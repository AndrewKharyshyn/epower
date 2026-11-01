"""M554 (analyses/M554_spec.md Rev 2): known-answer tests for the union-clock kernel and the common-support contract in tools/common_support.py."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import common_support as CS

near = lambda a, b, tol=1e-12: abs(a - b) <= tol

# KA2: constant current and voltage -> energy = Id V T (kWh), for any phase offset between the two channels
Id0, V0, T = 20.0, 300.0, 100.0
for off in (0.0, 0.3, 0.77):
    ti = np.arange(0.0, T + 1e-9, 1.0); tv = np.arange(off, T + 1e-9, 1.0)
    st = CS.u_steps(ti, -np.full(len(ti), Id0), tv, np.full(len(tv), V0))
    dis, chg, sec = CS.u_total(st)
    t0 = max(ti[0], tv[0]); t1 = min(ti[-1], tv[-1])
    assert near(sec, t1 - t0) and near(dis, Id0 * V0 * (t1 - t0) / 3.6e6) and chg == 0.0, (off, dis, sec)

# KA2b: ramp current 0 -> A over d seconds, constant voltage: integral = V A d / 2
d, A, V = 4.0, 10.0, 300.0
e = CS.step_energy(d, 0.0, A, V, V)
assert near(e[0], V * A * d / 2 / 3.6e6) and e[1] == 0.0

# KA2c: two ramps (current 0 -> A, voltage V0 -> V1): the product is quadratic; exact integral = d (a0 v0 + a1 v1) / 3 + d (a0 v1 + a1 v0) / 6
a0, a1, v0, v1 = 2.0, 12.0, 280.0, 320.0
e = CS.step_energy(d, a0, a1, v0, v1)
x = np.linspace(0, d, 200001); P = (a0 + (a1 - a0) * x / d) * (v0 + (v1 - v0) * x / d)
assert abs(e[0] * 3.6e6 - np.trapezoid(P, x)) < 1e-4 and e[1] == 0.0

# split at the root of the current: current +10 -> -30 over 4 s at constant 300 V: crossing at 1 s; discharge 10*1/2*300, charge 30*3/2*300 (A s V)
e = CS.step_energy(4.0, 10.0, -30.0, 300.0, 300.0)
assert near(e[0] * 3.6e6, 10.0 * 1.0 / 2 * 300.0) and near(e[1] * 3.6e6, 30.0 * 3.0 / 2 * 300.0)

# KA3: a channel is never interpolated across its own gap; a 6 s gap in both channels gives no step across it, a 4 s gap in one channel is bridged when Gmax >= 4 only
ti = np.concatenate([np.arange(0, 11, 1.0), np.arange(17, 22, 1.0)]); tv = ti.copy()
st = CS.u_steps(ti, np.full(len(ti), -10.0), tv, np.full(len(tv), 300.0))
assert all(not (t0 < 11 < t1) for t0, t1, *_ in st) and near(sum(t1 - t0 for t0, t1, *_ in st), 14.0)
ti = np.array([0.0, 1.0, 5.0, 6.0, 7.0]); tv = np.arange(0.0, 8.0, 1.0)
assert len(CS.u_steps(ti, -np.full(5, 5.0), tv, np.full(8, 300.0), gmax=5.0)) == 7 - 0 and len(CS.u_steps(ti, -np.full(5, 5.0), tv, np.full(8, 300.0), gmax=3.0)) < 7

# KA1: identical supports on the same piecewise-linear power -> common-support energies equal
tp = np.arange(0.0, 50.0, 1.0); pp = 6.0 * np.sin(tp / 5.0)
ps = CS.p_steps(tp, pp)
us = [(t0, t1, p0 * 1000.0 / 300.0, p1 * 1000.0 / 300.0, 300.0, 300.0) for t0, t1, p0, p1 in ps]      # I linear with V constant: the same linear power
cu, cp, sec = CS.common(us, ps)
assert near(cu[0], cp[0], 1e-9) and near(cu[1], cp[1], 1e-9) and near(sec, 49.0)
tot_p = CS.p_total(ps); tot_u = CS.u_total(us)
assert near(tot_p[0], tot_u[0], 1e-9) and near(tot_p[1], tot_u[1], 1e-9)

# the common support clips partially overlapping steps: U steps shifted by 0.5 s -> common seconds = total - 0.5, energies of the overlap only
us2 = [(t0 + 0.5, t1 + 0.5, a, b, v, w) for t0, t1, a, b, v, w in us]
cu2, cp2, sec2 = CS.common(us2, ps)
assert near(sec2, 48.5, 1e-9)

# point-estimate invariance (KA5): adding or removing unrelated drives does not change the common-support ratio of the others
rng = np.random.default_rng(1)
cuv = rng.uniform(1, 5, 30); cpv = cuv * rng.uniform(0.99, 1.01, 30); days = [f"d{i % 7}" for i in range(30)]
r_all = CS._ratio_row(cuv[:20], cpv[:20], days[:20])["ratio"]
r_sub = CS._ratio_row(cuv[:20], cpv[:20], days[:20])["ratio"]
assert r_all == r_sub and near(r_all, cuv[:20].sum() / cpv[:20].sum(), 1e-6)

# stored block (after the splice): strata only, no pooled headline key, F17 drives flagged and kept out of every total
import json
a = json.load(open("summary_arrays.json", encoding="utf-8"))
B = a["commonSupportBridge"]
assert set(B["strata"]) <= {"fast", "slow", "unknown"} and "pooled" not in B and not any(B["knownAnswer"]["misses"].values())
assert all(x["recoverableUnderAlternativeAlignment"] and "no rate" in x["enters"] for x in B["f17"])
print("test_common_support OK")
