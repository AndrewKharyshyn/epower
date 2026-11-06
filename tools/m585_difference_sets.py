#!/usr/bin/env python3
"""M585 (spec analyses/M585_spec.md Rev 1): per-consumer difference sets between the OLD inline rule (period < 1.05 s fast) and the central regime reader (1.10 s, guard zone), BEFORE any consumer stage is re-run.
Analysis only; writes analyses/M585_difference_sets.json. Usage: python tools/m585_difference_sets.py"""
import hashlib, json, os, pickle, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import regime_reader as RR

OLD = 1.05


def old_regime(v):
    return None if pd.isna(v) else ("fast" if v < OLD else "slow")


def main():
    os.chdir(ROOT)
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    per = dm["I_sample_period_s"]
    new = per.map(RR.regime_of)
    old = per.map(old_regime)
    diff = dm.loc[old.fillna("none") != new.fillna("none"), "file"].tolist()
    out = {"masterMd5": md5, "nDrives": int(len(dm)), "nMissingPeriod": int(per.isna().sum()),
           "periodBased": {"consumers": ["dependence_sensitivity", "m480_spread_sensitivity", "m480b_pair_outcomes", "m573_cell_spread_step", "timing_support (drive classification)"],
                           "driveDifferenceSet": diff, "periodsOfDifferenceSet": {f: float(per[dm["file"] == f].iloc[0]) for f in diff}, "nInGuardZone": int(((per >= RR.GUARD_ZONE[0]) & (per < RR.GUARD_ZONE[1])).sum())}}
    # missing-period behaviour of each consumer (old = new by construction; checked on the drives without a period)
    miss = dm.loc[per.isna(), "file"].tolist()
    out["missingPeriodDrives"] = miss
    out["m573_slow_missing_old_new"] = {"old": float(np.nan >= OLD), "new": RR.slow_flag(np.nan, missing=0.0)}
    out["timing_support_missing_label"] = "unknown (unchanged)"
    # capacity_basis: diagnostic from the logged intervals (cached records of the OLD code), vs the sidecar rule of record
    mv = 4
    try:
        import capacity_basis as C
        mv = C.METHOD_VERSION
    except Exception:
        pass
    rows = []
    for f, p in zip(dm["file"], per):
        cp = os.path.join("capacity_cache", "%s.v%d.pkl" % (f, mv))
        if not os.path.exists(cp):
            rows.append((f, None, p)); continue
        rec = pickle.load(open(cp, "rb"))["rec"]
        rows.append((f, None if rec is None else bool(rec["fast"]), p))
    cap = pd.DataFrame(rows, columns=["file", "diagFastOld", "period"])
    ok = cap.dropna(subset=["diagFastOld", "period"])
    out["capacity_basis"] = {"nRecords": int(cap["diagFastOld"].notna().sum()), "nWithoutRecord": int(cap["diagFastOld"].isna().sum()),
                             "diagOldVsSidecarOldDisagree": ok.loc[ok["diagFastOld"] != (ok["period"] < OLD), "file"].tolist(),
                             "diagOldVsSidecarNewDisagree": ok.loc[ok["diagFastOld"] != (ok["period"] < RR.THRESHOLD_S), "file"].tolist(),
                             "note": "the diagnostic (median of the logged HV-current intervals) is recomputed with the new rule by the capacity_basis stage; the sidecar is the rule of record"}
    # timing_support: window-median crossing flags, old cut vs new cut (from the sidecar columns)
    ts = pd.read_csv("timing_support.csv")
    pre_cols = [c for c in ts.columns if c.endswith("_win_dt_min")]
    flips, in_guard = {}, 0
    for c in pre_cols:
        pref = c[:-len("_win_dt_min")]
        mn, mx = ts[pref + "_win_dt_min"], ts[pref + "_win_dt_max"]
        cr_old = (mn < OLD) & (OLD <= mx)
        cr_new = (mn < RR.THRESHOLD_S) & (RR.THRESHOLD_S <= mx)
        fl = ts.loc[cr_old != cr_new, "file"].tolist()
        flips[pref] = fl
        in_guard += int(((mn >= RR.GUARD_ZONE[0]) & (mn < RR.GUARD_ZONE[1])).sum() + ((mx >= RR.GUARD_ZONE[0]) & (mx < RR.GUARD_ZONE[1])).sum())
    out["timing_support_crossFlips"] = {"byPrefix": flips, "nDrivesWithAnyFlip": len(sorted({f for v in flips.values() for f in v})), "drivesWithAnyFlip": sorted({f for v in flips.values() for f in v}),
                                        "nWindowMediansInGuardZone": in_guard}
    with open(os.path.join(ROOT, "analyses", "M585_difference_sets.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(json.dumps({"periodBased": out["periodBased"]["driveDifferenceSet"], "guardZone": out["periodBased"]["nInGuardZone"], "missing": len(miss), "capacityDisagreeOld": out["capacity_basis"]["diagOldVsSidecarOldDisagree"],
                      "capacityDisagreeNew": out["capacity_basis"]["diagOldVsSidecarNewDisagree"], "timingFlips": out["timing_support_crossFlips"]["drivesWithAnyFlip"], "timingGuardWindows": in_guard}))


if __name__ == "__main__":
    main()
