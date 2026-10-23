"""M490 known-answer tests (spec analyses/M490_spec.md Rev 2, audit Update 7 A06): the registered support rule 'an interval touches a speed bin iff its TOTAL overlap with the bin is at least touchMinS (25 ms)' is
subdivision invariant. Inserting redundant native I / V knots (samples on the same straight line) splits the pieces but must change neither the touch flag nor the energies. Cases: constant and varying signals, at and around
the threshold (24 ms, 24.99 ms, 25 ms, 25.01 ms, 100 ms), several subdivisions each; a bin edge crossing; the former per-piece rule is reproduced on the 100 ms / ten 10 ms counterexample (it said not touched)."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import regen_v2 as R

NB = R.NB


def run(dt, knots_i, knots_v, i_fun, v_fun, v0=30.0, slope=10.0):
    """One braking interval [0, dt] from v0 km/h falling by `slope` km/h per second; I(t) and V(t) are the given straight lines sampled at the knots (plus the two far ends)."""
    ti = np.unique(np.concatenate([[-1.0, dt + 1.0], knots_i])); tv = np.unique(np.concatenate([[-1.0, dt + 1.0], knots_v]))
    S = R._exact_energy(np.array([0.0]), np.array([dt]), np.array([v0]), np.array([v0 - slope * dt]), ti, i_fun(ti), tv, v_fun(tv), None)
    comb = S["owner"] * NB + S["bin"]
    flags = R.touch_flags(comb, S["piece_h"], NB)
    return S, flags


def overlap_case(d, n_split, i_fun, v_fun, rng=None):
    """Interval whose overlap with speed bin 1 (10-20 km/h) is d seconds: it crosses 20 km/h at t = 1.0 (30 -> 20 at 10 km/h per second) and ends d later. n_split redundant knots are inserted inside the overlap."""
    dt = 1.0 + d
    if rng is None:
        inner = 1.0 + d * np.arange(1, n_split) / n_split          # equally spaced redundant knots
    else:
        inner = np.sort(1.0 + d * rng.uniform(0.05, 0.95, max(n_split - 1, 0)))
    return run(dt, inner, inner, i_fun, v_fun)


const_i, const_v = (lambda t: np.full_like(t, 7.0)), (lambda t: np.full_like(t, 310.0))
vary_i, vary_v = (lambda t: 5.0 + 3.0 * t), (lambda t: 300.0 + 8.0 * t)

for name, (fi, fv) in {"constant": (const_i, const_v), "varying": (vary_i, vary_v)}.items():
    for d, want in ((0.024, 0), (0.02499, 0), (0.025, 1), (0.02501, 1), (0.1, 1)):
        S0, f0 = overlap_case(d, 1, fi, fv)
        assert int(f0[1]) == want, (name, d, f0[1], want)
        for n in (2, 5, 12, 40):
            S, f = overlap_case(d, n, fi, fv)
            assert np.array_equal(f, f0), (name, d, n, f0[1], f[1])
            assert abs(S["ch"].sum() - S0["ch"].sum()) <= 1e-12 * max(abs(S0["ch"].sum()), 1e-30), (name, d, n)
            assert abs(S["dv2"].sum() - S0["dv2"].sum()) <= 1e-9, (name, d, n)
            assert sorted(set(S["bin"].tolist())) == sorted(set(S0["bin"].tolist()))
        rg = np.random.default_rng(int(d * 1e5) % 1000 + 1)
        for k in (1, 3, 7):
            S, f = overlap_case(d, k + 1, fi, fv, rng=rg)
            assert np.array_equal(f, f0), (name, d, "random", k)
            assert abs(S["ch"].sum() - S0["ch"].sum()) <= 1e-12 * max(abs(S0["ch"].sum()), 1e-30)

# the audit counterexample: a 100 ms overlap as ten 10 ms pieces. The former per-piece rule says not touched, the registered rule says touched; the charge energy is identical (0.0001 kWh scale)
S10, f10 = overlap_case(0.1, 10, const_i, const_v)
in_bin1 = S10["bin"] == 1
assert in_bin1.sum() == 10 and np.allclose(S10["piece_h"][in_bin1], 0.01) and not (S10["piece_h"][in_bin1] >= R.POLICY["touchMinS"]).any()      # old rule: no piece reaches 25 ms
assert int(f10[1]) == 1 and abs(S10["ch"][in_bin1].sum() - 7.0 * 310.0 * 0.1 / 3.6e6) < 1e-15

# a crossing: an interval spanning two bins touches each bin only with its own overlap (the totals are per bin)
S, f = run(2.0, np.array([]), np.array([]), const_i, const_v, v0=30.0, slope=10.0)          # 30 -> 10: bin 2 (20-30) for 1 s, bin 1 (10-20) for 1 s
assert f[1] == 1 and f[2] == 1 and f.sum() == 2
S, f = run(1.0 + 0.02, np.array([1.005, 1.01, 1.015]), np.array([1.005, 1.01, 1.015]), const_i, const_v)          # 20 ms in bin 1, split into four pieces: not touched; bin 2 touched
assert f[1] == 0 and f[2] == 1
# monotone: the new rule never touches fewer cells than the former per-piece rule
rg = np.random.default_rng(3)
for _ in range(200):
    d = rg.uniform(0.001, 0.2); n = int(rg.integers(1, 30))
    S, f = overlap_case(d, n, vary_i, vary_v, rng=rg)
    old = np.zeros(NB, bool)
    old[S["bin"][S["piece_h"] >= R.POLICY["touchMinS"]]] = True
    assert (f.astype(bool) | ~old).all(), (d, n)
print("test_regen_touch_subdivision OK")
