#!/usr/bin/env python3
"""M646 (spec analyses/M646_spec.md Rev 1, Director review 2026-11-14): Cold-minus-Warm and Shoulder-minus-Warm contrast in the Compare charts.
Writes ONLY the new top-level key `cohortContrast` (and its `_artifactStamps` entry) of summary_arrays.json.
Descriptive difference between thermal classes (which are also calendar periods); never a temperature effect. No multiplicity correction, no p-value.
Usage: python tools/m646_cohort_contrast.py [--dry-run] [--stamp-only]"""
import copy, datetime, hashlib, json, os, sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
import eligibility as EL

NB, SEED = 4000, 42
FLOOR_DRIVES, FLOOR_DAYS, WEIGHT_CUT = 10, 5, 0.05
EFF_DAYS_MIN = 10.0            # R3: below this the contrast is exploratory (no verdict wording)
MAX_DROP = 0.01                # R4: above this the row is not estimable
CONTRASTS = ("cold", "shoulder")
SPEC = "analyses/M646_spec.md"
METRICS = {
    "M1": {"label": "Gross pack throughput per 100 km", "unit": "kWh/100 km", "num": lambda d: d["gross_throughput_kwh"] * 100.0, "den": lambda d: d["distance_km"],
           "defn": "100 x sum(gross_throughput_kwh) / sum(distance_km), canonical-clean drives with a gross energy integral (same definition as cohortSupport.metrics.grossKwhPer100km)", "need": ["gross_throughput_kwh", "distance_km"]},
    "M2": {"label": "Engine-on share of time", "unit": "% of time", "num": lambda d: d["engine_on_pct"] * d["duration_s"], "den": lambda d: d["duration_s"] * 100.0,
           "defn": "sum(engine_on_pct x duration_s) / (100 x sum(duration_s)) x 100, canonical-clean drives with a stored engine_on_pct", "need": ["engine_on_pct", "duration_s"], "scale": 100.0},
    "M3": {"label": "EV distance share", "unit": "% of distance", "num": lambda d: d["ev_dist_km"], "den": lambda d: d["distance_km"],
           "defn": "100 x sum(ev_dist_km) / sum(distance_km), canonical-clean drives with a defined ev_dist_km", "need": ["ev_dist_km", "distance_km"], "scale": 100.0},
}


def collapse(t):
    return "urban" if t == "urban" else "non-urban"


def effective_n(w):
    w = np.asarray(w, dtype=float)
    return float(1.0 / ((w / w.sum()) ** 2).sum()) if w.sum() > 0 else None


def load(label_col="thermal_regime_raw", strict=False):
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
    sdm = pd.read_csv(os.path.join(ROOT, "seasonal_drive_master.csv"), low_memory=False)
    flags = EL.load_flags(os.path.join(ROOT, "drive_master.csv"))
    ex = {r.file for r in flags.itertuples() if EL._true(r.ens_outlier_v2) or EL._true(r.ens_invalid)}     # explicit True only (cohort_arrays / cohort_support convention); a missing flag is never a licence to add a drive to a ratio that needs an integral
    d = dm[["file", "date", "distance_km", "duration_s", "gross_throughput_kwh", "engine_on_pct", "ev_dist_km", "drive_type"]].merge(
        sdm[["file", "thermal_regime_raw", "thermal_regime_physical"]], on="file", how="left")
    assert d["thermal_regime_raw"].notna().all(), "drives without a thermal class"
    d["date"] = d["date"].astype(str).str[:10]
    d["canon"] = ~d["file"].isin(ex)
    if strict:                                                            # sensitivity: a missing ens_outlier_v2 flag is never clean (eligibility.py / M639 convention)
        miss = set(flags.loc[flags["ens_outlier_v2"].isna(), "file"])
        d["canon"] = d["canon"] & ~d["file"].isin(miss)
    d["strat2"] = d["drive_type"].map(collapse)
    d["strat4"] = d["drive_type"]
    d["cohort"] = d[label_col]
    return d


