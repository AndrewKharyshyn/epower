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


def cohort_meta(sdm):
    out = {}
    for c in ("all", "warm", "shoulder", "cold"):
        d = sdm if c == "all" else sdm[sdm["thermal_regime"] == c]
        if len(d) == 0:
            out[c] = {"n": 0, "km": 0, "dateFrom": None, "dateTo": None, "routeMix": {}}
            sup = int((sdm["thermal_regime"] == f"{c}_insufficient").sum()) if c != "all" else 0
            if sup:                                   # M310 minimum-support rule: disclose, never silently drop
                out[c].update(nObserved=sup, suppressed="below_min_support")
            continue
        mix = (d["drive_type"].fillna("unknown").value_counts(normalize=True) * 100).round().astype(int).to_dict()
        out[c] = {"n": int(len(d)), "km": round(float(d["distance_km"].sum()), 2), "dateFrom": str(d["date"].min()),
                  "dateTo": str(d["date"].max()), "routeMix": mix}
    return out


def main():
    sdm = pd.read_csv(P("seasonal_drive_master.csv"), low_memory=False)
    dm = pd.read_csv(P("drive_master.csv"), usecols=["file"], low_memory=False)
    assert len(sdm) == len(dm), f"seasonal master rows {len(sdm)} != drive_master rows {len(dm)}"
    A = json.load(open(P("summary_arrays.json"), encoding="utf-8"))
    A["cohortMeta"] = cohort_meta(sdm)
    m = A["seasonalCharts"]["_meta"]
    vc = sdm["thermal_regime"].value_counts()
    sup = {c: int(vc.get(f"{c}_insufficient", 0)) for c in ("warm", "shoulder", "cold") if vc.get(f"{c}_insufficient", 0)}
    known = ["warm", "shoulder", "cold"] + [f"{c}_insufficient" for c in ("warm", "shoulder", "cold")]
    m["cohortCounts"] = {"all": int(len(sdm)), "warm": int(vc.get("warm", 0)), "shoulder": int(vc.get("shoulder", 0)),
                         "cold": int(vc.get("cold", 0)), "unclassified": int(len(sdm) - vc.reindex(known).fillna(0).sum())}
    m["cohortSuppressedBelowMinSupport"] = {"minDrivesForStatistics": 10, "nObserved": sup}   # M310: observed but not analysed as a cohort
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
