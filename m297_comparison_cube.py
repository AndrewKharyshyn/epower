#!/usr/bin/env python3
"""m297_comparison_cube.py (M297, 2026-09-25) — typed drive-class x thermal-cohort Comparison cube and the
urban-only Warm-vs-Shoulder contrast (audit 2026-09-24 §3A, implementation order step 3).

Replaces the practice of filtering pre-formatted strings (highwayVsCity) with typed rows:
  {metricId, label, unit, estimand, classKey, cohortKey, estimate, nDrives, nDays, km, interval, eligibility, status}
computed from drive_master.csv (+ seasonal_drive_master.csv cohort labels), READ-ONLY.

Rules
  * eligibility: canonical-clean (ens_invalid / ens_outlier_v2 == True excluded) for every metric.
  * rates are ratio-of-sums over paired-eligible drives; distributional metrics are pooled medians with IQR.
  * uncertainty: percentile bootstrap with CALENDAR DAY as the resampling cluster (drives and engine events
    within a day are not independent replicates), B = 2000, fixed seed.
  * status: 'observed' (n >= 10 drives and >= 3 days), 'insufficient_support' (1-9 drives or < 3 days; estimate
    shown, flagged), 'not_observed' (0 drives -> estimate null, never zero).
  * Cold: no drives -> every cell 'not_observed'.
The urban contrast restricts both cohorts to clean urban drives, reports per-cohort ratio-of-sums energy
intensity with day-cluster CIs, their difference with a cohort-stratified day bootstrap, and the same
contrast inside trip-length bands (route duration confounding), plus descriptive SoC-ceiling medians.
Idempotent; writes top-level `comparisonCube` and stamps it from the `highwayVsCity` stamp (same corpus).
"""
import copy, json, os
import numpy as np, pandas as pd

W = os.path.dirname(os.path.abspath(__file__)); P = lambda n: os.path.join(W, n)
B, SEED = 2000, 20260925
MIN_N, MIN_DAYS = 10, 3
CLASSES = [("urban", "Urban"), ("mixed", "Mixed"), ("mixed_highway", "Mixed Highway"), ("highway", "Highway")]
COHORTS = ["all", "warm", "shoulder", "cold"]

dm = pd.read_csv(P("drive_master.csv"), low_memory=False)
reg = pd.read_csv(P("seasonal_drive_master.csv"), low_memory=False)[["file", "thermal_regime"]]
d = dm.merge(reg, on="file", how="left")
flag = lambda c: d[c].astype(str).str.strip().str.lower().eq("true")
d = d[~(flag("ens_invalid") | flag("ens_outlier_v2"))].copy()
d["day"] = d["date"].astype(str)
d["classKey"] = d["drive_type"].astype(str).str.strip().str.lower().replace({"city": "urban"})
d["soc_band_pp"] = d["soc_max"] - d["soc_min"]

# (metricId, label, unit, kind, numerator, denominator/column, estimand text)
METRICS = [
    ("energy_intensity", "Pack gross throughput", "kWh/100 km", "ratio", "gross_throughput_kwh", "distance_km",
     "ratio of sums, 100·Σkwh/Σkm"),
    ("gross_discharge_100km", "Pack gross discharge", "kWh/100 km", "ratio", "gross_discharge_kwh", "distance_km",
     "ratio of sums, 100·Σkwh/Σkm (outbound battery work)"),
    ("starts_100km", "Engine-start proxy (current sign crossings)", "/100 km", "ratio", "n_sign_crossings", "distance_km",
     "ratio of sums; n_sign_crossings is a start PROXY, not a counted start"),
    ("engoff_brake_share", "Engine-off braking share of pack charge", "%", "share", "charge_pure_regen_kwh", "gross_charge_kwh",
     "ratio of sums, 100·Σ engine-off braking charge / Σ pack charge (operating-state proxy, not metered regen)"),
    ("engine_on_pct", "Engine-on share of drive time", "%", "median", "engine_on_pct", None, "pooled median [IQR] over drives"),
    ("soc_ceiling", "SoC ceiling (drive max)", "%", "median", "soc_max", None, "pooled median [IQR] over drives"),
    ("soc_floor", "SoC floor (drive min)", "%", "median", "soc_min", None, "pooled median [IQR] over drives"),
    ("soc_band", "SoC band (max − min)", "pp", "median", "soc_band_pp", None, "pooled median [IQR] over drives"),
    ("ev_dist_pct", "Engine-off (EV) distance share", "%", "median", "ev_dist_pct", None, "pooled median [IQR] over drives"),
    ("speed_moving", "Moving mean speed", "km/h", "median", "speed_mean_moving", None, "pooled median [IQR] over drives"),
    ("trip_km", "Trip distance", "km", "median", "distance_km", None, "pooled median [IQR] over drives"),
]


