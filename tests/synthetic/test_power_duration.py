"""M552 (analyses/M552_spec.md Rev 2): known-answer tests for the exact window-extremum kernel tools/power_duration.py."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import power_duration as PD

near = lambda a, b, tol=1e-9: abs(a - b) <= tol

# KA1: constant power P0 -> every window value is P0 (exact = grid = shift) for every W that fits
t = np.arange(0, 301, 1.0); p = np.full(len(t), 12.5)
for W in PD.WINDOWS:
    r = PD.window_extremes(t, p, W)
    assert near(r["max"], 12.5) and near(r["min"], 12.5) and near(r["gridMax"], 12.5) and near(r["shiftMax"], 12.5), (W, r)

# KA2: ramp 0 -> 20 kW over 10 s, then back to 0 over 10 s (triangle, peak 20 kW at t = 10 s); W = 5: the best window is centred on the peak
t = np.array([0.0, 10.0, 20.0]); p = np.array([0.0, 20.0, 0.0])
r = PD.window_extremes(t, p, 5)
# mean over [7.5, 12.5] of the triangle: 20 - (2.5 * 2) / 2 * ... computed analytically: power(7.5) = 15, power(12.5) = 15, area = 2.5 * (15 + 20) / 2 * 2 = 87.5 kW s -> 17.5 kW
assert near(r["max"], 17.5) and near(r["sMax"], 7.5), r
assert near(r["gridMax"], 17.4) and near(r["shiftMax"], 17.5)             # the integer grid misses the optimum by the analytic 0.1 kW, the 0.5 s shifted grid hits it
# the minimum over s in [0, 15] of the window mean is at the ends: mean over [0, 5] = 5 kW
r2 = PD.window_extremes(t, p, 5)
assert near(r2["min"], 5.0), r2["min"]

# KA2b: an asymmetric peak whose optimum is an interior vertex off every knot and off both grids (a breakpoint-only implementation must fail)
t = np.array([0.0, 4.0, 4.6, 9.0, 13.0]); p = np.array([0.0, 2.0, 30.0, 4.0, 0.0])
W = 5
r = PD.window_extremes(t, p, W)
fine = np.arange(0, 8.0 + 1e-9, 1e-4)
k = PD._prep(t, p)
brute = ((PD._E(fine + W, k) - PD._E(fine, k)) / W)
assert near(r["max"], brute.max(), 1e-6), (r["max"], brute.max())
assert abs(r["sMax"] - fine[brute.argmax()]) < 1e-3
bp = np.unique(np.concatenate([t, t - W, [0.0, 8.0]])); bp = bp[(bp >= 0) & (bp <= 8)]
bp_best = ((PD._E(bp + W, k) - PD._E(bp, k)) / W).max()
assert r["max"] > bp_best + 1e-6, (r["max"], bp_best)             # the interior vertex beats every breakpoint
assert r["max"] > r["gridMax"] + 1e-6 and r["max"] > r["shiftMax"] + 1e-6   # and both 1 s grids

# KA3: a gapped drive: windows never span a 6 s gap; a window ending exactly at the gap edge is counted; a short segment gives no window for a long W
ts = np.concatenate([np.arange(0, 11, 1.0), np.arange(17, 22, 1.0)])      # segment A: 0..10 s, gap 7 s (> 5 s), segment B: 17..21 s
P = np.where(ts < 11, 10.0, 50.0)
segs = PD.segments(ts, P)
assert len(segs) == 2 and near(segs[0][0][-1], 10.0) and near(segs[1][0][-1], 4.0)
rec = PD.drive_record(ts, P)
assert near(rec["byW"]["10"]["dis"], 10.0) and rec["byW"]["10"]["nSegEligible"] == 1          # W = 10 fits segment A exactly (window ends at the gap edge) and not B
assert rec["byW"]["5"]["dis"] == 50.0 and rec["byW"]["5"]["nSegEligible"] == 1 or near(rec["byW"]["5"]["dis"], 50.0) is False   # B (4 s) is shorter than 5 s: 5 s windows exist only in A
assert near(rec["byW"]["5"]["dis"], 10.0)
assert rec["byW"]["30"]["nSegEligible"] == 0 and rec["byW"]["30"]["dis"] == 0.0

# KA7: a duplicate timestamp with a power jump keeps E continuous and the result does not depend on the order of the duplicate rows' time (E has no jump)
t = np.array([0.0, 5.0, 5.0, 10.0]); p = np.array([10.0, 10.0, 30.0, 30.0])
k = PD._prep(t, p)
assert near(PD._E(5.0, k), 50.0) and near(PD._E(np.nextafter(5.0, 6.0), k), 50.0, 1e-6)
r = PD.window_extremes(t, p, 5)
assert near(r["max"], 30.0) and np.isfinite(r["min"])
# the same shape without the duplicate gives the same extremes
r_nd = PD.window_extremes(np.array([0.0, 5.0, 10.0]), np.array([10.0, 30.0, 30.0]), 5)
assert near(r_nd["max"], 30.0)

# R5: charge extreme = max(0, -min): a drive whose window means are all positive reports 0 charge, never |min|
rec = PD.drive_record(np.arange(0, 60, 1.0), np.full(60, 8.0))
assert rec["byW"]["5"]["chg"] == 0.0 and near(rec["byW"]["5"]["dis"], 8.0)
rec = PD.drive_record(np.arange(0, 60, 1.0), np.full(60, -6.0))
assert rec["byW"]["5"]["dis"] == 0.0 and near(rec["byW"]["5"]["chg"], 6.0)

# KA6 (integer multiples only): random power series: the exact extremes are non-increasing in W over segments eligible for both
rng = np.random.default_rng(3)
for _ in range(20):
    n = int(rng.integers(300, 900)); ts = np.cumsum(rng.choice([0.0, 0.5, 1.0, 2.0], size=n, p=[0.05, 0.3, 0.5, 0.15])); P = rng.normal(0, 25, n)
    assert PD.drive_record(ts, P)["ka6Violations"] == 0
# ... and the claim is false for non-multiples (documented): P = 1, 0, 1 on 1 s pieces, W = 2 gives 0.5, W = 3 gives 2/3
t = np.array([0.0, 1.0, 2.0, 3.0]); p = np.array([1.0, 1.0, 0.0, 0.0])
# (illustrative shape check: window means of a piecewise series need not be monotone in W unless W2 is a multiple of W1)
a = PD.window_extremes(np.array([0.0, 1.0, 1.0, 2.0, 2.0, 3.0]), np.array([1.0, 1.0, 0.0, 0.0, 1.0, 1.0]), 2)["max"]
b = PD.window_extremes(np.array([0.0, 1.0, 1.0, 2.0, 2.0, 3.0]), np.array([1.0, 1.0, 0.0, 0.0, 1.0, 1.0]), 3)["max"]
assert b > a - 1e-12

# closure: the integral of the power over a segment equals the ledger formula on a signed series (no crossing issue: E is the trapezoid integral)
ts = np.arange(0, 100, 1.0); P = np.sin(ts / 7.0) * 20
rec = PD.drive_record(ts, P)
assert near(rec["closureKwhSegments"], float(np.sum((P[:-1] + P[1:]) / 2.0 * np.diff(ts)) / 3600.0), 1e-12)

# pct bootstrap rules: no interval for fewer than 5 days, none for p99 under 20 days, none when n*(1-q) < 5
vals = list(np.linspace(1, 10, 30)); days = [f"d{i % 6}" for i in range(30)]
assert PD._pct_boot(vals, days, 95)["ci95"] is None            # 30 * 0.05 = 1.5 < 5
assert PD._pct_boot(vals, days, 50)["ci95"] is not None
assert PD._pct_boot(vals, days, 99)["ci95"] is None

# stored block (after the splice): strata only, no pooled headline key
import json
a = json.load(open("summary_arrays.json", encoding="utf-8"))
B = a["powerDuration"]
assert set(B["strata"]) <= {"fast", "slow", "unknown"} and "pooled" not in B and B["knownAnswer"]["misses"] == {"ka4": 0, "ka5": 0, "ka6": 0}
print("test_power_duration OK")
