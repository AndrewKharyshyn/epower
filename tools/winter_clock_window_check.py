#!/usr/bin/env python3
"""M738 (report-only): does the +16 s cloud-to-OBD clock offset of M730 (median 16-17 s, P90 26 s, same before and after the 25 Oct time change) affect the winter scoring-window assumption of M717 (drive start times are logger clock = Europe/Kyiv local time, scoring set = drives that start after F + 1 h, day label = local start date)?
Counts, on the exposure frame, the drives whose classification could change if every start time moved by up to MAX_SHIFT_S seconds either way: (a) the scoring or basis boundary F +- 1 h, (b) the calendar-day label (midnight), and states the time-zone reading (a zone error would be 3600 s, the size of the guard, not 16 s).
Writes analyses/M738_clock_window_check.json. No frozen file, registry or payload is touched. Usage: python tools/winter_clock_window_check.py"""
import json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_exposure_monitor as WM

MAX_SHIFT_S = 60.0                       # >= 2 x the M730 P90 (26 s)
OUT = os.path.join(ROOT, "analyses", "M738_clock_window_check.json")


def main(argv=None):
    fr = pd.read_csv(os.path.join(ROOT, "analyses", "M713", "exposure_drives.csv"), dtype={"key": str}, low_memory=False, usecols=["key", "day", "start"])
    st = pd.to_datetime(fr["start"])
    sec = (st - st.dt.normalize()).dt.total_seconds()
    d = pd.Timedelta(seconds=MAX_SHIFT_S)
    near = lambda t: int(((st - t).abs() <= d).sum())
    m30 = json.load(open(os.path.join(ROOT, "analyses", "M730_clock_offset.json"), encoding="utf-8"))
    res = {"milestone": "M738", "maxShiftTestedSeconds": MAX_SHIFT_S, "nDrives": int(len(fr)), "lastDriveStart": str(st.max()),
           "driveStartsWithinShiftOfScoringBoundary(F+1h)": near(WM.F + WM.GUARD), "driveStartsWithinShiftOfBasisBoundary(F-1h)": near(WM.F - WM.GUARD), "driveStartsWithinShiftOfFreezeTime(F)": near(WM.F),
           "driveStartsWithinShiftOfMidnight": int(((sec < MAX_SHIFT_S) | (sec > 86400 - MAX_SHIFT_S)).sum()),
           "m730": {k: m30.get(k) for k in ("n_drives", "n_days", "pooled_best_offset_s")}, "m730ByDstPeriod": m30.get("by_dst_period"),
           "reading": "the M730 offset is cloud-versus-OBD, not logger-versus-true-time, and it is about 16 s (P90 26 s); the guard around F is 3600 s and the frozen scoring rule uses drive starts, so a 16 s shift cannot move a drive across the boundary unless a start lies within the shift of it (counted above). The offset is the same before and after the 25 Oct time change, so there is no sign of a time-zone handling defect (that would be 3600 s). It only matters for a calendar-day label when a drive starts within the shift of midnight (counted above); re-run at scoring on the scoring frame.",
           "language": "an offset of about 16 s; logger clock assumed Europe/Kyiv local time (not verified against an external time source)"}
    ok = res["driveStartsWithinShiftOfScoringBoundary(F+1h)"] == 0 and res["driveStartsWithinShiftOfBasisBoundary(F-1h)"] == 0 and res["driveStartsWithinShiftOfMidnight"] == 0
    res["noDriveClassificationChangesToday"] = bool(ok)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(res, ensure_ascii=False, indent=1, default=str) + "\n")
    print(json.dumps({k: v for k, v in res.items() if k.startswith(("driveStarts", "noDrive", "nDrives"))}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
