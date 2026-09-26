#!/usr/bin/env python3
"""refresh_seasonal_kpis.py (M284, external audit Section 9: per-cohort CI/ESS plumbing).

Refreshes seasonalCharts.charts.{EnergyIntensity, CohortExposure} to the CURRENT corpus (drive_master.csv +
seasonal_drive_master.csv) and attaches a per-cohort 95 % interval to the scalar KPI:

  estimator  : paired-eligible ratio-of-sums, 100*sum(gross_throughput_kwh)/sum(distance_km), over drives with
               BOTH quantities present and distance_km > 0 (numerator/denominator over the same drives)
  interval   : percentile bootstrap, cluster = calendar day (drives on one day are not independent), B = 4000,
               fixed seed => byte-reproducible
  ESS        : Kish effective number of independent days, (sum w)^2 / sum w^2 with w = eligible km per day

Idempotent; touches only the two chart keys and seasonalCharts._staleness.refreshedCharts. Run AFTER any
regeneration of summary_arrays.json (like patch_m284_data.py).
"""
import csv, json, os, sys
from collections import defaultdict
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
# layout-agnostic: flat project checkout (drive_master.csv beside the scripts) or work/{seasonal,track3,track4}/ tree
WORK = os.environ.get("XT_WORK") or (_HERE if os.path.exists(os.path.join(_HERE, "drive_master.csv")) else os.path.dirname(_HERE))
SDIR = os.path.join(WORK, "seasonal") if os.path.isdir(os.path.join(WORK, "seasonal")) else WORK
sys.path.insert(0, SDIR)
import seasonal_core as sc  # noqa: E402

B, SEED, ALPHA = 4000, 20260919, 0.05
COH = [("all", lambda r: True), ("warm", lambda r: r["thermal_regime"] == "warm"),
       ("shoulder", lambda r: r["thermal_regime"] == "shoulder"), ("cold", lambda r: r["thermal_regime"] == "cold")]

def _f(x):
    try: return float(x) if x not in (None, "", "None") else None
    except ValueError: return None

def load():
    dm = {r["file"]: r for r in csv.DictReader(open(os.path.join(WORK, "drive_master.csv"), newline=""))}
    rows = []
    for r in csv.DictReader(open(os.path.join(SDIR, "seasonal_drive_master.csv"), newline="")):
        m = dm[r["file"]]
        rows.append({"file": r["file"], "date": r["date"], "thermal_regime": r["thermal_regime"],
                     "distance_km": _f(m.get("distance_km")), "gross_throughput_kwh": _f(m.get("gross_throughput_kwh")),
                     "ambient_time_mean_c": _f(r.get("ambient_time_mean_c")),
                     # M295: canonical exclusion flags (only an explicit True excludes; unscored NaN stays in)
                     "excluded": str(m.get("ens_invalid")).strip().lower() == "true"
                                 or str(m.get("ens_outlier_v2")).strip().lower() == "true"})
    return rows

def ratio_ci(pool):
    el = [r for r in pool if r["gross_throughput_kwh"] is not None and r["distance_km"] is not None and r["distance_km"] > 0]
    if not el: return None
    days = defaultdict(lambda: [0.0, 0.0])
    for r in el:
        days[r["date"]][0] += r["gross_throughput_kwh"]; days[r["date"]][1] += r["distance_km"]
    num = np.array([v[0] for v in days.values()]); den = np.array([v[1] for v in days.values()])
    point = 100.0 * num.sum() / den.sum()
    G = len(days)
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, G, size=(B, G))
    bs = 100.0 * num[idx].sum(1) / den[idx].sum(1)
    lo, hi = np.quantile(bs, [ALPHA / 2, 1 - ALPHA / 2])
    ess = float(den.sum() ** 2 / (den ** 2).sum())
    mean_of_ratios = float(np.mean([100.0 * r["gross_throughput_kwh"] / r["distance_km"] for r in el]))
    return {"n": len(el), "km": round(float(den.sum()), 3), "point": point, "lo": float(lo), "hi": float(hi), "clusters": G, "ess": ess, "mor": mean_of_ratios}

