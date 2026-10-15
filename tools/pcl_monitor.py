#!/usr/bin/env python3
"""PCL-1 monitor (spec analyses/PCL1_spec.md sections 3-4): REPORT-ONLY ingestion stage. Counts and compliance of the paired-cadence protocol drives: eligible drives, observed arm (master ev_rpm_dt_med_s < 1.0 fast, otherwise slow), assigned arm from the
schedule, compliance, paired days (at least 2 drives of each observed arm), balance of distance and start hour. NO cell value, difference or interval of the protocol drives is computed here (pre-registered: nothing is looked at before the one-shot analysis).
Slot rule (B6): the trip number of a drive is its start order among ALL files of that calendar day (ineligible ones included). Deterministic state file analyses/pcl1_monitor.json (no timestamps).
Usage: python tools/pcl_monitor.py [--schedule analyses/PCL1_schedule.csv] [--out analyses/pcl1_monitor.json]"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import pcl_schedule as PS

ESCALATE_BELOW = 0.90


def observed_arm(x):
    return "unknown" if not np.isfinite(x) else ("fast" if x < 1.0 else "slow")


def protocol_frame(dm, start, design, table):
    """Drives on or after the START DATE with trip number (start order among all files of the day), assigned and observed arm."""
    d = dm.copy()
    d["date"] = d["date"].astype(str).str[:10]
    d = d.sort_values(["date", "time_start"]).reset_index(drop=True)
    d["trip"] = d.groupby("date").cumcount() + 1
    d = d[d["date"] >= start.isoformat()].copy()
    d["assigned"] = [PS.assigned_arm(design, table, a, t, ts) for a, t, ts in zip(d["date"], d["trip"], d["time_start"])]
    d["observed"] = [observed_arm(x) for x in d["ev_rpm_dt_med_s"]]
    return d


def report(dm, schedule_path):
    if not os.path.exists(schedule_path):
        return {"protocol": "PCL-1", "started": False, "note": "no schedule file: the protocol has not started (the owner chooses the START DATE)"}
    start, seed, design, table, sha = PS.read(schedule_path)
    d = protocol_frame(dm, start, design, table)
    clean = ~d["ens_outlier_v2"].astype(bool) if "ens_outlier_v2" in d else pd.Series(True, index=d.index)
    e = d[clean]
    both = e[e["observed"].isin(["fast", "slow"])]
    per_day = both.groupby(["date", "observed"]).size().unstack(fill_value=0)
    for c in ("fast", "slow"):
        if c not in per_day:
            per_day[c] = 0
    paired = per_day[(per_day["fast"] >= 2) & (per_day["slow"] >= 2)]
    # compliance over ALL files since the start (a missed or split log is non-compliance, B6): files with a known observed arm
    comp = d[d["assigned"].isin(["fast", "slow"]) & d["observed"].isin(["fast", "slow"])]
    out = {"protocol": "PCL-1", "started": True, "startDate": start.isoformat(), "seed": seed, "design": design, "scheduleBodySha256": sha, "nDrivesSinceStart": int(len(d)), "nEligibleClean": int(len(e)),
           "observedArm": {k: int((e["observed"] == k).sum()) for k in ("fast", "slow", "unknown")},
           "compliance": {"nCompared": int(len(comp)), "nCompliant": int((comp["assigned"] == comp["observed"]).sum()),
                          "share": None if not len(comp) else round(float((comp["assigned"] == comp["observed"]).mean()), 4), "directorBeforePassIfBelow": ESCALATE_BELOW},
           "pairedDays": int(len(paired)), "minPairedDays": 60, "stopPairedDays": 100, "hardStop": "2027-09-30",
           "daysWithDrives": int(both["date"].nunique()),
           "balance": {k: {"nDrives": int((both["observed"] == k).sum()), "meanDistanceKm": None if "distance_km" not in both or not (both["observed"] == k).any() else round(float(both.loc[both["observed"] == k, "distance_km"].mean()), 2),
                           "meanStartHour": round(float(both.loc[both["observed"] == k, "time_start"].astype(str).str[:2].astype(int).mean()), 2) if (both["observed"] == k).any() else None} for k in ("fast", "slow")},
           "reading": "counts only; no cell value, difference or interval of the protocol drives is computed before the one-shot analysis (tools/pcl_gate.py)"}
    out["flag"] = ("compliance below %.0f %%: check the app setting before each trip" % (100 * ESCALATE_BELOW)) if (out["compliance"]["share"] is not None and out["compliance"]["nCompared"] >= 8 and out["compliance"]["share"] < ESCALATE_BELOW) else None
    out["readyForAnalysis"] = bool(out["pairedDays"] >= out["minPairedDays"])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--schedule", default=os.path.join(ROOT, "analyses", "PCL1_schedule.csv"))
    ap.add_argument("--out", default=os.path.join(ROOT, "analyses", "pcl1_monitor.json"))
    ap.add_argument("--master", default=os.path.join(ROOT, "drive_master.csv"))
    a = ap.parse_args(argv)
    dm = pd.read_csv(a.master, low_memory=False)
    res = report(dm, a.schedule)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1, sort_keys=True)
    print(json.dumps({k: res[k] for k in ("started", "pairedDays", "flag") if k in res}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
