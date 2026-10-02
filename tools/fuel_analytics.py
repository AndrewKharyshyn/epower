#!/usr/bin/env python3
"""M337 Fuel analytics v1 (spec analyses/M337_spec.md rev 2): FUEL-12 (rate integral vs counter), FUEL-01 (consumption vs trip length),
FUEL-11 (distribution and trend). Script-written payload key `fuelAnalytics`, additive leaf splice into summary_arrays.json (asserts no other leaf
changes, idempotent). Reads raw/ (basis: F03 provenance-sensitive), drive_master.csv, seasonal_drive_master.csv, raw_manifest.json. Never writes them.
Logger quantities are logged/app-calculated (Car Scanner ELM OBD2); no energy, cost, BSFC or generator quantity here.
Resampling unit: calendar day of the trip start; day-clustered percentile bootstrap, seed 42, 4000 draws; ratio-of-sums only.
Usage: XT_RAW_DIR=$PWD/raw python tools/fuel_analytics.py [--dry-run] [--no-write]"""
import hashlib, json, os, sys, re
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
os.environ.setdefault("XT_RAW_DIR", os.path.join(ROOT, "raw"))
import numpy as np, pandas as pd
import recon_engine as RE

ARR = os.path.join(ROOT, "summary_arrays.json")
NB, SEED = 4000, 42
DT_CAP = RE.DT_CAP
CNT, RATE = RE.CH["used"], RE.CH["flow"]
COOL, OIL = RE.CH["coolant"], RE.CH["oil"]
KM_EDGES = [0.5, 2, 5, 10, 20, np.inf]
BAND_LABELS = ["0.5-2", "2-5", "5-10", "10-20", "20+"]
TEMP_BANDS = ["<40C", "40-60C", ">=60C", "unknown"]
MIN_DAYS_CI, MIN_DAYS_LOWCLUSTER = 7, 5


def key_digits(n):
    d = re.sub(r"\D", "", n)
    return d[:8] + "_" + d[8:14] + ".csv" if len(d) >= 14 else None


def temp_band(x):
    return "unknown" if x is None or not np.isfinite(x) else ("<40C" if x < 40 else ("40-60C" if x < 60 else ">=60C"))


def read_trip(path):
    df = pd.read_csv(path, low_memory=False)
    t = pd.to_datetime(df["time"], errors="coerce")
    out = {"colCounter": CNT in df.columns, "colRate": RATE in df.columns}
    c = pd.to_numeric(df[CNT], errors="coerce") if CNT in df.columns else pd.Series(dtype=float)
    r = pd.to_numeric(df[RATE], errors="coerce") if RATE in df.columns else pd.Series(dtype=float)
    out["counterUsable"] = bool(len(c) and c.notna().sum() >= 2 and c.max() > c.min())
    out["rateUsable"] = bool(len(r) and (r.dropna() > 0).any())
    out["counter"], out["rate"], out["t"] = c, r, t
    for nm, col in (("cool", COOL), ("oil", OIL)):
        s = pd.to_numeric(df[col], errors="coerce") if col in df.columns else pd.Series(dtype=float)
        out[nm] = float(s.dropna().iloc[0]) if len(s) and s.notna().any() else np.nan
    return out


def integrate(t, r, i0t, i1t, cap, trap=False):
    """rate integral (L) on the rate series' OWN valid sample times inside [i0t, i1t]; dt capped; returns (V, gap_flag)."""
    m = r.notna()
    tt, rr = t[m], r[m]
    if len(tt) < 2:
        return np.nan, False
    dts = tt.diff().dt.total_seconds().fillna(0.0)
    win = (tt >= i0t) & (tt <= i1t)
    gap = bool((dts[win] > DT_CAP).any())
    dt = dts.clip(upper=cap)
    if trap:
        rm = (rr + rr.shift(1)).fillna(rr) / 2.0
        return float((rm / 3600.0 * dt)[win].sum()), gap
    return float((rr / 3600.0 * dt)[win].sum()), gap