def clean(pool):
    """M295 (audit 2026-09-24 P0): canonical-clean eligibility — drop ens_invalid / ens_outlier_v2 drives."""
    return [r for r in pool if not r.get("excluded")]

def _pack(c):
    return {"value": c["point"], "n": c["n"], "pairedKm": c.get("km"),
            "ci95": {"lo": c["lo"], "hi": c["hi"], "nClusters": c["clusters"], "essDays": round(c["ess"], 2)}}

def refresh(arr):
    rows = load()
    ch = arr["seasonalCharts"]["charts"]
    ei = ch["EnergyIntensity"]; ce = ch["CohortExposure"]
    cov, data, status = {}, {}, {}
    for key, pred in COH:
        pool = [r for r in rows if pred(r)]
        if not pool:
            cov[key] = {"n_drives": 0, "status": "no_observations"}; data[key] = None; status[key] = "unavailable"; continue
        cov[key] = sc.cohort_coverage(pool); status[key] = "computed"
        c = ratio_ci(clean(pool))
        pub = ratio_ci(pool)
        data[key] = {"eligibility": "canonical_clean (ens_invalid / ens_outlier_v2 excluded)",
                     "pairedKm": c.get("km"),
                     "publishedBasisSensitivity": dict(_pack(pub), basis="all paired-eligible drives incl. canonically invalid",
                                                       nExcludedByCleanRule=pub["n"] - c["n"],
                                                       deltaVsClean=round(pub["point"] - c["point"], 4)),"value": c["point"], "unit": "kWh/100km", "estimator": "ratio_of_sums_paired_eligible",
                     "driveWeightedMeanOfIntensities": c["mor"], "n": c["n"],
                     "ci95": {"lo": c["lo"], "hi": c["hi"], "method": "percentile bootstrap, cluster = calendar day",
                              "B": B, "seed": SEED, "nClusters": c["clusters"], "essDays": round(c["ess"], 2)}}
    ei["statisticalUnit"] = ("ratio_of_sums (paired-eligible, canonical-clean): 100*sum(gross_throughput_kwh)/sum(distance_km) over drives "
                             "with both present, km>0, and not ens_invalid/ens_outlier_v2; the unfiltered published basis is carried as "
                             "publishedBasisSensitivity per cohort (M295)")
    ei["data"], ei["coverage"], ei["status"] = data, cov, status
    ei["intervalNote"] = ("95% interval: percentile bootstrap with calendar day as the resampling cluster (B=%d, fixed seed); "
                          "essDays = Kish effective number of independent days. Conditional on the observed season; not a "
                          "population interval for the regime.").replace("%d", str(B))
    ce["data"] = {k: (v if v.get("status") != "no_observations" else None) for k, v in cov.items()}
    ce["status"] = status
    st = arr["seasonalCharts"]["_staleness"]
    st["refreshedCharts"] = {"keys": ["EnergyIntensity", "CohortExposure"], "milestone": "M295",
                             "basisNDrives": len(rows),
                             "note": f"Recomputed from the current {len(rows)}-drive corpus (canonical-clean paired-eligible ratio-of-sums + day-cluster bootstrap CI; M295). All other seasonalCharts keys remain carried forward at the basis stated above."}
    return arr

if __name__ == "__main__":
    p = os.path.join(WORK, "summary_arrays.json")
    arr = json.load(open(p, encoding="utf-8"))
    arr = refresh(arr)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(arr, f, ensure_ascii=False, indent=1)
    ei = arr["seasonalCharts"]["charts"]["EnergyIntensity"]["data"]
    for k, v in ei.items():
        print(k, None if not v else (round(v["value"], 3), round(v["ci95"]["lo"], 3), round(v["ci95"]["hi"], 3), v["n"], v["ci95"]["nClusters"], v["ci95"]["essDays"]))
