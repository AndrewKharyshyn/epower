#!/usr/bin/env python3
"""cohort_distributions.py (M284, Section 9: ECDF small multiples). Adds top-level `cohortDistributions` to
summary_arrays.json: per-drive values per cohort for four drive-level metrics, so Compare can draw ECDFs (fuller
shape than a box). Values are read from drive_master.csv + seasonal_drive_master.csv (cohort labels); nothing is
smoothed. Idempotent; replaces the key and its stamp."""
import csv, json, os, copy
import numpy as np
_HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get("XT_WORK") or (_HERE if os.path.exists(os.path.join(_HERE, "drive_master.csv")) else os.path.dirname(_HERE))
SDIR = os.path.join(WORK, "seasonal") if os.path.isdir(os.path.join(WORK, "seasonal")) else WORK
MIN_KM_INTENSITY = 1.0
METRICS = [("kwh100", "Energy intensity (per drive)", "kWh/100 km"), ("engine_on_pct", "Engine-on share", "% of time"),
           ("ev_dist_pct", "EV distance share", "% of distance"), ("regen_share_of_charge", "Regen share of charge", "%")]

def _f(x):
    try: return float(x) if x not in (None, "", "None") else None
    except ValueError: return None

def ks_d(a, b):
    a = np.sort(a); b = np.sort(b); z = np.concatenate([a, b])
    return float(np.max(np.abs(np.searchsorted(a, z, side="right") / len(a) - np.searchsorted(b, z, side="right") / len(b))))

def build():
    dm = {r["file"]: r for r in csv.DictReader(open(os.path.join(WORK, "drive_master.csv"), newline=""))}
    reg = {r["file"]: r["thermal_regime"] for r in csv.DictReader(open(os.path.join(SDIR, "seasonal_drive_master.csv"), newline=""))}
    rows = []
    for f, c in reg.items():
        m = dm[f]; km = _f(m.get("distance_km")); gt = _f(m.get("gross_throughput_kwh"))
        rows.append({"c": c, "kwh100": (100 * gt / km) if (gt is not None and km is not None and km >= MIN_KM_INTENSITY) else None,
                     "engine_on_pct": _f(m.get("engine_on_pct")), "ev_dist_pct": _f(m.get("ev_dist_pct")),
                     "regen_share_of_charge": _f(m.get("regen_share_of_charge"))})
    out = {"_meta": {"basisNDrives": len(rows), "note": ("Per-drive empirical distributions by thermal cohort (ECDF small multiples). Drive-weighted, unsmoothed. "
           "Energy intensity uses drives ≥ %.0f km (sub-1 km logs are noise-floor artefacts). KS D is a descriptive max ECDF gap only: "
           "drives within a day are not independent and cohorts differ in route mix, so no p-value is given." % MIN_KM_INTENSITY)}, "metrics": {}}
    for key, label, unit in METRICS:
        co = {}
        for name, pred in (("all", lambda c: True), ("warm", lambda c: c == "warm"), ("shoulder", lambda c: c == "shoulder"), ("cold", lambda c: c == "cold")):
            v = sorted(round(r[key], 3) for r in rows if pred(r["c"]) and r[key] is not None)
            co[name] = v if v else None
        d = ks_d(co["warm"], co["shoulder"]) if co["warm"] and co["shoulder"] else None
        out["metrics"][key] = {"label": label, "unit": unit, "cohorts": co, "ksWarmShoulder": None if d is None else round(d, 3)}
    return out

if __name__ == "__main__":
    p = os.path.join(WORK, "summary_arrays.json"); a = json.load(open(p, encoding="utf-8"))
    a["cohortDistributions"] = build()
    st = copy.deepcopy(a["_artifactStamps"]["records"])
    st["computationStatus"] = "computed"
    st["computationStatusNote"] = "M284: per-drive cohort distributions for ECDF small multiples (cohort_distributions.py); derived from drive_master.csv + seasonal_drive_master.csv."
    a["_artifactStamps"]["cohortDistributions"] = st
    json.dump(a, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for k, m in a["cohortDistributions"]["metrics"].items():
        print(k, {c: (len(v) if v else None) for c, v in m["cohorts"].items()}, "KS", m["ksWarmShoulder"])