def _clusters(g, cols):
    return {day: gg[cols].to_numpy(float) for day, gg in g.groupby("day")}


def ratio_stat(g, num, den, scale=100.0, rng=None):
    e = g[g[num].notna() & g[den].notna() & (g[den] > 0)]
    if not len(e):
        return None, e
    days = e.groupby("day")[[num, den]].sum()
    n, dd = days[num].to_numpy(float), days[den].to_numpy(float)
    est = scale * n.sum() / dd.sum()
    G = len(days); idx = rng.integers(0, G, size=(B, G))
    bs = scale * n[idx].sum(1) / dd[idx].sum(1)
    lo, hi = np.quantile(bs, [0.025, 0.975])
    return {"estimate": round(float(est), 3), "interval": {"lo": round(float(lo), 3), "hi": round(float(hi), 3),
            "method": "percentile bootstrap, cluster = calendar day", "B": B}}, e


def median_stat(g, col, rng=None):
    e = g[g[col].notna()]
    if not len(e):
        return None, e
    vals = e[col].to_numpy(float)
    groups = [gg[col].to_numpy(float) for _, gg in e.groupby("day")]
    G = len(groups); meds = np.empty(B)
    for b in range(B):
        pick = rng.integers(0, G, size=G)
        meds[b] = np.median(np.concatenate([groups[i] for i in pick]))
    lo, hi = np.quantile(meds, [0.025, 0.975])
    q1, q3 = np.quantile(vals, [0.25, 0.75])
    return {"estimate": round(float(np.median(vals)), 2), "iqr": [round(float(q1), 2), round(float(q3), 2)],
            "interval": {"lo": round(float(lo), 2), "hi": round(float(hi), 2),
                         "method": "percentile bootstrap of the median, cluster = calendar day", "B": B}}, e


rows = []
rng = np.random.default_rng(SEED)
for ck, clabel in CLASSES:
    for coh in COHORTS:
        base = d[d.classKey.eq(ck)] if coh == "all" else d[d.classKey.eq(ck) & d.thermal_regime.eq(coh)]
        for mid, lab, unit, kind, a, b_, estd in METRICS:
            r = {"metricId": mid, "label": lab, "unit": unit, "estimand": estd, "classKey": ck, "classLabel": clabel,
                 "cohortKey": coh, "eligibility": "canonical_clean"}
            if not len(base):
                r.update({"estimate": None, "interval": None, "nDrives": 0, "nDays": 0, "km": 0.0, "status": "not_observed"})
                rows.append(r); continue
            if kind in ("ratio", "share"):
                st, e = ratio_stat(base, a, b_, rng=rng)
            else:
                st, e = median_stat(base, a, rng=rng)
            n, nd = int(len(e)), int(e["day"].nunique()) if len(e) else 0
            if st is None:
                r.update({"estimate": None, "interval": None, "nDrives": 0, "nDays": 0, "km": 0.0, "status": "not_observed"})
            else:
                r.update(st); r.update({"nDrives": n, "nDays": nd, "km": round(float(e["distance_km"].clip(lower=0).sum()), 1),
                                        "status": "observed" if (n >= MIN_N and nd >= MIN_DAYS) else "insufficient_support"})
            rows.append(r)

# ---- urban-only Warm vs Shoulder contrast (clean) ----
u = d[d.classKey.eq("urban") & d.thermal_regime.isin(["warm", "shoulder"])
      & d.gross_throughput_kwh.notna() & d.distance_km.gt(0)].copy()


def cohort_ratio(g, rng):
    days = g.groupby("day")[["gross_throughput_kwh", "distance_km"]].sum()
    n, k = days.gross_throughput_kwh.to_numpy(float), days.distance_km.to_numpy(float)
    G = len(days); idx = rng.integers(0, G, size=(B * 2, G))
    return 100 * n.sum() / k.sum(), 100 * n[idx].sum(1) / k[idx].sum(1), G


def contrast(g, label, rng):
    w, s = g[g.thermal_regime.eq("warm")], g[g.thermal_regime.eq("shoulder")]
    out = {"band": label, "warm": None, "shoulder": None, "difference": None}
    if len(w) < 3 or len(s) < 3:
        out["status"] = "insufficient_support"; out["nWarm"], out["nShoulder"] = int(len(w)), int(len(s)); return out
    ew, bw, gw = cohort_ratio(w, rng); es, bs, gs = cohort_ratio(s, rng)
    q = lambda a: [round(float(x), 2) for x in np.quantile(a, [0.025, 0.975])]
    out["warm"] = {"estimate": round(ew, 2), "ci95": q(bw), "nDrives": int(len(w)), "nDays": gw, "km": round(float(w.distance_km.sum()), 1)}
    out["shoulder"] = {"estimate": round(es, 2), "ci95": q(bs), "nDrives": int(len(s)), "nDays": gs, "km": round(float(s.distance_km.sum()), 1)}
    diff = bs - bw  # independent cohort-stratified day bootstraps
    out["difference"] = {"estimate": round(es - ew, 2), "ci95": q(diff), "direction": "Shoulder minus Warm",
                         "method": "cohort-stratified calendar-day bootstrap (days resampled within each cohort), B=4000"}
    out["status"] = "observed" if min(len(w), len(s)) >= MIN_N and min(gw, gs) >= MIN_DAYS else "insufficient_support"
    return out