def ref_weights(d, col):
    ref = d[d["canon"] & (d["distance_km"] > 0)]
    rk = ref.groupby(col)["distance_km"].sum()
    return rk / rk.sum(), ref


def metric_frame(d, mk):
    m = METRICS[mk]
    f = d[d["canon"]]
    f = f.dropna(subset=m["need"])
    f = f[f["distance_km"] > 0]                                  # spec section 2: distance_km > 0 for every metric
    out = f[["file", "date", "cohort", "strat2", "strat4", "distance_km"]].copy()
    out["N"], out["D"] = m["num"](f), m["den"](f)
    return out


def cell_tables(f, cohorts, col, strata, days):
    """day x (cohort, stratum) numerator / denominator matrices."""
    idx = {(c, s): i for i, (c, s) in enumerate((c, s) for c in cohorts for s in strata)}
    N = np.zeros((len(days), len(idx))); D = np.zeros_like(N)
    di = {x: i for i, x in enumerate(days)}
    for r in f[f["cohort"].isin(cohorts)].itertuples():
        s = getattr(r, col)
        if (r.cohort, s) in idx:
            N[di[r.date], idx[(r.cohort, s)]] += r.N; D[di[r.date], idx[(r.cohort, s)]] += r.D
    return idx, N, D


def stat(Ns, Ds, idx, c, w, strata, scale, adjusted):
    """Ns, Ds: (nrep, ncell) sums. Returns (nrep,) difference D(c) - D(warm); NaN where a needed cell is empty."""
    if not adjusted:
        def ratio(g):
            cols = [idx[(g, s)] for s in strata]
            return Ns[:, cols].sum(1) / np.where(Ds[:, cols].sum(1) > 0, Ds[:, cols].sum(1), np.nan)
        return scale * (ratio(c) - ratio("warm"))
    out = np.zeros(Ns.shape[0])
    for s in strata:
        rc = Ns[:, idx[(c, s)]] / np.where(Ds[:, idx[(c, s)]] > 0, Ds[:, idx[(c, s)]], np.nan)
        rw = Ns[:, idx[("warm", s)]] / np.where(Ds[:, idx[("warm", s)]] > 0, Ds[:, idx[("warm", s)]], np.nan)
        out = out + w[s] * (rc - rw)
    return scale * out


def support_of(f, g, strata=None, col="strat2"):
    x = f[f["cohort"] == g]
    if strata is not None:
        x = x[x[col].isin(strata)]
    return int(len(x)), int(x["date"].nunique())


