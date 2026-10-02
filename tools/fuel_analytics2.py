#!/usr/bin/env python3
"""M339 Fuel analytics v2 (spec analyses/M339_spec.md rev 3): FUEL-03 fuel by speed state and FUEL-02 warm-up trajectory.
Script-written payload keys `fuelStates` and `fuelWarmup` (additive splice into summary_arrays.json, artifact stamps, idempotent).
Reads raw/ (basis: F03 provenance-sensitive), drive_master.csv, seasonal_drive_master.csv, raw_manifest.json; never writes them.
Logged/app-calculated fuel (Car Scanner ELM OBD2). States are temporal states of the logged rate, not fuel-source allocations. Associations only.
Clock: the rate series' own valid sample times; each interval is owned by its END sample (backward dt, capped at 5 s); state taken at that sample.
Resampling unit: calendar day of the trip start; day-clustered percentile bootstrap, seed 42, 4000 draws; ratio-of-sums only.
Usage: XT_RAW_DIR=$PWD/raw python tools/fuel_analytics2.py [--no-write] [--limit N]"""
import hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("XT_RAW_DIR", os.path.join(ROOT, "raw"))
import numpy as np, pandas as pd
import recon_engine as RE
import fuel_analytics as fa

ARR = os.path.join(ROOT, "summary_arrays.json")
SPD_VCM, SPD_OBD = "[VCM] Vehicle Speed (km/h)", RE.CH["speed"]
MIN_NATIVE, TOL = 20, 1.5                      # pipeline speed-priority floor; nearest-sample tolerance (s)
THRS = [0.5, 1.0, 2.0, 3.0]
PRIMARY_THR, DWELL_S, DEADBANDS = 1.0, 5.0, [0.1, 0.5, 1.0]
TIME_GRID = np.arange(30, 601, 30.0)           # s since t0
DIST_GRID = np.arange(0.25, 5.01, 0.25)        # km since t0
INTERVALS = np.arange(0.0, 5.0, 0.5)
STALE_S = 120.0                                # maximum age of the initial coolant sample before t0
BANDS = ["<40C", "40-60C", ">=60C"]
BAND_LABEL = {"<40C": "initial coolant < 40 C", "40-60C": "initial coolant 40-60 C", ">=60C": "start with coolant >= 60 C (warm-engine start)", "oil-fallback": "initial temperature from oil (fallback; separate stratum)"}


def load_trip(raw, off, window_cols=("time",)):
    """rate-clock arrays inside the counter window; speed per the project priority rule (VCM if >= 20 native samples else OBD)."""
    g = RE.load_drive(raw, off)
    if g is None:
        return None
    df = pd.read_csv(RE.BASE + raw, low_memory=False, usecols=lambda c: c in ("time", RE.CH["used"], SPD_VCM, SPD_OBD))
    t = pd.to_datetime(df["time"], errors="coerce")
    cnt = RE._ser(df, t, RE.CH["used"])
    if cnt is None or len(cnt) < 2:
        return None
    vcm = RE._ser(df, t, SPD_VCM)
    use_vcm = vcm is not None and len(vcm) >= MIN_NATIVE
    src = SPD_VCM if use_vcm else SPD_OBD
    ss = vcm if use_vcm else RE._ser(df, t, SPD_OBD)
    if ss is not None:
        m = pd.merge_asof(g[["t"]], ss.rename(columns={"v": "spd"}), on="t", direction="nearest", tolerance=pd.Timedelta("1500ms"))
        g["spd"] = m["spd"].values
    else:
        g["spd"] = np.nan
    t0c, t1c = cnt["t"].iloc[0], cnt["t"].iloc[-1]
    g["tsec"] = (g["t"] - g["t"].iloc[0]).dt.total_seconds()
    w = (g["t"] >= t0c) & (g["t"] <= t1c)
    g = g[w].reset_index(drop=True)
    if len(g) < 3:
        return None
    raw_dt = g["t"].diff().dt.total_seconds().fillna(0.0).values
    return {"g": g, "rawDt": raw_dt, "spdSrc": "VCM" if use_vcm else "OBD", "spdValues": ss["v"].values if ss is not None else np.array([]),
            "Vcnt": float(cnt["v"].iloc[-1] - cnt["v"].iloc[0])}


