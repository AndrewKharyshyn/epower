#!/usr/bin/env python3
"""M401 (audit D4, analyses/M401_spec.md): odometer continuity check on drive_master.csv with a ledger of recorded anomalies (odometer_anomalies.json).
Fixed rules (not tuned), drives ordered by (date, time_start):
  R1  odo_end < odo_start - 0.05 km                         the odometer decreases inside a drive
  R2  odo_start < previous odo_end - 0.5 km                 backward step between drives (stale repeated reading, reset)
  R3  odo_start < 0.5 x running maximum of earlier odo_end  reset regime (odometer restarted)
  R4  odo_start - previous odo_end > 500 km                 forward jump (typically the first drive after a reset regime)
A positive gap between drives of a few tens of km is unlogged driving, not an anomaly. The master is never edited: anomalies are RECORDED in the ledger with a reason, and the release gate
fails on an unrecorded one (or on recorded rules that differ). Stale ledger entries are reported. The Overview KPI (total logged km / dash ODO, owner rule 2026-10-03) is unaffected.
Usage: python tools/odometer_check.py [--draft]"""
import json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TOL_WITHIN, TOL_BACK, RESET_FRAC, JUMP_KM = 0.05, 0.5, 0.5, 500.0


def continuity_anomalies(dm):
    d = dm.sort_values(["date", "time_start"], kind="stable").reset_index(drop=True)
    out, prev_end, run_max = [], None, None
    for _, r in d.iterrows():
        a, b = float(r["odo_start"]), float(r["odo_end"])
        rules = []
        if b < a - TOL_WITHIN:
            rules.append("R1")
        if prev_end is not None and a < prev_end - TOL_BACK:
            rules.append("R2")
        if run_max is not None and a < RESET_FRAC * run_max:
            rules.append("R3")
        if prev_end is not None and a - prev_end > JUMP_KM:
            rules.append("R4")
        if rules:
            out.append({"file": str(r["file"]), "date": str(r["date"]), "odo_start": a, "odo_end": b, "prev_odo_end": prev_end, "rules": rules})
        prev_end = b
        run_max = b if run_max is None else max(run_max, b)
    return out


def check(dm, ledger):
    found = {x["file"]: x for x in continuity_anomalies(dm)}
    rec = {e["file"]: e for e in ledger.get("anomalies", [])}
    unrecorded = sorted(set(found) - set(rec))
    differ = sorted(f for f in set(found) & set(rec) if sorted(found[f]["rules"]) != sorted(rec[f]["rules"]))
    stale = sorted(set(rec) - set(found))
    if unrecorded:
        return False, "unrecorded odometer anomalies: %s" % unrecorded
    if differ:
        return False, "recorded rules differ from the detected rules for: %s" % differ
    return True, "%d odometer anomalies, all recorded%s" % (len(found), ("; stale ledger entries: %s" % stale) if stale else "")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
    if "--draft" in argv:
        print(json.dumps({"anomalies": continuity_anomalies(dm)}, indent=1))
        return 0
    ledger = json.load(open(os.path.join(ROOT, "odometer_anomalies.json"), encoding="utf-8"))
    ok, msg = check(dm, ledger)
    print(("PASS " if ok else "FAIL ") + "odometer continuity: " + msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