def contrast(f, c, mk, w2, col="strat2", w=None, strata=None):
    m = METRICS[mk]; scale = m.get("scale", 1.0)
    w = w2 if w is None else w
    strata = list(w.index) if strata is None else strata
    cohorts = ["warm", c]
    sub = f[f["cohort"].isin(cohorts)]
    days = sorted(sub["date"].unique())
    idx, N, D = cell_tables(sub, cohorts, col, list(w.index), days)
    tot_N, tot_D = N.sum(0, keepdims=True), D.sum(0, keepdims=True)
    # supports (metric-eligible drives)
    sup = {g: {"nDrives": support_of(f, g)[0], "nDays": support_of(f, g)[1]} for g in cohorts}
    cells = {g: {s: dict(zip(("nDrives", "nDays"), support_of(f[f[col] == s], g))) for s in w.index} for g in cohorts}
    km_day = {g: f[f["cohort"] == g].groupby("date")["distance_km"].sum() for g in cohorts}
    eff = {g: round(effective_n(km_day[g].values), 2) if len(km_day[g]) else None for g in cohorts}
    window = {g: [str(f[f["cohort"] == g]["date"].min()), str(f[f["cohort"] == g]["date"].max())] for g in cohorts}
    floor_ok = all(sup[g]["nDrives"] >= FLOOR_DRIVES and sup[g]["nDays"] >= FLOOR_DAYS for g in cohorts)
    # adjusted: strata above the weight cut; a heavy unsupported cell makes D_adj not estimable; strata below the cut are excluded and the weights renormalised (R1)
    heavy = [s for s in w.index if w[s] >= WEIGHT_CUT]
    excluded_share = round(float(w[[s for s in w.index if s not in heavy]].sum()), 4)
    wr = (w[heavy] / w[heavy].sum()) if heavy else None
    unsup = [s for s in heavy if any(cells[g][s]["nDrives"] < FLOOR_DRIVES or cells[g][s]["nDays"] < FLOOR_DAYS for g in cohorts)]
    rng = np.random.default_rng(SEED)
    nd = len(days)
    K = np.bincount((rng.integers(0, nd, size=(NB, nd)) + np.arange(NB)[:, None] * nd).ravel(), minlength=NB * nd).reshape(NB, nd).astype(float)      # day multiplicities per replicate
    Ns, Ds = K @ N, K @ D
    res = {}
    for name, adjusted in (("raw", False), ("adjusted", True)):
        if not floor_ok:
            res[name] = {"estimable": False, "reason": "a cohort is below the floor of %d drives on %d days" % (FLOOR_DRIVES, FLOOR_DAYS)}
            continue
        if adjusted and unsup:
            res[name] = {"estimable": False, "reason": "route stratum %s is below the floor in a cohort (not estimable; the unadjusted difference is shown)" % ",".join(unsup)}
            continue
        pt = stat(tot_N, tot_D, idx, c, wr if adjusted else None, heavy if adjusted else list(w.index), scale, adjusted)[0]
        reps = stat(Ns, Ds, idx, c, wr if adjusted else None, heavy if adjusted else list(w.index), scale, adjusted)
        ok = np.isfinite(reps)
        dropped = int((~ok).sum()); drop_rate = dropped / NB
        ci = [round(float(np.percentile(reps[ok], 2.5)), 4), round(float(np.percentile(reps[ok], 97.5)), 4)] if ok.sum() > 100 else None
        # leave-one-day-out of the point estimate
        lodo = []
        for i in range(len(days)):
            keep = np.ones(len(days), bool); keep[i] = False
            Nn, Dn = N[keep].sum(0, keepdims=True), D[keep].sum(0, keepdims=True)
            v = stat(Nn, Dn, idx, c, wr if adjusted else None, heavy if adjusted else list(w.index), scale, adjusted)[0]
            if np.isfinite(v):
                lodo.append(float(v))
        entry = {"estimable": True, "estimate": round(float(pt), 4), "ci95": ci, "nDroppedReplicates": dropped, "dropRate": round(drop_rate, 4), "draws": NB, "seed": SEED,
                 "lodoRange": [round(min(lodo), 4), round(max(lodo), 4)] if lodo else None}
        if drop_rate > MAX_DROP or ci is None:
            entry.update(estimable=False, reason="more than %.0f %% of the bootstrap replicates were dropped for an empty cell (R4)" % (MAX_DROP * 100), ci95=None)
        res[name] = entry
    base = res.get("raw", {})
    ref_w = float(f[f["cohort"] == "warm"].pipe(lambda x: x["N"].sum() / x["D"].sum()) * scale)
    if base.get("estimable"):
        base["relativeToWarm"] = round(base["estimate"] / ref_w, 4) if ref_w else None
    exploratory = bool(any(e is None or e < EFF_DAYS_MIN for e in eff.values()))
    if not exploratory:
        for name in ("raw", "adjusted"):
            e = res[name]
            if e.get("estimable") and e.get("ci95"):
                e["reading"] = "interval excludes zero" if (e["ci95"][0] > 0 or e["ci95"][1] < 0) else "interval includes zero (not distinguished at this support)"
    disagree = None
    if res["raw"].get("estimable") and res["adjusted"].get("estimable"):
        sr, sa = res["raw"]["estimate"], res["adjusted"]["estimate"]
        ex_r = res["raw"]["ci95"] and (res["raw"]["ci95"][0] > 0 or res["raw"]["ci95"][1] < 0)
        ex_a = res["adjusted"]["ci95"] and (res["adjusted"]["ci95"][0] > 0 or res["adjusted"]["ci95"][1] < 0)
        disagree = bool(np.sign(sr) != np.sign(sa) or bool(ex_r) != bool(ex_a))
    return {"contrast": c + " minus warm", "support": sup, "effectiveDays": eff, "calendarWindows": window, "cells": cells, "exploratory": exploratory,
            "exploratoryRule": "fewer than %d effective days in a cohort (1 / sum of squared day km shares): point and interval shown, no verdict wording" % EFF_DAYS_MIN,
            "heavyStrata": heavy, "excludedWeightShare": excluded_share, "weights": {s: round(float(w[s]), 4) for s in w.index}, "raw": res["raw"], "adjusted": res["adjusted"],
            "routeMixDisagreement": disagree}