def dayboot(df, stat, nb=NB, seed=SEED, key="day"):
    """generic day-clustered percentile bootstrap: stat(df_resampled) -> float or dict of floats."""
    days = df[key].unique()
    idx = {d: np.where(df[key].values == d)[0] for d in days}
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(nb):
        pick = rng.integers(0, len(days), len(days))
        out.append(stat(df.iloc[np.concatenate([idx[days[i]] for i in pick])]))
    if isinstance(out[0], dict):
        return {k: [float(np.nanpercentile([o[k] for o in out], 2.5)), float(np.nanpercentile([o[k] for o in out], 97.5))] for k in out[0]}
    return [float(np.nanpercentile(out, 2.5)), float(np.nanpercentile(out, 97.5))]


def ratio_ci(df, num, den, scale=1.0):
    """pooled ratio of sums with day-clustered CI via vectorised per-day sums."""
    day = df.groupby("day")[[num, den]].sum()
    A = day.values
    n = len(A)
    est = float(A[:, 0].sum() / A[:, 1].sum() * scale) if A[:, 1].sum() else None
    if n < 2 or est is None:
        return {"est": est, "ci95": None, "nTrips": int(len(df)), "nDays": int(n)}
    rng = np.random.default_rng(SEED)
    cnt = np.stack([np.bincount(rng.integers(0, n, n), minlength=n) for _ in range(NB)])
    S = cnt @ A
    with np.errstate(divide="ignore", invalid="ignore"):
        r = S[:, 0] / S[:, 1] * scale
    return {"est": round(est, 5), "ci95": [round(float(np.nanpercentile(r, 2.5)), 5), round(float(np.nanpercentile(r, 97.5)), 5)],
            "nTrips": int(len(df)), "nDays": int(n)}


def support(nd):
    return "ci" if nd >= MIN_DAYS_CI else ("low-cluster CI" if nd >= MIN_DAYS_LOWCLUSTER else "points only")


def wquantile(r, w, q):
    o = np.argsort(r)
    r, w = np.asarray(r)[o], np.asarray(w)[o]
    c = np.cumsum(w) / w.sum()
    return float(r[np.searchsorted(c, q, side="left")])


def qstats(df, w=None):
    r = df["rate100"].values
    return {f"q{int(q*100)}": (wquantile(r, df["km"].values, q) if w else float(np.percentile(r, q * 100))) for q in (0.1, 0.25, 0.5, 0.75, 0.9)}