def classify(speed, raw_dt, cap, thr, dwell):
    """0 stationary, 1 moving, 2 unknown speed; state of each interval is taken at its END sample; dwell: a stationary run shorter than DWELL_S is moving."""
    st = np.where(np.isnan(speed), 2, np.where(speed <= thr, 0, 1)).astype(int)
    if dwell:
        dt = np.minimum(raw_dt, cap)
        i, n = 0, len(st)
        while i < n:
            if st[i] == 0:
                j = i
                while j + 1 < n and st[j + 1] == 0:
                    j += 1
                if dt[i:j + 1].sum() < DWELL_S:
                    st[i:j + 1] = 1
                i = j + 1
            else:
                i += 1
    return st


def litres_by_state(flow, raw_dt, speed, cap, thr, dwell=False):
    dt = np.minimum(raw_dt, cap)
    dt = np.where(np.arange(len(dt)) == 0, 0.0, dt)
    lit = np.nan_to_num(flow) / 3600.0 * dt
    st = classify(speed, raw_dt, cap, thr, dwell)
    return {"stationary": float(lit[st == 0].sum()), "moving": float(lit[st == 1].sum()), "unknown": float(lit[st == 2].sum()), "total": float(lit.sum())}


def curves_for_trip(g, raw_dt):
    """FUEL-02 per-trip grid values. Returns dict or a reason string. Contribution ends at the trip end, a rate gap above 5 s or the first unknown-speed sample (distance axis)."""
    flow = np.nan_to_num(g["flow"].values)
    rpm = g["rpm"].values
    on = (np.nan_to_num(rpm) > 400) & (flow > 0)
    if not on.any():
        return "noT0"
    i0 = int(np.argmax(on))
    capped = np.minimum(raw_dt, fa.DT_CAP)
    capped[0] = 0.0
    lit = flow / 3600.0 * capped
    spd = g["spd"].values
    tsec = g["tsec"].values
    # initial temperature: latest valid coolant at or before t0 within STALE_S; oil as fallback
    def initial(col):
        v = g[col].values[: i0 + 1]
        ok = np.where(np.isfinite(v))[0]
        if not len(ok):
            return None
        k = ok[-1]
        age = tsec[i0] - tsec[k]
        return (float(v[k]), float(age)) if age <= STALE_S else None
    ic, io = initial("coolant"), initial("oil")
    src, tmp = ("coolant", ic) if ic else (("oil-fallback", io) if io else (None, None))
    ev_km = float(np.nansum(np.nan_to_num(spd[: i0 + 1]) / 3600.0 * capped[: i0 + 1]))
    out = {"i0": i0, "leftCensored": i0 == 0, "preT0S": float(tsec[i0] - tsec[0]), "evKmBeforeT0": round(ev_km, 3), "tempSource": src,
           "tempC": tmp[0] if tmp else None, "tempAgeS": tmp[1] if tmp else None}
    # end of contribution (time axis): first rate gap > cap after t0, else trip end
    after = np.arange(i0 + 1, len(g))
    gap = [k for k in after if raw_dt[k] > fa.DT_CAP]
    k_end = (gap[0] - 1) if gap else len(g) - 1
    out["endReasonTime"] = "gap" if gap else "tripEnd"
    cumL = np.cumsum(lit[i0:]) - lit[i0]
    ts = tsec[i0:] - tsec[i0]
    n_t = k_end - i0 + 1
    tv = []
    for gp in TIME_GRID:
        tv.append(float(np.interp(gp, ts[:n_t], cumL[:n_t])) if gp <= ts[n_t - 1] else np.nan)
    out["timeCum"] = tv
    # distance axis: contribution also ends at the first unknown-speed sample after t0
    unk = [k for k in after if np.isnan(spd[k])]
    k_end_d = min(k_end, unk[0] - 1) if unk else k_end
    out["endReasonDist"] = "unknownSpeed" if (unk and unk[0] - 1 < k_end) else out["endReasonTime"]
    st = classify(spd, raw_dt, fa.DT_CAP, PRIMARY_THR, False)
    dkm = np.nan_to_num(spd) / 3600.0 * capped
    cumD = np.cumsum(dkm[i0:]) - dkm[i0]
    cumS = np.cumsum(np.where(st == 0, lit, 0.0)[i0:]) - np.where(st == 0, lit, 0.0)[i0]
    cumM = np.cumsum(np.where(st == 1, lit, 0.0)[i0:]) - np.where(st == 1, lit, 0.0)[i0]
    n_d = k_end_d - i0 + 1
    dd = cumD[:n_d]
    dtot, dstat, dmov = [], [], []
    mono = np.maximum.accumulate(dd)
    for gp in DIST_GRID:
        if n_d >= 2 and gp <= mono[-1]:
            dtot.append(float(np.interp(gp, mono, cumL[:n_d]))); dstat.append(float(np.interp(gp, mono, cumS[:n_d]))); dmov.append(float(np.interp(gp, mono, cumM[:n_d])))
        else:
            dtot.append(np.nan); dstat.append(np.nan); dmov.append(np.nan)
    out["distCumTotal"], out["distCumStationary"], out["distCumMoving"] = dtot, dstat, dmov
    # interval consumption: moving samples only, 0.5 km intervals of distance since t0, only intervals completed before censoring
    ivl = []
    for lo in INTERVALS:
        hi = lo + 0.5
        if n_d >= 2 and mono[-1] >= hi:
            sel = np.arange(i0, i0 + n_d)
            pos = cumD[: n_d]
            inw = (pos > lo) & (pos <= hi) & (st[sel] == 1)
            ivl.append((float(lit[sel][inw].sum()), float(dkm[sel][inw].sum())))
        else:
            ivl.append((np.nan, np.nan))
    out["intervals"] = ivl
    return out


