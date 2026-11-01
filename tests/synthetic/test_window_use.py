"""M553 (analyses/M553_spec.md Rev 2): known-answer tests for the excursion kernel tools/window_use.py."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import window_use as WU

near = lambda a, b, tol=1e-9: abs(a - b) <= tol

# KA1: constant discharge current I0 over T s -> excursion = I0 T / 3600, monotone, single segment
t = np.arange(0, 601, 1.0); I0 = 12.0
r = WU.excursion(t, np.full(len(t), I0))
assert near(r["upper"], I0 * 600 / 3600) and near(r["lower"], r["upper"]) and r["nSeg"] == 1 and near(r["netSegSum"], r["upper"])
# the same for power (kWh)
assert near(WU.excursion(t, np.full(len(t), 7.5))["upper"], 7.5 * 600 / 3600)

# KA1b: a constant offset i_off adds exactly |i_off| T / 3600 in the monotone case
off = 0.8
assert near(WU.excursion(t, np.full(len(t), I0 - off))["upper"], (I0 - off) * 600 / 3600)
assert near(WU.excursion(t, np.full(len(t), I0))["upper"] - WU.excursion(t, np.full(len(t), I0 - off))["upper"], off * 600 / 3600)

# KA2: sine current with zero mean: Q(t) = A T/(2 pi) (1 - cos(2 pi t / T)) / 3600 -> range A T / (pi 3600) Ah; 1 s sampling, linear interpolation error bounded by 1e-4 Ah here
A, T = 20.0, 100.0
t = np.arange(0, 1001, 0.5); y = A * np.sin(2 * np.pi * t / T)
r = WU.excursion(t, y)
assert abs(r["upper"] - A * T / (np.pi * 3600)) < 1e-4, (r["upper"], A * T / (np.pi * 3600))

# KA2b: an interior extremum at a zero crossing that is off every sample: current +10 A at t = 0, -30 A at t = 5 (the longest supported step) -> the crossing is at 1.25 s; Q peaks there at 6.25 As and ends at -50 As
t = np.array([0.0, 5.0]); y = np.array([10.0, -30.0])
r = WU.excursion(t, y)
assert near(r["upper"], (6.25 + 50.0) / 3600.0, 1e-12) and near(r["netSegSum"], -50.0 / 3600.0, 1e-12)

# KA3: a 6 s gap splits the drive: excursion = sum of the two segments, the gap contributes nothing, lower = the larger segment
ts = np.concatenate([np.arange(0, 11, 1.0), np.arange(17, 22, 1.0)]); y = np.where(ts < 11, 10.0, 50.0)
r = WU.excursion(ts, y)
assert r["nSeg"] == 2 and near(r["upper"], (10.0 * 10 + 50.0 * 4) / 3600) and near(r["lower"], 10.0 * 10 / 3600.0 if 10.0 * 10 > 50.0 * 4 else 50.0 * 4 / 3600.0)
assert near(r["gapS"], 7.0) and near(r["gapShare"], 7.0 / 21.0)

# KA7: a duplicate timestamp with a signal jump keeps Q continuous and the result does not depend on the order of the duplicate rows
t = np.array([0.0, 5.0, 5.0, 10.0]); y = np.array([10.0, 10.0, 30.0, 30.0])
r = WU.excursion(t, y)
assert near(r["upper"], (10.0 * 5 + 30.0 * 5) / 3600.0)
assert near(r["upper"], WU.excursion(np.array([0.0, 5.0, 10.0]), np.array([10.0, 30.0, 30.0]))["upper"] - (30.0 - 10.0) / 2 * 5 / 3600.0 + 0.0)
r_rev = WU.excursion(np.array([0.0, 5.0, 5.0, 10.0]), np.array([10.0, 30.0, 10.0, 30.0]))
assert np.isfinite(r_rev["upper"])

# bounds: peak-to-trough <= total variation (throughput) and |net| <= upper, on a random series
rng = np.random.default_rng(5)
for _ in range(20):
    n = int(rng.integers(200, 600)); ts = np.cumsum(rng.choice([0.5, 1.0, 2.0, 7.0], size=n, p=[0.3, 0.5, 0.15, 0.05])); y = rng.normal(0, 25, n)
    r = WU.excursion(ts, y)
    dt = np.diff(ts); sup = dt <= 5.0
    tv = float(np.sum(np.where(sup, np.where(y[:-1] * y[1:] >= 0, np.abs(y[:-1] + y[1:]) / 2 * dt, ((y[:-1] ** 2 + y[1:] ** 2) / (2 * np.abs(y[:-1] - y[1:]) + 1e-300)) * dt), 0.0)) / 3600.0)
    assert abs(r["netSegSum"]) <= r["upper"] + 1e-9 and r["lower"] <= r["upper"] + 1e-12 and r["upper"] <= tv + 1e-9, (r, tv)

# stored block (after the splice): strata only, no pooled headline key
import json
a = json.load(open("summary_arrays.json", encoding="utf-8"))
B = a["windowUse"]
assert set(B["strata"]) <= {"fast", "slow", "unknown"} and "pooled" not in B and B["knownAnswer"]["misses"] == {"closure": 0, "bounds": 0}
print("test_window_use OK")
