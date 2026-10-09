"""M386b: the NumPy phase-energy helpers of _csg_events (compute_summary_arrays._csg_phase_np / _csg_phx_np) reproduce the former per-window pandas chain
(iloc slice, dropna, sum, clip(lower=0), sum) BIT-FOR-BIT: random power series with NaN runs, +/-0.0, all-NaN and empty windows, negative and out-of-range indices."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import numpy as np, pandas as pd
import compute_summary_arrays as C


def phase_old(p, a, b):          # the former nested _phase, verbatim
    seg = p.iloc[a:b + 1].dropna()
    if not len(seg):
        return (None, None, None)
    return (float(seg.sum()) / 3.6, float(seg.clip(lower=0).sum()) / 3.6, float((-seg).clip(lower=0).sum()) / 3.6)


def phx_old(p, a, b):            # the former nested _phx, verbatim
    raw_seg = p.iloc[a:b + 1]
    seg = raw_seg.dropna()
    cov = round(float(len(seg)) / float(len(raw_seg)), 4) if len(raw_seg) else 0.0
    if not len(seg):
        return (None, None, None, 0.0)
    return (float(seg.sum()) / 3.6, float(seg.clip(lower=0).sum()) / 3.6, float((-seg).clip(lower=0).sum()) / 3.6, cov)


def same(x, y):
    if x is None or y is None:
        return x is None and y is None
    return all((u is None and v is None) or (u is not None and v is not None and (u == v) and np.signbit(u) == np.signbit(v)) for u, v in zip(x, y)) and len(x) == len(y)


rng = np.random.default_rng(7)
n_checked = 0
for trial in range(60):
    n = int(rng.integers(5, 400))
    v = rng.normal(0, 40, n)
    v[rng.random(n) < 0.15] = np.nan
    v[rng.random(n) < 0.05] = 0.0
    v[rng.random(n) < 0.03] = -0.0
    if trial % 7 == 0:
        v[:] = np.nan                                         # all-NaN series
    if trial % 11 == 0:
        v[:] = 0.0                                            # all zeros (+0.0 / -0.0 signs)
    p = pd.Series(v)
    pv = p.to_numpy(dtype=float)
    for _ in range(80):
        a = int(rng.integers(-n // 4, n)); b = int(rng.integers(-n // 4, n + 10))
        assert same(phase_old(p, a, b), C._csg_phase_np(pv, a, b)), (trial, a, b)
        assert same(phx_old(p, a, b), C._csg_phx_np(pv, a, b)), (trial, a, b)
        n_checked += 1
assert same(C._csg_phase_np(np.array([]), 0, 3), (None, None, None))
print("OK test_csg_phase_np (%d windows, bit-identical incl. signed zeros)" % n_checked)