def pointwise(df, valcol):
    """mean cumulative litres per contributing trip (sum of litres / number of trips), day-clustered pointwise CI when n >= 10 trips and >= 7 days."""
    d = df.assign(one=1.0)
    n, nd = int(len(d)), int(d.day.nunique())
    e = fa.ratio_ci(d, valcol, "one")
    ok = n >= 10 and nd >= fa.MIN_DAYS_CI
    return {"n": n, "days": nd, "est": e["est"], "ci95": e["ci95"] if ok else None, "support": "pointwise CI" if ok else "points only"}


def main():
    nowrite = "--no-write" in sys.argv
    lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 0
    dm = pd.read_csv("drive_master.csv")
    sm = pd.read_csv("seasonal_drive_master.csv")[["file", "thermal_regime"]]
    cohort = dict(zip(sm.file.map(fa.key_digits), sm.thermal_regime))
    man = {r["record_id"]: r for r in json.load(open("raw_manifest.json", encoding="utf-8"))["files"]}
    names = {fa.key_digits(n): n for n in os.listdir("raw") if fa.key_digits(n)}
    prev = json.load(open(ARR, encoding="utf-8")).get("fuelAnalytics", {})
    ok_ids = {t["id"] for t in prev.get("trips", []) if not t["reset"]}
    expected = len(ok_ids)
    rows, curves, speed_vals = [], {}, {"VCM": [], "OBD": []}
    excl = {"noT0": 0, "noInitialTemp": 0, "leftCensored": 0}
    for _, m in dm.iterrows():
        k = fa.key_digits(m["file"])
        if k not in ok_ids or k not in names:
            continue
        off = float(m["I_offset_A_applied"]) if pd.notna(m.get("I_offset_A_applied")) else np.nan
        T = load_trip(names[k], off)
        if T is None:
            continue
        g, raw_dt = T["g"], T["rawDt"]
        flow, spd = g["flow"].values, g["spd"].values
        speed_vals[T["spdSrc"]].append(T["spdValues"])
        row = {"id": k, "day": k[:4] + "-" + k[4:6] + "-" + k[6:8], "km": float(m["distance_km"]), "dType": m["drive_type"], "cohort": cohort.get(k, "unknown"),
               "spdSrc": T["spdSrc"], "Vcnt": T["Vcnt"],
               "hashPass": bool(man.get(k) and hashlib.sha256(open(os.path.join("raw", names[k]), "rb").read()).hexdigest() == man[k].get("sha256"))}
        # FUEL-03 variants
        for cap in (2.0, 5.0, 10.0):
            row[f"cap{int(cap)}"] = litres_by_state(flow, raw_dt, spd, cap, PRIMARY_THR)
        for thr in THRS:
            for dw in (False, True):
                row[f"thr{thr:g}{'d' if dw else ''}"] = litres_by_state(flow, raw_dt, spd, fa.DT_CAP, thr, dw)
        capped = np.minimum(raw_dt, fa.DT_CAP); capped[0] = 0.0
        row["lostS"] = float(np.maximum(raw_dt - fa.DT_CAP, 0).sum()); row["totalS"] = float(raw_dt.sum())
        row["lostL"] = float((np.nan_to_num(flow) / 3600.0 * np.maximum(raw_dt - fa.DT_CAP, 0)).sum())
        row["kmSpeedIntegral"] = float(np.nansum(np.nan_to_num(spd) / 3600.0 * capped))
        # charging sub-state (needs a battery offset and HV current/voltage)
        if np.isfinite(off) and g["Pbatt"].notna().any():
            st = classify(spd, raw_dt, fa.DT_CAP, PRIMARY_THR, False)
            lit = np.nan_to_num(flow) / 3600.0 * capped
            pb = np.nan_to_num(g["Pbatt"].values)
            row["charging"] = {f"db{d:g}": {"stationary": float(lit[(st == 0) & (pb < -d)].sum()), "moving": float(lit[(st == 1) & (pb < -d)].sum())} for d in DEADBANDS}
        else:
            row["charging"] = None
        # FUEL-02
        c = curves_for_trip(g, raw_dt)
        if isinstance(c, str):
            excl["noT0"] += 1; row["warm"] = {"excluded": c}
        else:
            reason = "leftCensored" if c["leftCensored"] else ("noInitialTemp" if c["tempSource"] is None else None)
            if reason:
                excl[reason] += 1
            row["warm"] = {k2: c[k2] for k2 in ("leftCensored", "preT0S", "evKmBeforeT0", "tempSource", "tempC", "tempAgeS", "endReasonTime", "endReasonDist")}
            row["warm"]["excluded"] = reason
            if not reason:
                curves[k] = c
        rows.append(row)
        if lim and len(rows) >= lim:
            break
    d = pd.DataFrame([{k: v for k, v in r.items() if k not in ("warm", "charging")} for r in rows])
    # ----- FUEL-03 aggregates -----
    for r_, base in zip(rows, d.index):
        pass
    def share(df, var, state):
        x = pd.DataFrame({"day": df.day.values, "num": [r[var][state] for r in df.rows], "den": [r[var]["total"] for r in df.rows]})
        return fa.ratio_ci(x, "num", "den")
    d["rows"] = rows
    d["band"] = pd.cut(d.km, fa.KM_EDGES, right=False, labels=fa.BAND_LABELS).astype(str)
    primary = f"thr{PRIMARY_THR:g}"
    groups = {"all": d, **{f"band {b}": d[d.band == b] for b in fa.BAND_LABELS}, **{f"driveType {t}": g_ for t, g_ in d.groupby("dType")},
              **{f"cohort {c}": g_ for c, g_ in d.groupby("cohort")}}
    out3 = {"groups": {}}
    for gname, gdf in groups.items():
        nd = int(gdf.day.nunique())
        e = {"nTrips": int(len(gdf)), "nDays": nd, "support": fa.support(nd), "litres": round(float(sum(r[primary]["total"] for r in gdf.rows)), 3)}
        if len(gdf) and nd >= fa.MIN_DAYS_LOWCLUSTER:
            for s_ in ("stationary", "moving", "unknown"):
                e[s_ + "Share"] = share(gdf, primary, s_)
        elif len(gdf):
            tot = sum(r[primary]["total"] for r in gdf.rows)
            for s_ in ("stationary", "moving", "unknown"):
                e[s_ + "Share"] = {"est": round(sum(r[primary][s_] for r in gdf.rows) / tot, 5) if tot else None, "ci95": None}
        out3["groups"][gname] = e
    variants = {}
    for key in [f"thr{t:g}{'d' if dw else ''}" for t in THRS for dw in (False, True)] + ["cap2", "cap5", "cap10"]:
        variants[key] = {s_: share(d, key, s_)["est"] for s_ in ("stationary", "moving", "unknown")}
    out3["variants"] = variants
    out3["strata"] = {"vcmOnlyStationary": share(d[d.spdSrc == "VCM"], primary, "stationary") if (d.spdSrc == "VCM").sum() >= 5 else {"note": "<5 VCM trips"},
                      "obdOnlyStationary": share(d[d.spdSrc == "OBD"], primary, "stationary") if (d.spdSrc == "OBD").sum() >= 5 else {"note": "<5 OBD trips"},
                      "nVcm": int((d.spdSrc == "VCM").sum()), "nObd": int((d.spdSrc == "OBD").sum()),
                      "hashPassStationary": share(d[d.hashPass], primary, "stationary"), "hashFailStationary": share(d[~d.hashPass], primary, "stationary"),
                      "f03Note": "not a paired test: date-confounded; speed/HV columns raw-vs-originals unchecked (needs Andrii's permission)"}
    chg = [r for r in rows if r["charging"]]
    out3["chargingSubState"] = {"nTripsWithBatteryInputs": len(chg), "nExcluded": len(rows) - len(chg),
                                "note": "fuel consumed during net pack charging: a temporal state, not a fuel-source allocation; battery offset is estimated; hash-passing trips are the primary basis, hash-failing trips have rounded raw/ current (F03-unchecked)",
                                "byDeadbandKw": {f"db{dbd:g}": {"hashPass": {"stationary": round(sum(r["charging"][f"db{dbd:g}"]["stationary"] for r in chg if r["hashPass"]), 3),
                                                                           "moving": round(sum(r["charging"][f"db{dbd:g}"]["moving"] for r in chg if r["hashPass"]), 3)},
                                                              "all": {"stationary": round(sum(r["charging"][f"db{dbd:g}"]["stationary"] for r in chg), 3),
                                                                      "moving": round(sum(r["charging"][f"db{dbd:g}"]["moving"] for r in chg), 3)}} for dbd in DEADBANDS}}
    tot5 = sum(r["cap5"]["total"] for r in rows)
    out3["coverage"] = {"lostSecondsShare": round(sum(r["lostS"] for r in rows) / sum(r["totalS"] for r in rows), 5), "lostLitresShare": round(sum(r["lostL"] for r in rows) / (tot5 + sum(r["lostL"] for r in rows)), 5),
                        "totalLitresIntegral": round(tot5, 3), "counterLitres": round(sum(r["Vcnt"] for r in rows), 3),
                        "integralOverCounter": round(tot5 / sum(r["Vcnt"] for r in rows) - 1.0, 5),
                        "partitionMaxAbsErrL": float(max(abs(r[primary]["stationary"] + r[primary]["moving"] + r[primary]["unknown"] - r[primary]["total"]) for r in rows))}
    km_bad = float(np.mean([abs(r["kmSpeedIntegral"] - r["km"]) / r["km"] > 0.05 for r in rows]))
    out3["speedResolutionKmh"] = {s: (round(float(np.min(np.diff(np.unique(np.concatenate(v))))), 4) if v and len(np.concatenate(v)) > 1 else None) for s, v in speed_vals.items()}
    out3["kmCheck"] = {"shareTripsAbove5pct": round(km_bad, 3), "toleranceFlag": 0.05}
    # ----- FUEL-02 aggregates -----
    cd = []
    for r in rows:
        if r["id"] in curves:
            c = curves[r["id"]]
            band = c["tempSource"] if c["tempSource"] == "oil-fallback" else fa.temp_band(c["tempC"])
            cd.append({"id": r["id"], "day": r["day"], "band": band, "cohort": r["cohort"], "c": c})
    out2 = {"alignment": "first rate sample with rpm > 400 and rate > 0 inside the counter window (left-censored trips excluded and counted)",
            "initialTempMaxStalenessS": STALE_S, "bands": {b: BAND_LABEL[b] for b in BANDS + ["oil-fallback"]}, "timeGridS": TIME_GRID.tolist(), "distGridKm": DIST_GRID.tolist(),
            "intervalsKm": [[float(a), float(a + 0.5)] for a in INTERVALS], "excluded": excl, "nAnalysis": len(rows), "nCurves": len(cd), "expectedTripsFromFuelAnalytics": expected,
            "pointwiseNote": "CIs are pointwise (day-clustered bootstrap), not simultaneous bands", "groups": {}}
    sets = {"all": (0, 0), "h300": (300.0, 2.5), "h600": (600.0, 5.0)}
    for cname in ("all", "warm", "shoulder"):
        for band in BANDS + ["oil-fallback"]:
            sub = [x for x in cd if x["band"] == band and (cname == "all" or x["cohort"] == cname)]
            ent = {"nTrips": len(sub), "nDays": len({x["day"] for x in sub}), "sets": {}}
            for sname, (th, dh) in sets.items():
                s_t = {}
                for ax, grid, keys in (("time", TIME_GRID, ["timeCum"]), ("dist", DIST_GRID, ["distCumTotal", "distCumStationary", "distCumMoving"])):
                    for key in keys:
                        pts = []
                        thr_idx = (len(grid) - 1) if sname != "all" else None
                        for j, gp in enumerate(grid):
                            members = [x for x in sub if np.isfinite(x["c"][key][j]) and (sname == "all" or np.isfinite(x["c"][("timeCum" if ax == "time" else "distCumTotal")][
                                int(np.argmin(np.abs(grid - (th if ax == "time" else dh))))]))]
                            if not members:
                                pts.append({"pos": float(gp), "n": 0, "days": 0, "est": None, "ci95": None, "support": "no trips"}); continue
                            df = pd.DataFrame({"day": [x["day"] for x in members], "lit": [x["c"][key][j] for x in members]})
                            pts.append({"pos": float(gp), **pointwise(df, "lit")})
                        s_t[key] = pts
                ent["sets"][sname] = s_t
            iv = []
            for j, lo in enumerate(INTERVALS):
                mem = [x for x in sub if np.isfinite(x["c"]["intervals"][j][0])]
                if not mem:
                    iv.append({"fromKm": float(lo), "n": 0, "support": "no trips"}); continue
                df = pd.DataFrame({"day": [x["day"] for x in mem], "lit": [x["c"]["intervals"][j][0] for x in mem], "km": [x["c"]["intervals"][j][1] for x in mem]})
                e = fa.ratio_ci(df, "lit", "km", 100.0)
                ok = len(mem) >= 10 and df.day.nunique() >= fa.MIN_DAYS_CI
                iv.append({"fromKm": float(lo), "n": int(len(mem)), "days": int(df.day.nunique()), "est": e["est"], "ci95": e["ci95"] if ok else None,
                           "support": "pointwise CI" if ok else "points only", "label": "moving-sample L/100 km"})
            ent["intervalConsumption"] = iv
            out2["groups"][f"{cname}|{band}"] = ent
    last = {b: {"h600": int(sum(1 for x in cd if x["band"] == b and np.isfinite(x["c"]["timeCum"][-1]))), "h600dist": int(sum(1 for x in cd if x["band"] == b and np.isfinite(x["c"]["distCumTotal"][-1]))),
               "h300": int(sum(1 for x in cd if x["band"] == b and np.isfinite(x["c"]["timeCum"][9]))), "h250km": int(sum(1 for x in cd if x["band"] == b and np.isfinite(x["c"]["distCumTotal"][9])))} for b in BANDS + ["oil-fallback"]}
    out2["constantPopulationCounts"] = last
    out2["censoring"] = {"timeEnd": {k2: int(sum(1 for x in cd if x["c"]["endReasonTime"] == k2)) for k2 in ("tripEnd", "gap")},
                         "distEnd": {k2: int(sum(1 for x in cd if x["c"]["endReasonDist"] == k2)) for k2 in ("tripEnd", "gap", "unknownSpeed")}}
    out2["tripRows"] = [{"id": r["id"], **{k2: v for k2, v in r["warm"].items()}} for r in rows]
    # ----- stop conditions -----
    sp = [variants[k]["stationary"] for k in variants]
    caps = {k: sum(r[k]["total"] for r in rows) for k in ("cap2", "cap10")}
    vcm = out3["strata"]["vcmOnlyStationary"].get("est") if isinstance(out3["strata"]["vcmOnlyStationary"], dict) else None
    hp, hf = out3["strata"]["hashPassStationary"]["est"], out3["strata"]["hashFailStationary"]["est"]
    thr_sp = (variants["thr3"]["stationary"] - variants["thr0.5"]["stationary"])
    stops = {"excludedOver20pct": (sum(excl.values()) / max(len(rows), 1)) > 0.20, "capLitres2vs10Over2pct": abs(caps["cap2"] / caps["cap10"] - 1.0) > 0.02,
             "kmMismatchOver5pctOnOver10pctTrips": km_bad > 0.10, "vcmOnlyShiftOver2pp": (vcm is not None and abs(vcm - variants[primary]["stationary"]) > 0.02),
             "stationaryShiftOver5ppAcrossThresholds": abs(thr_sp) > 0.05, "stationaryShiftOver5ppAcrossCapsDwell": (max(sp) - min(sp)) > 0.05,
             "unknownShareOver10pct": variants[primary]["unknown"] > 0.10, "hashPassVsFailOver5pp": (hp is not None and hf is not None and abs(hp - hf) > 0.05),
             "constantPopLast<10or<7days": {b: v["h600"] < 10 for b, v in last.items()}, "partitionFailed": out3["coverage"]["partitionMaxAbsErrL"] > 1e-9}
    out3["stopConditions"] = stops
    out3["_provenance"] = "GENERATED by tools/fuel_analytics2.py (M339). Do not hand-edit."
    out2["_provenance"] = out3["_provenance"]
    for blk in (out3, out2):
        blk.update({"schemaVersion": 1, "basis": "logged/app-calculated fuel rate (Car Scanner ELM OBD2); raw/ basis, provenance-sensitive (F03); not M299-reproducible; temporal states, associations only",
                    "method": "day-clustered percentile bootstrap (seed 42, 4000 draws), ratio-of-sums; interval only with >= 10 trips and >= 7 distinct days at a position (shares: >= 7 days; 5-6 low-cluster; < 5 points only)",
                    "inputs": {"driveMasterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()}})
    out3["tripRows"] = [{"id": r["id"], "day": r["day"], "km": round(r["km"], 3), "cohort": r["cohort"], "dType": r["dType"], "spdSrc": r["spdSrc"], "hashPass": r["hashPass"],
                         "litres": round(r["cap5"]["total"], 4), "stationary": round(r[primary]["stationary"], 4), "moving": round(r[primary]["moving"], 4), "unknown": round(r[primary]["unknown"], 4)} for r in rows]
    out3["nAnalysis"], out3["expectedTripsFromFuelAnalytics"] = len(rows), expected
    prev_path = os.path.join("analyses", "M339_fuel_analytics2_preview.json")
    json.dump({"fuelStates": out3, "fuelWarmup": out2}, open(prev_path, "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False, default=float)
    print(json.dumps({"n": len(rows), "expected": expected, "excl": excl, "stops": stops, "coverage": out3["coverage"], "speedRes": out3["speedResolutionKmh"],
                      "primary": variants[primary], "nCurves": len(cd)}, indent=1, default=float))
    if nowrite:
        return
    import copy, datetime
    A = json.load(open(ARR, encoding="utf-8"))
    skip = ("fuelStates", "fuelWarmup", "_artifactStamps")
    before = {k: json.dumps(v, sort_keys=True) for k, v in A.items() if k not in skip}
    stamps_before = {k: json.dumps(v, sort_keys=True) for k, v in A["_artifactStamps"].items() if k not in ("fuelStates", "fuelWarmup")}
    new = {"fuelStates": json.loads(json.dumps(out3, default=float)), "fuelWarmup": json.loads(json.dumps(out2, default=float))}
    status = "unchanged" if all(A.get(k) == v for k, v in new.items()) else "written"
    live = out3["inputs"]["driveMasterMd5"]
    for key in new:
        A[key] = new[key]
        old = A["_artifactStamps"].get(key)
        if not (isinstance(old, dict) and old.get("corpusHash") == live and status == "unchanged"):
            st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
            st.update(corpusHash=live, generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
                      computationStatusNote="M339: computed by tools/fuel_analytics2.py from raw/ fuel/speed columns and the master; additive, no published value recomputed; not M299-reproducible.", upstreamHashes=dict(out3["inputs"]))
            st.pop("carriedForward", None)
            A["_artifactStamps"][key] = st
    assert before == {k: json.dumps(v, sort_keys=True) for k, v in A.items() if k not in skip}
    assert stamps_before == {k: json.dumps(v, sort_keys=True) for k, v in A["_artifactStamps"].items() if k not in ("fuelStates", "fuelWarmup")}
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A, f, ensure_ascii=False, indent=1)
    print(json.dumps({"payload": status}))


if __name__ == "__main__":
    main()
