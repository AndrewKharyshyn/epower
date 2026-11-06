"""M597 known-answer tests (analyses/M597_spec.md Rev 1 section 6) for tools/highway_share.py."""
import os, sys
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import highway_share as H

def close(a, b, tol=1e-9):
    assert abs(a - b) < tol, (a, b)

# 1. audit fixture: 100 s in band, 40 s rotation, 20 s discharge while rotating -> J 20 %, C 50 %, R 40 %
speed = np.full(100, 100.0)
rpm = np.r_[np.full(40, 1500.0), np.zeros(60)]
Id = np.r_[np.full(20, 10.0), np.full(20, -10.0), np.full(60, 5.0)]   # discharge while engine off must not count
B, E, D = H.band_seconds(speed, rpm, Id, np.ones(100))
assert (B, E, D) == (100.0, 40.0, 20.0), (B, E, D)
J, C, R = H.shares(B, E, D)
close(J, 0.2); close(C, 0.5); close(R, 0.4)

# 2. discharge with the engine at or below the threshold does not enter E or D (400 is exclusive)
B, E, D = H.band_seconds([100, 100], [400.0, 401.0], [5, 5], [1, 1])
assert (B, E, D) == (2.0, 1.0, 1.0)

# 3. edges 80 and 120 inclusive; outside excluded; NaN speed excluded
B, E, D = H.band_seconds([79.9, 80, 120, 120.1, np.nan], [1000] * 5, [5] * 5, [1] * 5)
assert (B, E, D) == (2.0, 2.0, 2.0)

# 4. E = 0 -> C undefined; NaN rpm is engine-off; NaN Id is not discharge
B, E, D = H.band_seconds([100, 100], [np.nan, 0], [5, np.nan], [1, 1])
assert (B, E, D) == (2.0, 0.0, 0.0)
assert H.shares(B, E, D)[1] is None

# 5. non-uniform dt: seconds, not sample counts
B, E, D = H.band_seconds([100, 100, 100], [1000, 1000, 0], [5, -5, 5], [0.5, 2.0, 3.0])
assert (B, E, D) == (5.5, 2.5, 0.5)

# 6. sensitivity threshold 300 admits rpm 350
_, E3, _ = H.band_seconds([100], [350.0], [5], [1], thr=300.0)
assert E3 == 1.0
_, E4, _ = H.band_seconds([100], [350.0], [5], [1], thr=400.0)
assert E4 == 0.0

# 7. day-clustered bootstrap known answer: two days with constant values -> degenerate interval at the pooled mean
vals = {"d1": np.array([0.2, 0.2]), "d2": np.array([0.6, 0.6])}
est, lo, hi = H.day_bootstrap(vals, lambda x: float(np.mean(x)), draws=500, seed=42)
close(est, 0.4)
assert 0.2 - 1e-12 <= lo <= est <= hi <= 0.6 + 1e-12
# one day only: every draw is the same day
est, lo, hi = H.day_bootstrap({"d1": np.array([0.3, 0.5])}, lambda x: float(np.mean(x)), draws=100)
close(est, 0.4); close(lo, 0.4); close(hi, 0.4)
print("ok test_highway_share")
