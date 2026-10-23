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
import copy, json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
import joint_day_bootstrap as JB          # M491 (spec analyses/M491_spec.md Rev 2): joint calendar-day bootstrap of the Warm/Shoulder difference

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
    ("starts_100km", "Pack-current direction reversals (not an engine-start count)", "/100 km", "ratio", "n_sign_crossings", "distance_km",
     "ratio of sums; n_sign_crossings counts pack-current direction reversals, a different quantity from RPM onsets, not an engine-start count"),
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
    diff = bs - bw  # independent cohort-stratified day bootstraps: kept as the stored sensitivity ci95IndependentCohorts (M491)
    dw = w.groupby("day")[["gross_throughput_kwh", "distance_km"]].sum().rename(columns={"gross_throughput_kwh": "num", "distance_km": "den"})
    ds = s.groupby("day")[["gross_throughput_kwh", "distance_km"]].sum().rename(columns={"gross_throughput_kwh": "num", "distance_km": "den"})
    jd, jra, jrb, jdrop, nunion, nshared = JB.joint_difference(dw, ds, rngJ, B * 2)
    sd, sdrop = JB.stratified_difference(dw, ds, rngS, B * 2)
    for _v, _n in (("joint", jdrop), ("stratified", sdrop)):
        if _n > JB.DROP_CAP * B * 2:
            raise SystemExit("M491 STOP: %d of %d %s draws discarded in band %r (cap %.1f %%): Director decision needed" % (_n, B * 2, _v, label, JB.DROP_CAP * 100))
    out["difference"] = {"estimate": round(es - ew, 2), "ci95": JB.interval(jd), "direction": "Shoulder minus Warm",
                         "method": "joint calendar-day bootstrap (dates shared by both cohorts resampled together), B=4000, seed=%d (stream SEED+2)" % SEED,
                         "ci95IndependentCohorts": q(diff), "ci95Stratified": JB.interval(sd),
                         "nSharedDates": nshared, "nUnionDates": nunion, "bootstrapCorrelation": round(float(np.corrcoef(jra, jrb)[0, 1]), 3),
                         "nDrawsDropped": jdrop, "nDrawsDroppedStratified": sdrop, "seed": SEED, "B": B * 2}
    out["status"] = "observed" if min(len(w), len(s)) >= MIN_N and min(gw, gs) >= MIN_DAYS else "insufficient_support"
    return out


# M465: Cold column of the urban contrast: point estimate only (ratio of sums), NO interval and NO difference, because the cold urban set rests on
# fewer than EXPLORATORY_DAYS calendar days (same floor as the regeneration display, >= 10 drives on >= 5 days); cohort boundary is a display band.
EXPLORATORY_DAYS = 5
uc = d[d.classKey.eq("urban") & d.thermal_regime.eq("cold") & d.gross_throughput_kwh.notna() & d.distance_km.gt(0)].copy()


def cold_cell(g):
    if not len(g):
        return None
    nd = int(g.day.nunique())
    return {"estimate": round(float(100 * g.gross_throughput_kwh.sum() / g.distance_km.sum()), 2), "ci95": None, "nDrives": int(len(g)), "nDays": nd,
            "km": round(float(g.distance_km.sum()), 1),
            "status": "observed" if (len(g) >= MIN_N and nd >= EXPLORATORY_DAYS) else "exploratory_no_interval"}


rng2 = np.random.default_rng(SEED + 1)
rngJ, rngS = np.random.default_rng(SEED + 2), np.random.default_rng(SEED + 3)       # M491: dedicated streams, so the per-cohort intervals (rng2) are consumed exactly as before
bands = [("all urban trips", u)]
for lo, hi, lab in ((0, 3, "< 3 km"), (3, 10, "3–10 km"), (10, 1e9, "≥ 10 km")):
    bands.append((lab, u[(u.distance_km >= lo) & (u.distance_km < hi)]))
urban = [contrast(g, lab, rng2) for lab, g in bands]
_cold_bands = [uc] + [uc[(uc.distance_km >= lo) & (uc.distance_km < hi)] for lo, hi in ((0, 3), (3, 10), (10, 1e9))]
for _b, _g in zip(urban, _cold_bands):
    _b["cold"] = cold_cell(_g)
soc = {c: {"socCeilingMedian": round(float(u[u.thermal_regime.eq(c)].soc_max.median()), 2),
           "tripKmMedian": round(float(u[u.thermal_regime.eq(c)].distance_km.median()), 2),
           "nDrives": int(u.thermal_regime.eq(c).sum())} for c in ("warm", "shoulder")}
soc["cold"] = {"socCeilingMedian": round(float(uc.soc_max.median()), 2), "tripKmMedian": round(float(uc.distance_km.median()), 2), "nDrives": int(len(uc))} if len(uc) else None

A = json.load(open(P("summary_arrays.json"), encoding="utf-8"))
counts = {c: int(d.thermal_regime.eq(c).sum()) for c in ("warm", "shoulder", "cold")}
cold_days = int(d.loc[d.thermal_regime.eq("cold"), "date"].nunique())      # M426: the caveat follows the full support rule (drives AND days)
A["comparisonCube"] = {
    "_meta": {"milestone": "M297", "basisNDrivesClean": int(len(d)), "basisNDrives": int(len(dm)),
              "eligibility": "canonical_clean (ens_invalid / ens_outlier_v2 excluded)",
              "minSupport": {"drives": MIN_N, "days": MIN_DAYS},
              "uncertainty": f"percentile bootstrap, calendar day as cluster, B={B}, seed={SEED}", "B": B,
              "contrastUncertainty": f"Warm-vs-Shoulder difference: joint calendar-day bootstrap over the union of dates, {B * 2} draws, seed={SEED} (stream SEED+2); the independent-cohort interval (ci95IndependentCohorts) and a date-type stratified interval (ci95Stratified, SEED+3) are stored sensitivities; M491",
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
                      "caveat": ("Descriptive seasonal operating difference; Cold not observed." if not (counts["cold"] >= MIN_N and cold_days >= MIN_DAYS) else
                                 "Descriptive seasonal operating difference (Warm vs Shoulder, with an interval and a difference). Cold (n=%d clean drives, %d urban) is shown as a point estimate only, exploratory, no interval and no difference: its urban set rests on too few calendar days." % (counts["cold"], len(uc)))},
}
st = copy.deepcopy(A["_artifactStamps"]["highwayVsCity"])
st["computationStatus"] = "computed"
st["computationStatusNote"] = "M297: typed class x cohort comparison cube + urban Warm-vs-Shoulder contrast (m297_comparison_cube.py)."
A["_artifactStamps"]["comparisonCube"] = st
json.dump(A, open(P("summary_arrays.json"), "w", encoding="utf-8", newline=chr(10)), ensure_ascii=False, indent=1)      # M491: LF on every platform (a Windows run wrote CRLF)
from collections import Counter
print("rows:", len(rows), Counter(r["status"] for r in rows))
for b in urban:
    print(b["band"], b.get("status"), b["warm"] and b["warm"]["estimate"], b["shoulder"] and b["shoulder"]["estimate"],
          b["difference"] and (b["difference"]["estimate"], b["difference"]["ci95"]))
print(soc)