def point_only(f, c, mk, w, strata_col="strat2"):
    """Point difference used by the sensitivities (no interval)."""
    m = METRICS[mk]; scale = m.get("scale", 1.0)
    cohorts = ["warm", c]
    sub = f[f["cohort"].isin(cohorts)]
    out = {}
    g = {k: sub[sub["cohort"] == k] for k in cohorts}
    if any(len(v) == 0 for v in g.values()):
        return None
    out["raw"] = scale * (g[c]["N"].sum() / g[c]["D"].sum() - g["warm"]["N"].sum() / g["warm"]["D"].sum())
    adj = 0.0
    for s in w.index:
        a, b = g[c][g[c][strata_col] == s], g["warm"][g["warm"][strata_col] == s]
        if len(a) == 0 or len(b) == 0 or not a["D"].sum() > 0 or not b["D"].sum() > 0:
            adj = None
            break
        adj += w[s] * (a["N"].sum() / a["D"].sum() - b["N"].sum() / b["D"].sum())
    out["adjusted"] = None if adj is None else scale * adj
    return {k: (None if v is None else round(float(v), 4)) for k, v in out.items()}


def build():
    d = load()
    w2, ref = ref_weights(d, "strat2")
    w4, _ = ref_weights(d, "strat4")
    dp = load("thermal_regime_physical")
    blk = {"metrics": {}}
    for mk, m in METRICS.items():
        f = metric_frame(d, mk)
        fp = metric_frame(dp, mk)
        cb = {}
        for c in CONTRASTS:
            e = contrast(f, c, mk, w2)
            sens = {"physicalThresholdLabels": point_only(fp, c, mk, w2)}
            # without the largest drive of each cohort
            drop = {g: f[f["cohort"] == g].sort_values("distance_km").iloc[-1]["file"] for g in ("warm", c) if len(f[f["cohort"] == g])}
            sens["withoutLargestDriveOfEachCohort"] = point_only(f[~f["file"].isin(drop.values())], c, mk, w2)
            sens["fourDriveTypeStrata"] = point_only(f, c, mk, w4, "strat4")
            ds = load(strict=True); ws, _ = ref_weights(ds, "strat2")
            sens["missingEnsFlagNotClean"] = point_only(metric_frame(ds, mk), c, mk, ws)
            if mk == "M1":
                sens["driveKmAtLeast1"] = point_only(f[f["distance_km"] >= 1.0], c, mk, w2)      # the cohort-distribution basis (sub-1 km logs are noise-floor artefacts)
            if mk in ("M2", "M3"):
                alt = f.copy(); alt["N"] = (alt["N"] / alt["D"]); alt["D"] = alt["distance_km"]            # km-weighted mean of per-drive values
                sens["kmWeightedMeanOfPerDriveValues"] = point_only(alt.rename(columns={}), c, mk, w2)
            if not e["adjusted"].get("estimable"):                         # an unsupported route cell: no adjusted point value anywhere, sensitivities included
                for v in sens.values():
                    if isinstance(v, dict):
                        v["adjusted"] = None
            e["sensitivities"] = sens
            cb[c] = e
        blk["metrics"][mk] = {"label": m["label"], "unit": m["unit"], "definition": m["defn"], "contrasts": cb}
    # reproduction of the cohort ratios (spec section 7)
    rep = {}
    for mk in METRICS:
        f = metric_frame(d, mk); scale = METRICS[mk].get("scale", 1.0)
        rep[mk] = {g: round(float(f[f["cohort"] == g]["N"].sum() / f[f["cohort"] == g]["D"].sum() * scale), 4) for g in ("warm", "shoulder", "cold")}
    blk["cohortRatios"] = rep
    blk["referenceSet"] = {"definition": "canonical-clean drives (explicit ens flags True excluded) with distance_km > 0, all cohorts; one fixed km mix by route stratum (urban / non-urban)",
                           "nDrives": int(len(ref)), "nDays": int(ref["date"].nunique()), "kmShare": {s: round(float(w2[s]), 4) for s in w2.index}}
    md5 = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    blk["_provenance"] = {"generatedBy": "tools/m646_cohort_contrast.py", "spec": SPEC, "specGitBlob": os.popen('git hash-object "%s"' % os.path.join(ROOT, SPEC)).read().strip(),
                          "masterMd5": md5, "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest()}
    blk["method"] = ("Difference of cohort ratios of sums (cohort minus Warm), unadjusted and route-mix standardised (urban/non-urban only; fixed all-cohort km weights; strata below 5 % weight excluded with renormalisation). "
                     "Day-clustered percentile bootstrap, seed 42, 4000 draws, the calendar day resampled jointly over the union of days of the two cohorts with the weights fixed; a replicate with an empty cell is dropped and counted, "
                     "above 1 % dropped the row is not estimable. Floors: 10 drives on 5 days per cohort and per heavy route cell. Under 10 effective days a cohort makes the contrast exploratory (no verdict wording). "
                     "The 12 intervals are descriptive: no multiplicity correction, no p-value, never the word significant.")
    blk["caption"] = ("Difference between thermal classes (season, route, load and logging period move together), not a temperature effect. "
                      "Route-mix standardised (urban/non-urban only) removes only that mix. Not an article figure; article use requires the Opus audit and the owner's sign-off per the project rule.")
    return blk


def stamp(A):
    import stamp_common as _sc
    md5 = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    old = (A.get("_artifactStamps") or {}).get("cohortContrast")
    st = copy.deepcopy(A["_artifactStamps"]["cohortSupport"])
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for k in ("carriedForward", "recomputeMode", "corpusSizeAtRecompute"):
        st.pop(k, None)
    st.update(corpusHash=md5, generatedAt=now, computationStatus="computed", upstreamHashes={"driveMasterMd5": md5},
              computationStatusNote="M646: derived by tools/m646_cohort_contrast.py from drive_master.csv and seasonal_drive_master.csv (spec analyses/M646_spec.md Rev 1); descriptive contrast between thermal classes")
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A["_artifactStamps"]["cohortContrast"] = _sc.carry_declared(old, st)


def main(argv):
    dry = "--dry-run" in argv
    p = os.path.join(ROOT, "summary_arrays.json")
    raw = open(p, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    if "--stamp-only" in argv:
        stamp(A)
        open(p, "w", encoding="utf-8", newline="").write(json.dumps(A, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
        print("stamped")
        return 0
    blk = build()
    # reproduction check (spec section 7): M1 cohort ratios against cohortSupport
    for g in ("warm", "shoulder", "cold"):
        pub = A["cohortSupport"]["assigned"][g]["metrics"]["grossKwhPer100km"]["value"]
        if abs(blk["cohortRatios"]["M1"][g] - pub) > 5e-5:
            print("STOP: M1 %s ratio %.4f does not reproduce cohortSupport %.4f; nothing written" % (g, blk["cohortRatios"]["M1"][g], pub))
            return 3
    print(json.dumps({k: blk[k] for k in ("cohortRatios", "referenceSet")}, indent=1))
    if dry:
        return 0
    B = copy.deepcopy(A)
    B["cohortContrast"] = blk
    stamp(B)
    open(p, "w", encoding="utf-8", newline="").write(json.dumps(B, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
