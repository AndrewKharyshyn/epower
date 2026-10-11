"""M401 (audit N04): day-cluster ratio bootstrap input semantics. Expected values come from independent numpy code, not from the module under test."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
from day_bootstrap import ratio_boot_ci, ratio_boot_ci_detail


def manual(days, n, m, nb, seed, scale=1.0):
    """Independent re-implementation: same rng stream (one rng.choice(nd, nd) per draw), ratio of resampled day totals, zero-denominator draws dropped."""
    nd = len(days); rng = np.random.default_rng(seed)
    sn = np.array([sum(n[i] for i in range(len(n)) if days[i] == d) for d in dict.fromkeys(days)]); sd = np.array([sum(m[i] for i in range(len(m)) if days[i] == d) for d in dict.fromkeys(days)])
    nd = len(sn); out = []
    for _ in range(nb):
        p = rng.choice(nd, nd); D = sd[p].sum()
        if D != 0 and np.isfinite(D):
            out.append(scale * sn[p].sum() / D)
    return [float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))], len(out)


# two-day fixture reproduces the declared (independently computed) CI
df = pd.DataFrame({"date": ["a", "a", "b"], "n": [1.0, 3.0, 10.0], "m": [2.0, 2.0, 5.0]})
exp, used = manual(list(df.date), list(df.n), list(df.m), 200, 3)
ci, nu = ratio_boot_ci_detail(df, "n", "m", nb=200, seed=3)
assert np.allclose(ci, exp, rtol=0, atol=1e-12) and nu == used == 200, (ci, exp)
assert np.allclose(ratio_boot_ci(df, "n", "m", nb=200, seed=3), exp, rtol=0, atol=1e-12)

# NaN: explicit error naming the column (default), former per-column skip-NaN semantics only on request
dn = df.copy(); dn.loc[1, "n"] = np.nan
try:
    ratio_boot_ci(dn, "n", "m", nb=10); raise SystemExit("NaN accepted silently")
except ValueError as e:
    assert "n" in str(e) and "non-finite" in str(e)
exp_skip, _ = manual(list(dn.date), [1.0, 0.0, 10.0], list(dn.m), 200, 3)
assert np.allclose(ratio_boot_ci(dn, "n", "m", nb=200, seed=3, nan="skipna"), exp_skip, rtol=0, atol=1e-12)
di = df.copy(); di.loc[0, "m"] = np.inf
for kw in ({}, {"nan": "skipna"}):
    try:
        ratio_boot_ci(di, "n", "m", nb=10, **kw); raise SystemExit("inf accepted")
    except ValueError:
        pass

# zero-denominator draws are excluded and counted; all-invalid returns [nan, nan]; empty frame raises
dz = pd.DataFrame({"date": ["a", "b", "c"], "n": [1.0, 2.0, 0.0], "m": [2.0, 4.0, 0.0]})
exp, used = manual(list(dz.date), list(dz.n), list(dz.m), 300, 5)
ci, nu = ratio_boot_ci_detail(dz, "n", "m", nb=300, seed=5)
assert nu == used and 0 < nu < 300 and np.allclose(ci, exp, rtol=0, atol=1e-12), (nu, used, ci, exp)
d0 = pd.DataFrame({"date": ["a", "b"], "n": [0.0, 0.0], "m": [0.0, 0.0]})
ci, nu = ratio_boot_ci_detail(d0, "n", "m", nb=20, seed=1)
assert nu == 0 and all(np.isnan(ci))
try:
    ratio_boot_ci(df.iloc[0:0], "n", "m", nb=10); raise SystemExit("empty frame accepted")
except ValueError as e:
    assert "empty" in str(e)
# tuple (sum of columns) form still works and is checked
dt = pd.DataFrame({"date": ["a", "b"], "n": [1.0, 2.0], "n2": [1.0, 1.0], "m": [2.0, 2.0]})
assert np.allclose(ratio_boot_ci(dt, ("n", "n2"), "m", nb=50, seed=2), manual(["a", "b"], [2.0, 3.0], [2.0, 2.0], 50, 2)[0], rtol=0, atol=1e-12)
print("OK test_day_bootstrap_guards")