def main():
    dry = "--dry-run" in sys.argv
    dm = pd.read_csv("drive_master.csv")
    sm = pd.read_csv("seasonal_drive_master.csv")[["file", "thermal_regime"]]
    man = {r["record_id"]: r for r in json.load(open("raw_manifest.json", encoding="utf-8"))["files"]}
    names = {key_digits(n): n for n in os.listdir("raw") if key_digits(n)}
    cohort = dict(zip(sm.file.map(key_digits), sm.thermal_regime))
    rec, why = [], {"outlier_or_no_km": 0, "no_raw": 0, "no_counter_or_rate": 0}
    elig_contract = 0
    for _, m in dm.iterrows():
        k = key_digits(m["file"])
        if str(m.get("ens_outlier_v2")) == "True" or not (float(m["distance_km"]) > 0):
            why["outlier_or_no_km"] += 1; continue
        if k not in names:
            why["no_raw"] += 1; continue
        p = os.path.join("raw", names[k])
        T = read_trip(p)
        if not (T["counterUsable"] and T["rateUsable"]):
            why["no_counter_or_rate"] += 1; continue
        elig_contract += 1
        c, r, t = T["counter"], T["rate"], T["t"]
        i0, i1 = c.first_valid_index(), c.last_valid_index()
        t0, t1 = t.loc[i0], t.loc[i1]
        cv = c.dropna()
        dec = float((cv.diff().dropna()).min()) if len(cv) > 1 else 0.0
        incs = cv.diff().dropna()
        pos = incs[incs > 0]
        V_cnt = float(c.loc[i1] - c.loc[i0])
        row = {"id": k, "day": k[:4] + "-" + k[4:6] + "-" + k[6:8], "km": float(m["distance_km"]), "V_cnt": V_cnt, "minDecrease": dec,
               "minPosIncrement": float(pos.min()) if len(pos) else np.nan, "durationS": float(m["duration_s"]) if pd.notna(m.get("duration_s")) else np.nan,
               "dSocPp": float(m["soc_end"] - m["soc_start"]) if pd.notna(m.get("soc_start")) and pd.notna(m.get("soc_end")) else np.nan,
               "cohort": cohort.get(k, "unknown"), "dType": m["drive_type"],
               "startCoolant": T["cool"], "startOil": T["oil"]}
        V5, gap = integrate(t, r, t0, t1, DT_CAP)
        row["V_int"], row["gap"] = V5, gap
        row["V_int_trap"], _ = integrate(t, r, t0, t1, DT_CAP, trap=True)
        row["V_int_cap2"], _ = integrate(t, r, t0, t1, 2.0)
        row["V_int_cap10"], _ = integrate(t, r, t0, t1, 10.0)
        mf = man.get(k, {})
        row["hashPass"] = bool(mf and hashlib.sha256(open(p, "rb").read()).hexdigest() == mf.get("sha256"))
        sc = row["startCoolant"]
        row["tempSource"] = "coolant" if np.isfinite(sc) else ("oil" if np.isfinite(row["startOil"]) else "none")
        row["tempBand"] = temp_band(sc if np.isfinite(sc) else row["startOil"])
        rec.append(row)
    d = pd.DataFrame(rec)
    # resolutions measured from the logged values (script-written; spec item 9)
    res_cnt = float(d.minPosIncrement.min())
    reset_thr = max(0.01, 2 * res_cnt)
    floor = max(0.05, 10 * res_cnt)
    d["reset"] = d.minDecrease < -reset_thr
    n_reset = int(d.reset.sum())
    ok = d[~d.reset].copy()
    ok["rate100"] = 100.0 * ok.V_cnt / ok.km
    recon = {"contractEligibleAfterOutlierKmMask": elig_contract, "excludedReset": n_reset, "analysisEligible": int(len(ok)), "auditReference": 234,
             "notIn": why, "counterResolutionL": round(res_cnt, 6), "resetThresholdL": reset_thr, "relDiffFloorL": floor,
             "eligibilityRule": "ELIG-A (fuelContract): counter >=2 numeric with max>min AND rate any value >0; canonical-clean (ens_outlier_v2 not True), km>0"}
    # ---------------- FUEL-12 ----------------
    f12 = ok.copy()
    f12["d"] = f12.V_int - f12.V_cnt
    f12["m"] = (f12.V_int + f12.V_cnt) / 2
    f12["rel"] = np.where(f12.m >= floor, f12.d / f12.m, np.nan)
    f12["flag5"] = f12.rel.abs() > 0.05
    f12 = f12.dropna(subset=["V_int"])

    def agg(x, col="V_int"):
        return ratio_ci(x.assign(dd=x[col] - x.V_cnt), "dd", "V_cnt")
    a12 = agg(f12)
    variants = {k: agg(f12, c) for k, c in (("trapezoid", "V_int_trap"), ("cap2s", "V_int_cap2"), ("cap10s", "V_int_cap10"))}
    variants["gapFreeTripsBase"] = agg(f12[~f12.gap])
    variants["gappedTripsBase"] = agg(f12[f12.gap]) if f12.gap.sum() >= 3 else {"note": "<3 gapped trips"}
    sens_f03 = {"hashPass": agg(f12[f12.hashPass]), "hashFail": agg(f12[~f12.hashPass]),
                "note": "not a paired test: hash-passing and hash-failing files are date-confounded; read-only raw-vs-originals fuel check in analyses/M337_f03_fuel_check_result.md"}
    lo, hi, pt = a12["ci95"][0], a12["ci95"][1], a12["est"]
    stop12 = bool(lo > 0.01 or hi < -0.01 or abs(pt) > 0.01)
    f12r = {"definition": "sum(V_int - V_cnt)/sum(V_cnt); positive = rate integral above counter; V_cnt = counter(last valid) - counter(first valid); V_int = rate integral on the rate's own valid sample times inside that window, dt capped at 5 s",
            "aggregate": a12, "alsoOverMeanVolume": round(float(f12.d.sum() / f12.m.sum()), 5),
            "perTripRelMedianIqr": [round(float(f12.rel.median()), 5), round(float(f12.rel.quantile(.25)), 5), round(float(f12.rel.quantile(.75)), 5)],
            "nRelativeShown": int(f12.rel.notna().sum()), "nBelowFloor": int(f12.rel.isna().sum()), "nFlag5pct": int(f12.flag5.sum()),
            "integrationVariants": variants, "f03Sensitivity": sens_f03, "auditR9Reference": {"trips": 234, "aggregateRelDiff": 0.0024, "role": "regression reference for the frozen audit data, not an acceptance tolerance"},
            "stopRuleTriggered": stop12, "stopRule": "CI lower > +1% or CI upper < -1% or |point| > 1% of counter volume",
            "limits": "both series come from the same app: agreement does not establish independence or external accuracy"}
    # ---------------- FUEL-01 ----------------
    s01 = ok[ok.km >= 0.5].copy()
    s01["band"] = pd.cut(s01.km, KM_EDGES, right=False, labels=BAND_LABELS)
    bands = []
    for b in BAND_LABELS:
        g = s01[s01.band == b]
        e = {"band": b, "nTrips": int(len(g)), "nDays": int(g.day.nunique())}
        if len(g):
            e["support"] = support(e["nDays"])
            if e["nDays"] >= MIN_DAYS_LOWCLUSTER:
                e["pooledL100"] = ratio_ci(g, "V_cnt", "km", 100.0)
            tb = {}
            for tbn in TEMP_BANDS:
                gg = g[g.tempBand == tbn]
                if len(gg):
                    tb[tbn] = {"nTrips": int(len(gg)), "nDays": int(gg.day.nunique()), "support": support(int(gg.day.nunique()))}
                    if gg.day.nunique() >= MIN_DAYS_LOWCLUSTER:
                        tb[tbn]["pooledL100"] = ratio_ci(gg, "V_cnt", "km", 100.0)
            e["byStartTemp"] = tb
        bands.append(e)
    short = ok[ok.km < 0.5]
    f01r = {"eligibility": "ELIG-A, no reset, km >= 0.5 (identical ids in both panels); trip fuel = counter delta; rate = 100*V/km", "bands": bands,
            "pooledAll": ratio_ci(s01, "V_cnt", "km", 100.0),
            "shortTripsNotInRatePanels": {"n": int(len(short)), "note": "km < 0.5: litres-versus-duration view only"},
            "limits": "rates are not SoC-corrected (charge-sustaining balance) and SoC change confounds short trips; any fitted line would be descriptive, not a startup-fuel intercept"}
    # ---------------- FUEL-11 ----------------
    def dist_stat(df):
        if len(df) < 3:
            return None
        return {"tripWeighted": {k: round(v, 3) for k, v in qstats(df).items()}, "distanceWeighted": {k: round(v, 3) for k, v in qstats(df, True).items()}}

    def dist_with_ci(df):
        est = dist_stat(df)
        if est is None or df.day.nunique() < MIN_DAYS_LOWCLUSTER:
            return {"nTrips": int(len(df)), "nDays": int(df.day.nunique()), "support": "points only", "est": est}
        def st(x):
            o = {}
            for kind, w in (("trip", None), ("dist", True)):
                for k, v in qstats(x, w).items():
                    o[f"{kind}_{k}"] = v
            return o
        ci = dayboot(df, st)
        return {"nTrips": int(len(df)), "nDays": int(df.day.nunique()), "support": support(int(df.day.nunique())), "est": est,
                "ci95": {k: [round(a, 3), round(b, 3)] for k, (a, b) in ci.items()}}
    primary = ok[ok.km >= 2]
    f11 = {"distribution": {"primary_km_ge_2": dist_with_ci(primary), "sens_km_ge_0.5": dist_with_ci(ok[ok.km >= 0.5]), "sens_km_ge_5": dist_with_ci(ok[ok.km >= 5]),
                            "byCohort": {c: dist_with_ci(primary[primary.cohort == c]) for c in sorted(primary.cohort.unique())}},
           "weighting": "tripWeighted = type-7 empirical quantile of trip L/100 km; distanceWeighted = lowest rate with cumulative km share >= q; recomputed on every day-resample"}
    ok["date"] = pd.to_datetime(ok.day)
    anchor = (ok.date.min() - pd.Timedelta(days=ok.date.min().weekday())).normalize()

    def trend(win):
        w = ok.copy()
        w["win"] = ((w.date - anchor).dt.days // win).astype(int)
        out = []
        for wi, g in w.groupby("win"):
            gk = g[g.km >= 0.5]
            e = {"start": str((anchor + pd.Timedelta(days=int(wi) * win)).date()), "days": win, "nTrips": int(len(g)), "nDays": int(g.day.nunique()),
                 "litres": round(float(g.V_cnt.sum()), 3), "km": round(float(g.km.sum()), 1), "support": support(int(g.day.nunique())),
                 "shareKmInTripsUnder5km": round(float(g[g.km < 5].km.sum() / g.km.sum()), 3),
                 "shareTripsStartCoolantUnder40C": round(float((g.tempBand == "<40C").mean()), 3)}
            if g.day.nunique() >= MIN_DAYS_LOWCLUSTER:
                e["pooledL100"] = ratio_ci(g, "V_cnt", "km", 100.0)
            else:
                e["pooledL100"] = {"est": round(float(g.V_cnt.sum() / g.km.sum() * 100), 4), "ci95": None}
            out.append(e)
        return out
    f11["trend"] = {"primaryWindowDays": 14, "secondaryWindowDays": 7, "windowAnchor": str(anchor.date()) + " (Monday)", "nonOverlapping": True,
                    "emptyWindows": "gaps (no interpolation)", "windows14": trend(14), "windows7": trend(7)}
    f11["limits"] = "short-trip and thermal-composition drift can be misread as a seasonal trend; composition annotations are per window; rates are not SoC-corrected"
    trips = [{"id": r.id, "day": r.day, "km": round(r.km, 3), "V_cnt": round(r.V_cnt, 4), "V_int": None if not np.isfinite(r.V_int) else round(r.V_int, 4),
              "durationS": None if not np.isfinite(r.durationS) else round(r.durationS, 0), "dSocPp": None if not np.isfinite(r.dSocPp) else round(r.dSocPp, 1),
              "startCoolant": None if not np.isfinite(r.startCoolant) else round(r.startCoolant, 1), "tempBand": r.tempBand, "tempSource": r.tempSource,
              "cohort": r.cohort, "gap": bool(r.gap), "hashPass": bool(r.hashPass), "reset": bool(r.reset)} for r in d.itertuples()]
    block = {"_provenance": "GENERATED by tools/fuel_analytics.py (M337) from raw/ fuel columns, drive_master.csv, seasonal_drive_master.csv, raw_manifest.json. Do not hand-edit.",
             "schemaVersion": 1, "basis": "logged/app-calculated fuel counter and rate (Car Scanner ELM OBD2); raw/ basis, provenance-sensitive (F03); not M299-reproducible",
             "inputs": {"driveMasterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()},
             "method": "day-clustered percentile bootstrap (seed 42, 4000 draws), ratio-of-sums; day = trip start date; interval only with >=7 distinct days (5-6 low-cluster, <5 points only)",
             "reconciliation": recon, "fuel12": f12r, "fuel01": f01r, "fuel11": f11, "trips": trips}
    json.dump(block, open(os.path.join("analyses", "M337_fuel_analytics_preview.json"), "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False, default=float)
    print(json.dumps({"reconciliation": recon, "fuel12": {k: f12r[k] for k in ("aggregate", "alsoOverMeanVolume", "perTripRelMedianIqr", "nFlag5pct", "stopRuleTriggered")},
                      "variants": variants, "f03": sens_f03}, indent=1, default=float))
    if "--no-write" in sys.argv:
        return
    A = json.load(open(ARR, encoding="utf-8"))
    before = {k: json.dumps(v, sort_keys=True) for k, v in A.items() if k != "fuelAnalytics"}
    status = "added" if "fuelAnalytics" not in A else ("unchanged" if A["fuelAnalytics"] == json.loads(json.dumps(block, default=float)) else "replaced")
    A["fuelAnalytics"] = json.loads(json.dumps(block, default=float))
    assert before == {k: json.dumps(v, sort_keys=True) for k, v in A.items() if k != "fuelAnalytics"}
    if not dry and status != "unchanged":
        with open(ARR, "w", encoding="utf-8", newline="\n") as f:
            json.dump(A, f, ensure_ascii=False, indent=1)
    print(json.dumps({"fuelAnalytics": status}))


if __name__ == "__main__":
    main()
