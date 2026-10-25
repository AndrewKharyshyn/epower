"""M507 (Rev 2) mechanics tests of tools/few_cluster_coverage.py: delta-method SE by hand, closed-form R0 against a large simulation, determinism, smallest-G rule, normal-mean interval near 0.95 at large G.
Coverage direction/size predictions (percentile below 0.92 at G = 5; t closer to 0.95; both near 0.95 at G = 40) are logged in the spec as predictions and are NOT assertions here."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
from scipy import stats
import few_cluster_coverage as F

N, D = np.array([3.0, 5.0, 8.0]), np.array([1.0, 2.0, 4.0])
R = 16 / 7
res = np.array([3 - R, 5 - 2 * R, 8 - 4 * R])
se_hand = np.sqrt(3 / 2 * np.sum(res ** 2)) / 7.0
lo, hi, se = F.interval_t(N, D)
assert abs(se - se_hand) < 1e-12 and abs((lo + hi) / 2 - R) < 1e-12 and abs((hi - lo) / 2 - stats.t.ppf(0.975, 2) * se_hand) < 1e-12
# closed-form R0 against a large simulation of independent days
chk = F.r0_check(np.random.default_rng(3), n_days=200_000)
assert abs(chk - F.R0_CLOSED) / F.R0_CLOSED < 0.01, (chk, F.R0_CLOSED)
# determinism of a cell given the same SeedSequence
a = F.cell(5, 0.0, float(F.R0_CLOSED), 100, 100, np.random.SeedSequence(7)); b = F.cell(5, 0.0, float(F.R0_CLOSED), 100, 100, np.random.SeedSequence(7))
assert a == b
# the AR(1) series starts from its stationary marginal and has the requested lag-1 correlation (large G)
e = F.day_effects(200_000, 0.3, np.random.default_rng(5))
assert abs(e.std() - F.SD_DAY) / F.SD_DAY < 0.02 and abs(np.corrcoef(e[:-1], e[1:])[0, 1] - 0.3) < 0.02
# smallest-G rule: smallest G whose coverage + 2 MCSE >= 0.93 and that also holds at every larger G
mk = lambda G, c: {"G": G, "phi": 0.0, "percentile": {"coverage": c, "mcse": 0.005}}
cells = [mk(3, 0.80), mk(5, 0.95), mk(10, 0.90), mk(20, 0.94), mk(40, 0.95)]
assert F.smallest_g(cells, "percentile", 0.0) == 20          # G = 5 passes alone, but G = 10 fails, so the rule gives 20
# a normal-mean interval (known answer) near 0.95 at large G: the t interval for denominators equal to 1 is the classical mean interval
rng = np.random.default_rng(11); hits = 0
for _ in range(1500):
    x = 2.0 + rng.standard_normal(60)
    lo, hi, _ = F.interval_t(x, np.ones(60)); hits += (lo <= 2.0 <= hi)
assert 0.93 <= hits / 1500 <= 0.97, hits / 1500
print("test_few_cluster_coverage: OK")
