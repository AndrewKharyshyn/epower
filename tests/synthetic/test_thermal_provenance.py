"""M606 known-answer tests (analyses/M606_spec.md Rev 1 sections 0 and 5) for tools/thermal_provenance.py. Written before the tool."""
import os, sys
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import thermal_provenance as N


def close(a, b, tol=1e-9):
    assert abs(a - b) < tol, (a, b)


# 1. window edges inclusive, NaN invalid, out-of-window and the -100 sentinel counted separately
v = np.array([-40.0, 90.0, -40.1, 90.1, np.nan, -100.0, 20.0])
ok, nout, nsent = N.classify_values(v, -40.0, 90.0)
assert list(ok) == [True, True, False, False, False, False, True], ok
assert nout == 3 and nsent == 1, (nout, nsent)          # -40.1, 90.1, -100 are finite and outside; NaN is neither

# 2. coverage on time (10 s bins, nb = floor(span/10) + 1) and gaps including the edges
st = N.channel_stats(np.array([0.0, 15.0, 95.0]), 100.0)
assert st["nValid"] == 3 and st["bins"] == 11 and st["binsCovered"] == 3, st
close(st["coverageShare"], 3 / 11)
assert st["leadGapS"] == 0.0 and st["trailGapS"] == 5.0 and st["longestGapS"] == 80.0, st
st = N.channel_stats(np.array([30.0, 40.0]), 100.0)
assert st["leadGapS"] == 30.0 and st["trailGapS"] == 60.0 and st["longestGapS"] == 60.0, st
close(st["medianIntervalS"], 10.0)

# 3. a channel that stops mid-drive is caught by the trail gap; exactly 60 s is not gappy, 60.1 s is
dense = np.arange(0.0, 61.0, 1.0)
a = N.channel_stats(dense, 120.0)                         # valid 0..60 s, span 120 s: trail gap exactly 60
b = N.channel_stats(dense, 120.1)                         # trail gap 60.1
assert a["coverageShare"] >= 0.5 and b["coverageShare"] >= 0.5
assert N.flag(a, True) == "ok" and N.flag(b, True) == "gappy", (N.flag(a, True), N.flag(b, True))

# 4. flag order: absent, empty, partial (coverage < 0.5, takes precedence over gappy), gappy, ok
assert N.flag(N.channel_stats(np.array([]), 50.0), False) == "absent"
e = N.channel_stats(np.array([]), 50.0)
assert N.flag(e, True) == "empty" and e["nValid"] == 0 and e["longestGapS"] is None and e["coverageShare"] == 0.0
p = N.channel_stats(np.array([0.0, 5.0]), 200.0)
assert N.flag(p, True) == "partial", p
assert N.flag(N.channel_stats(np.arange(0.0, 100.0, 2.0), 100.0), True) == "ok"
# sensitivity thresholds are arguments
assert N.flag(N.channel_stats(np.arange(0.0, 100.0, 2.0), 100.0), True, cov_min=0.99) in ("ok", "partial")

# 5. duplicate timestamps collapse (first kept) before counting
d = N.channel_stats(np.array([5.0, 5.0, 5.0, 20.0]), 30.0)
assert d["nValid"] == 2, d

# 6. epoch in drive order (date, time_start), same-day outage starting mid-day
rows = [("2026-08-24", "13:00:00", False), ("2026-08-24", "08:00:00", True), ("2026-08-24", "09:00:00", True), ("2026-08-23", "20:00:00", True), ("2026-08-25", "07:00:00", False)]
ep = N.epoch(rows)
assert ep["lastValidDate"] == "2026-08-24" and ep["nValid"] == 3 and ep["nAfterLastValid"] == 2 and ep["firstValidDate"] == "2026-08-23", ep
assert N.epoch([("2026-01-01", "01:00:00", False)])["lastValidDate"] is None

# 7. manual-ledger reading kinds
assert [N.ledger_kind(n) for n in (1, 2, 3, 5)] == ["single", "pair", "trapezoid", "trapezoid"]

# 8. month x stratum matrix: totals over cells equal totals over drives; strata never merged
recs = [dict(month="2026-08", stratum="fast", flags={"intake": "ok"}), dict(month="2026-08", stratum="slow", flags={"intake": "empty"}),
        dict(month="2026-09", stratum="slow", flags={"intake": "empty"}), dict(month="2026-09", stratum="slow", flags={"intake": "ok"})]
m = N.matrix(recs, "intake")
assert sum(c["nDrives"] for c in m.values()) == len(recs)
assert m[("2026-09", "slow")]["flags"] == {"empty": 1, "ok": 1} and ("2026-08", "fast") in m and ("2026-08", "slow") in m

# 9. per-drive record on a sparse-wide CSV crossing midnight: one PID per row, duplicate timestamp, sentinel, out-of-window
H = "time,[BMS] HV Battery Intake Air Temperature (℃),[VCM] HV Coolant Temperature (℃),Температура охолодної рідини (℃),Температура повітря, що всмоктується (℃)"
lines = [H.replace("Температура повітря, що всмоктується (℃)", '"Температура повітря, що всмоктується (℃)"'),
         "23:59:50.000,20.0,,,", "23:59:55.000,,60.0,,", "00:00:00.000,,,85.0,", "00:00:00.000,,,85.0,", "00:00:05.000,-100,,,", "00:00:10.000,,,,150.5", "00:00:20.000,95.0,,,"]
rec = N.drive_record(("\n".join(lines) + "\n").encode("utf-8"))
assert rec["ok"] and abs(rec["spanS"] - 30.0) < 1e-9, rec
ia, hv, ec, ei = rec["channels"]["intake"], rec["channels"]["hvCoolant"], rec["channels"]["engineCoolant"], rec["channels"]["engineIntake"]
assert ia["nValid"] == 1 and ia["nOutOfWindow"] == 2 and ia["nSentinel100"] == 1 and ia["columnPresent"], ia      # 20.0 valid; -100 and 95.0 outside [-40, 90]
assert hv["nValid"] == 1 and ec["nValid"] == 1 and ec["nValid"] == 1, (hv, ec)                                 # the duplicate 85.0 row collapses
assert ei["nValid"] == 0 and ei["nOutOfWindow"] == 1, ei                                                       # 150.5 outside the engine-intake window
close(ec["leadGapS"], 10.0); close(ec["trailGapS"], 20.0)                                                      # valid at 10 s (00:00:00) of a 30 s span

# 9b. a missing column is "absent", not "empty"
rec2 = N.drive_record(b"time,[VCM] HV Coolant Temperature (\xe2\x84\x83)\n10:00:00.000,50.0\n10:00:10.000,51.0\n")
assert rec2["channels"]["intake"]["columnPresent"] is False and rec2["flags"]["intake"] == "absent"

# 10. population: e4ORCE_* and comparison files are never matched to a master row
rm = N.build_rawmap(["2026-09-22 11-55-57.csv", "e4ORCE_20260807_073756.csv", "2026-07-30 22-06-51_B_D_comparison.csv"])
assert list(rm.values()) == [["2026-09-22 11-55-57.csv"]], rm

# 11. no untracked input; cache key deterministic
assert "ambient_samples.json" not in N.INPUTS and all(os.path.exists(os.path.join(ROOT, f)) for f in N.INPUTS), N.INPUTS
assert N._src_hash() == N._src_hash()
print("ok test_thermal_provenance")
