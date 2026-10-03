#!/usr/bin/env python3
"""Refresh the cohort-count blocks that no other stage regenerates (M310): summary_arrays.json -> cohortMeta and
seasonalCharts._meta.{cohortCounts,corpusMd5,seasonalMasterMd5,generatedAt}, seasonalCharts._staleness.liveNDrives.
Sources: drive_master.csv (MD5) and seasonal_drive_master.csv (thermal_regime, drive_type, distance_km, date).
cohortMeta per cohort = {n, km (2 dp), dateFrom, dateTo, routeMix = % of drives by drive_type (rounded, missing -> 'unknown')}.
Validated 2026-09-30: applied to the 446-drive master/seasonal master it reproduces the published 446 cohortMeta byte-for-byte
(all / warm / shoulder); the cold cohort is the empty block. Run after compute_seasonal.py, BEFORE refresh_gtr_headline.py
(which reads seasonalCharts._meta.cohortCounts). Idempotent; touches only the keys above. Stamps are handled by tools/restamp_blocks.py."""
import datetime, hashlib, json, os
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
P = lambda f: os.path.join(ROOT, f)
md5 = lambda f: hashlib.md5(open(P(f), "rb").read()).hexdigest()


def cohort_meta(sdm, min_n):
    """M354 (F08.r1): per cohort, besides n/km/dates/routeMix (unchanged): observed (drives whose physical class is this regime, from
    thermal_regime_raw, incl. below-support), eligibleForCohortView (observed drives analysed as a cohort = n; cohort membership before any
    per-metric clean filtering, which is a different eligibility), inferenceAvailable (eligibleForCohortView >= minDrivesForStatistics, the
    M310 count rule, unchanged) and nDaysObserved (distinct calendar dates among the observed drives, 'all' included)."""
    out = {}
    raw = sdm["thermal_regime_raw"].astype(str)
    for c in ("all", "warm", "shoulder", "cold"):
        d = sdm if c == "all" else sdm[sdm["thermal_regime"] == c]
        ob = sdm if c == "all" else sdm[raw == c]
        extra = {"observed": int(len(ob)), "eligibleForCohortView": int(len(d)), "inferenceAvailable": bool(len(d) >= min_n),
                 "nDaysObserved": int(ob["date"].nunique())}
        if len(d) == 0:
            out[c] = {"n": 0, "km": 0, "dateFrom": None, "dateTo": None, "routeMix": {}}
            sup = int((sdm["thermal_regime"] == f"{c}_insufficient").sum()) if c != "all" else 0
            if sup:                                   # M310 minimum-support rule: disclose, never silently drop
                out[c].update(nObserved=sup, suppressed="below_min_support")
            out[c].update(extra)
            continue
        mix = (d["drive_type"].fillna("unknown").value_counts(normalize=True) * 100).round().astype(int).to_dict()
        out[c] = {"n": int(len(d)), "km": round(float(d["distance_km"].sum()), 2), "dateFrom": str(d["date"].min()),
                  "dateTo": str(d["date"].max()), "routeMix": mix, **extra}
    return out


def main():
    sdm = pd.read_csv(P("seasonal_drive_master.csv"), low_memory=False)
    dm = pd.read_csv(P("drive_master.csv"), usecols=["file"], low_memory=False)
    assert len(sdm) == len(dm), f"seasonal master rows {len(sdm)} != drive_master rows {len(dm)}"
    A = json.load(open(P("summary_arrays.json"), encoding="utf-8"))
    cfg_min = int(json.load(open(P("seasonal_config.json"), encoding="utf-8"))["cohorts"]["minDrivesForStatistics"])
    jsx_min = int(__import__("re").search(r"COHORT_MIN_SUPPORT_DRIVES\s*=\s*(\d+)", open(P("xtrail_summary.jsx"), encoding="utf-8").read()).group(1))
    assert cfg_min == jsx_min == A["ambientTable"]["cohortMinDrives"], (cfg_min, jsx_min, A["ambientTable"]["cohortMinDrives"])
    A["cohortMeta"] = cohort_meta(sdm, cfg_min)
    _cm = A["cohortMeta"]
    _unc = int(len(sdm) - sdm["thermal_regime_raw"].astype(str).isin(["warm", "shoulder", "cold"]).sum())
    assert sum(_cm[c]["observed"] for c in ("warm", "shoulder", "cold")) + _unc == _cm["all"]["observed"] == len(sdm) == len(dm), "observed counts do not conserve"
    for _c in ("warm", "shoulder", "cold"):
        assert _cm[_c]["observed"] == _cm[_c]["eligibleForCohortView"] + _cm[_c].get("nObserved", 0), (_c, _cm[_c])
    m = A["seasonalCharts"]["_meta"]
    vc = sdm["thermal_regime"].value_counts()
    sup = {c: int(vc.get(f"{c}_insufficient", 0)) for c in ("warm", "shoulder", "cold") if vc.get(f"{c}_insufficient", 0)}
    known = ["warm", "shoulder", "cold"] + [f"{c}_insufficient" for c in ("warm", "shoulder", "cold")]
    m["cohortCounts"] = {"all": int(len(sdm)), "warm": int(vc.get("warm", 0)), "shoulder": int(vc.get("shoulder", 0)),
                         "cold": int(vc.get("cold", 0)), "unclassified": int(len(sdm) - vc.reindex(known).fillna(0).sum())}
    m["cohortSuppressedBelowMinSupport"] = {"minDrivesForStatistics": cfg_min, "nObserved": sup}   # M310: observed but not analysed as a cohort
    m["corpusMd5"] = md5("drive_master.csv")
    m["seasonalMasterMd5"] = md5("seasonal_drive_master.csv")
    m["generatedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    st = A["seasonalCharts"].get("_staleness")
    if isinstance(st, dict):
        st["liveNDrives"] = int(len(sdm))
    with open(P("summary_arrays.json"), "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(A, ensure_ascii=False, indent=1))
    print(json.dumps({"cohortCounts": m["cohortCounts"], "cohortMeta_all": A["cohortMeta"]["all"]}))


if __name__ == "__main__":
    main()
