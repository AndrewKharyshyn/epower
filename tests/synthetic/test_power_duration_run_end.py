"""M566 (analyses/M566_spec.md Rev 2): known answers KU1-KU9 of the run-end bracket (upper = adjacent opposite-sign sample with a linear ramp to zero, hold = constant)."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import power_duration as PD
import power_duration_uninterrupted as U

near = lambda a, b, tol=1e-9: abs(a - b) < tol
T = list(range(0, 11)) + [15]; P = [10.0] * 11 + [-10.0]
lo = U.runs_of(T, P, False); pr = U.runs_of(T, P, True); up = U.runs_ext(T, P, "ramp"); ho = U.runs_ext(T, P, "hold")
# KU1
assert near(lo[0][0][-1], 10) and near(pr[0][0][-1], 12.5) and near(up[0][0][-1], 15) and near(ho[0][0][-1], 15)
assert U.run_best(lo, 12) is None and near(U.run_best(pr, 12)["exact"], 28 / 3) and near(U.run_best(up, 12)["exact"], 29 / 3)
assert U.run_best(pr, 14) is None and near(U.run_best(up, 14)["exact"], 62 / 7) and near(U.run_best(ho, 14)["exact"], 10.0)
seg = PD.segments(np.array(T, float), np.array(P, float))[0]
assert near(PD.window_extremes(*seg, 14)["max"], 54 / 7)                       # net (M552) value, exceeded by the upper value: never shown as an ordered pair
for W in (5, 10, 12):                                                            # ordering of the exact values noInterp <= primary <= upper <= hold
    v = [(U.run_best(r, W) or {"exact": None})["exact"] for r in (lo, pr, up, ho)]
    got = [x for x in v if x is not None]
    assert got == sorted(got), (W, v)
# KU3 left end symmetric: -10 at t = 0, +10 at t = 5 .. 15
T3 = [0, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]; P3 = [-10.0] + [10.0] * 11
assert near(U.runs_of(T3, P3, False)[0][0][-1], 10) and near(U.runs_of(T3, P3, True)[0][0][-1], 12.5) and near(U.runs_ext(T3, P3, "ramp")[0][0][-1], 15)
# KU4 zero-duration step: no extension
T4 = [0, 1, 2, 3, 4, 4, 5, 6]; P4 = [10.0] * 5 + [-10.0] * 3
assert near(U.runs_ext(T4, P4, "ramp")[0][0][-1], 4) and near(U.runs_of(T4, P4, True)[0][0][-1], 4) and near(U.runs_of(T4, P4, False)[0][0][-1], 4)
# KU5 gap / segment ends: segments are split before runs, so a gap step is never extended; the first and last knot of a segment have no neighbour
segs = PD.segments(np.array([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 16, 17, 18, 19, 20, 21, 22.0]), np.array([10.0] * 11 + [-10.0] * 7))
assert len(segs) == 2
ru = U.runs_ext(*segs[0], "ramp")
assert len(ru) == 1 and near(ru[0][0][-1], 10)
# 4 s variant of KU1 (one 4 s step): upper run 14
T5 = list(range(0, 11)) + [14]
assert near(U.runs_ext(T5, P, "ramp")[0][0][-1], 14) and near(U.runs_of(T5, P, True)[0][0][-1], 12)
# KU8 opposite-sign samples are hard boundaries: +10, -10, +10 at 5 s: two separate runs, not merged
r8 = U.runs_ext([0, 5, 10], [10.0, -10.0, 10.0], "ramp")
assert len(r8) == 2 and near(r8[0][0][-1], 5) and near(r8[1][0][-1], 5) and near(r8[0][1][-1], 0.0) and near(r8[1][1][0], 0.0)
# KU9 an observed zero sample at the end is not extended
r9 = U.runs_ext([0, 5, 10], [10.0, 0.0, -10.0], "ramp")
assert len(r9) == 1 and near(r9[0][0][-1], 5)
# single same-sign sample between opposite signs becomes a triangle of two steps
r10 = U.runs_ext([0, 5, 10], [-10.0, 10.0, -10.0], "ramp")
assert len(r10) == 1 and near(r10[0][0][-1], 10) and near(r10[0][1][1], 10.0)
print("test_power_duration_run_end OK")