rng2 = np.random.default_rng(SEED + 1)
bands = [("all urban trips", u)]
for lo, hi, lab in ((0, 3, "< 3 km"), (3, 10, "3–10 km"), (10, 1e9, "≥ 10 km")):
    bands.append((lab, u[(u.distance_km >= lo) & (u.distance_km < hi)]))
urban = [contrast(g, lab, rng2) for lab, g in bands]
soc = {c: {"socCeilingMedian": round(float(u[u.thermal_regime.eq(c)].soc_max.median()), 2),
           "tripKmMedian": round(float(u[u.thermal_regime.eq(c)].distance_km.median()), 2),
           "nDrives": int(u.thermal_regime.eq(c).sum())} for c in ("warm", "shoulder")}

A = json.load(open(P("summary_arrays.json"), encoding="utf-8"))
counts = {c: int(d.thermal_regime.eq(c).sum()) for c in ("warm", "shoulder", "cold")}
A["comparisonCube"] = {
    "_meta": {"milestone": "M297", "basisNDrivesClean": int(len(d)), "basisNDrives": int(len(dm)),
              "eligibility": "canonical_clean (ens_invalid / ens_outlier_v2 excluded)",
              "minSupport": {"drives": MIN_N, "days": MIN_DAYS},
              "uncertainty": f"percentile bootstrap, calendar day as cluster, B={B}, seed={SEED}", "B": B,
              "statusCodes": {"obs": "observed", "thin": "insufficient_support (estimate shown, flagged)", "none": "not_observed (null, not zero)"},
              "cohortCountsClean": counts,
              "note": ("Typed rows (metric x drive class x thermal cohort). Classes absent from a cohort are 'not_observed' "
                       "with null estimates, never zero. Engine events are nested in drives and days, so every interval "
                       "resamples calendar days, never events. Route mix differs sharply between cohorts (Shoulder is "
                       "urban-only), so cross-cohort comparisons are valid only within a class.")},
    # compact schema (M297, Project-size budget): metric metadata once; rows carry only typed values.
    "metrics": {m[0]: {"label": m[1], "unit": m[2], "estimand": m[6]} for m in METRICS},
    "rowKeys": {"m": "metricId", "c": "classKey", "k": "cohortKey", "est": "estimate", "iqr": "IQR [q1,q3]",
                "ci": "95% CI [lo,hi]", "n": "drives", "d": "calendar days", "km": "km", "st": "status"},
    "rows": [{k: v for k, v in {"m": r["metricId"], "c": r["classKey"], "k": r["cohortKey"], "est": r.get("estimate"),
              "iqr": r.get("iqr"), "ci": ([r["interval"]["lo"], r["interval"]["hi"]] if r.get("interval") else None),
              "n": r["nDrives"], "d": r["nDays"], "km": r["km"],
              "st": {"observed": "obs", "insufficient_support": "thin", "not_observed": "none"}[r["status"]]}.items()
              if v is not None} for r in rows],
    "urbanContrast": {"bands": urban, "descriptive": soc,
                      "estimand": ("urban-only, canonical-clean paired drives; pack gross throughput per 100 km by "
                                   "thermal cohort (ratio of sums). Confounded by calendar period, trip mix, load and "
                                   "cabin heating (no HVAC telemetry); not a chemistry effect."),
                      "caveat": "Descriptive seasonal operating difference; Cold not observed."},
}
st = copy.deepcopy(A["_artifactStamps"]["highwayVsCity"])
st["computationStatus"] = "computed"
st["computationStatusNote"] = "M297: typed class x cohort comparison cube + urban Warm-vs-Shoulder contrast (m297_comparison_cube.py)."
A["_artifactStamps"]["comparisonCube"] = st
json.dump(A, open(P("summary_arrays.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
from collections import Counter
print("rows:", len(rows), Counter(r["status"] for r in rows))
for b in urban:
    print(b["band"], b.get("status"), b["warm"] and b["warm"]["estimate"], b["shoulder"] and b["shoulder"]["estimate"],
          b["difference"] and (b["difference"]["estimate"], b["difference"]["ci95"]))
print(soc)
