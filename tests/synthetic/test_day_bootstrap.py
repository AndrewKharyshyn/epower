"""M383 (audit F22): the sufficient-statistic day bootstrap reproduces the former pd.concat-per-draw dayboot() (same draws, same estimator)."""
import os, sys, time
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
from day_bootstrap import ratio_boot_ci
from gtr_closure_diag import dayboot            # the former implementation (kept for non-ratio statistics)

# known-answer: two days, hand-computed resamples are all combinations of {d1, d2}
df = pd.DataFrame({"date": ["a", "a", "b"], "n": [1.0, 3.0, 10.0], "m": [2.0, 2.0, 5.0]})
ci = ratio_boot_ci(df, "n", "m", nb=50, seed=1)
assert 4 / 4 <= ci[0] <= ci[1] <= 10 / 5, ci            # per-day ratios 1.0 and 2.0 bound every resample

# repository data: all ratio statistics of the closure diagnostic, old vs new
d = pd.read_csv(os.path.join(ROOT, "analyses", "M377c_closure_perdrive.csv"))
rows = [("excess", "E_gen"), ("excess_engonly", "E_gen"), ("excess_ps", "E_gen_ps"), ("gen_def_gap", "E_gen")]
t_old = t_new = 0.0
for num, den in rows:
    t0 = time.perf_counter(); old = dayboot(d, lambda x: float(x[num].sum() / x[den].sum()), nb=500); t1 = time.perf_counter()
    new = ratio_boot_ci(d, num, den, nb=500); t2 = time.perf_counter()
    t_old += t1 - t0; t_new += t2 - t1
    assert np.allclose(old, new, rtol=0, atol=1e-12), (num, den, old, new)
old = dayboot(d, lambda x: float(x.E_gen.sum() / x.km.sum() * 100.0), nb=500); new = ratio_boot_ci(d, "E_gen", "km", scale=100.0, nb=500)
assert np.allclose(old, new, rtol=0, atol=1e-10), (old, new)
print("OK test_day_bootstrap: old %.2f s, new %.3f s (%.0fx)" % (t_old, t_new, t_old / max(t_new, 1e-9)))
