"""M603 known-answer tests (analyses/M603_spec.md Rev 1 section 6) for tools/steady_load_spread.py."""
import os, sys
import numpy as np
import pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import steady_load_spread as S

NS = 10**9


def close(a, b, tol=1e-9):
    assert abs(a - b) < tol, (a, b)


# native current at 1 s cadence: flat 60 A for 10 s, then a ramp of 10 A/s
tI = np.arange(0, 20) * NS
vI = np.r_[np.full(10, 60.0), 60.0 + 10.0 * np.arange(1, 11)]
# 1. flat part qualifies, ramp part does not (slew 10 A/s > 3), midpoints between samples
tm = np.array([3.5, 5.5, 12.5, 15.5]) * NS
absI = np.abs(np.interp(tm / NS, tI / NS, vI))
m = S.steady_mask(absI, tm.astype(np.int64), tI, vI)
assert list(m) == [True, True, False, False], m

# 2. current band edges are inclusive (30 and 100), 29.9 and 100.1 excluded
flat = np.full(6, 50.0); tf = np.arange(6) * NS
mm = S.steady_mask([30.0, 100.0, 29.9, 100.1], np.full(4, int(2.5 * NS)), tf, flat)
assert list(mm) == [True, True, False, False], mm

# 3. a bracket gap above 2 s makes the pair non-qualifying (slew undefined); exactly 2 s qualifies
tg = np.array([0, 1, 4, 5]) * NS            # gap 3 s between index 1 and 2
assert not S.steady_mask([50.0], [int(2.5 * NS)], tg, np.full(4, 50.0))[0]
th = np.array([0, 1, 3, 4]) * NS            # gap 2 s
assert S.steady_mask([50.0], [int(2.0 * NS) + 5], th, np.full(4, 50.0))[0]

# 4. duplicate native timestamps are dropped (first kept)
td = np.array([0, 1, 1, 2, 3]) * NS
assert S.steady_mask([50.0], [int(1.5 * NS)], td, np.array([50.0, 50.0, 90.0, 50.0, 50.0]))[0]

# 5. pair before the first or after the last native sample: undefined
assert not S.steady_mask([50.0], [-1], tf, flat)[0] and not S.steady_mask([50.0], [int(9 * NS)], tf, flat)[0]

# 6. fixed-window slew: range within +/- 1 s must be <= 3 A
ramp_v = np.array([50, 50, 50, 56, 56, 56], dtype=float)
assert S.fixed_window_mask([50.0], [int(1.0 * NS)], tf, ramp_v)[0]            # window 0..2 s: range 0
assert not S.fixed_window_mask([50.0], [int(3.0 * NS)], tf, ramp_v)[0]        # window 2..4 s: range 6

# 7. signed 20 A bands inside 30-100
assert [S.iband(x) for x in (30, 49.9, 50, 70, 90, 100, -30, -70, -100, 29, 101, 0)] == [1, 1, 2, 3, 4, 4, -1, -3, -4, 0, 0, 0]

# 8. p95 uses linear interpolation (pandas default); floor handled by the caller
close(S.p95(np.arange(1, 101)), 95.05)
assert S.p95([]) is None

# 9. Theil-Sen recovers an exactly linear slope and resists one outlier day
x = np.arange(10, dtype=float); y = 2.0 * x + 1.0
close(S.theil_sen(x, y), 2.0)
y2 = y.copy(); y2[4] = 100.0
close(S.theil_sen(x, y2), 2.0, 1e-9)
assert S.theil_sen([1.0, 1.0], [1.0, 2.0]) is None                     # no distinct x

# 10. day / week bootstrap on exact data: degenerate interval at the truth
g = pd.DataFrame({"x": x, "y": y, "wk": np.repeat(["a", "b"], 5)})
est, lo, hi, nb = S._ts_boot(g, "day", 200)
close(est, 2.0); close(lo, 2.0); close(hi, 2.0)

# 11. outcome grades
def mk(est, lo, hi):
    return {"est": est, "ci95": [lo, hi], "halfWidth": (hi - lo) / 2}
ld = mk(0.74, 0.41, 1.07)
assert S.grade(mk(0.6, 0.3, 0.9), ld, {"est": -0.14, "ci95": [-0.5, 0.2]}) == "CONSISTENT"
assert S.grade(mk(0.3, 0.05, 0.55), ld, {"est": -0.44, "ci95": [-0.7, -0.2]}) == "ATTENUATED"
assert S.grade(mk(0.2, -0.2, 0.6), ld, {"est": -0.54, "ci95": [-0.8, -0.3]}) == "ARTEFACT-SUPPORTED"
assert S.grade(mk(0.2, -1.5, 1.9), ld, {"est": -0.54, "ci95": [-0.8, -0.3]}) == "UNINFORMATIVE"      # half-width 1.7 > 0.74
assert S.grade(mk(0.9, 0.7, 1.1), ld, {"est": 0.16, "ci95": [0.05, 0.3]}) == "UNDECIDED"

# 12. paired difference: identical outcomes give D = 0 with a degenerate interval
rng = np.random.default_rng(1)
dfp = pd.DataFrame({"months": np.repeat(np.arange(8, dtype=float), 3), "T": rng.normal(size=24), "I": rng.normal(size=24), "day": np.repeat(np.arange(8).astype(str), 3)})
dfp["ys"] = 3.0 + 1.5 * dfp["months"] + 0.2 * dfp["T"]; dfp["yl"] = dfp["ys"]
r = S.paired_difference(dfp, "ys", "yl", 200)
close(r["est"], 0.0, 1e-9); close(r["ci95"][0], 0.0, 1e-9); close(r["slopeSteady"], 1.5, 1e-9)
dfp["yl"] = dfp["ys"] + 0.5 * dfp["months"]                              # loaded slope larger by 0.5 -> D = -0.5
close(S.paired_difference(dfp, "ys", "yl", 200)["est"], -0.5, 1e-9)
print("ok test_steady_load_spread")
