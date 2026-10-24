"""M497 known-answer tests: Mantel-Haenszel ratio, infinity-draw rule, day-clustered Poisson recovery of a known common ratio."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import m497_start_ratio as M

NB = M.NB
c = np.zeros((NB, 5, 2))
c[0, M.HI] = (10, 100); c[0, M.ST] = (2, 100)            # hand-computed: num 10*100/200=5, den 2*100/200=1
c[1, M.HI] = (30, 300); c[1, M.ST] = (6, 300)            # num 30*300/600=15, den 6*300/600=3
ok = M.eligible(c, n_min=30)
assert ok.sum() == 2 and ok[0] and ok[1]
assert abs(M.mh(c, ok) - 20.0 / 4.0) < 1e-12, M.mh(c, ok)
assert abs(M.crude(c) - (40 / 400) / (8 / 400)) < 1e-12
# degenerate draws: k_st = 0 with k_hi > 0 -> +inf; both 0 -> nan
d = c.copy(); d[:, M.ST, 0] = 0
assert np.isinf(M.mh(d, ok)) and M.mh(d, ok) > 0
e = d.copy(); e[:, M.HI, 0] = 0
assert np.isnan(M.mh(e, ok))
# infinity is kept in the percentiles and reported as unbounded above 2.5 %
draws = np.array([5.0] * 90 + [np.inf] * 10 + [np.nan] * 5)
s = M.summarize(draws)
assert s["nUndefined"] == 5 and s["nInfinite"] == 10 and s["upperUnbounded"] is True and s["hi"] is None
assert M.summarize(np.array([4.0, 5.0, 6.0] * 50))["upperUnbounded"] is False
# synthetic corpus: 60 days, 3 bins, known common ratio 20, day effects; the Poisson/CR1 estimate and the day bootstrap must bracket it in a fixed-seed run
rng = np.random.default_rng(7)
G = 60
cd = np.zeros((G, NB, 5, 2))
for g in range(G):
    eff = np.exp(rng.normal(0, 0.3))
    for j in (4, 5, 6):
        n_st, n_hi = rng.integers(2000, 4000), rng.integers(1000, 2000)
        p = 0.003 * eff
        cd[g, j, M.ST] = (rng.binomial(n_st, p), n_st); cd[g, j, M.HI] = (rng.binomial(n_hi, min(p * 20, 0.9)), n_hi)
pooled = cd.sum(axis=0); okk = M.eligible(pooled)
assert okk.sum() == 3
R = M.mh(pooled, okk); P = M.poisson_cluster(cd, okk, list(range(G)))
assert 14 < R < 28, R
assert P["lo"] < 20 < P["hi"] and abs(np.log(P["ratio"] / R)) < 0.15, (P, R)
b = M.summarize(M.boot(cd, okk, B=400))
assert b["lo"] < 20 < b["hi"], b
print("test_m497_start_ratio: OK")
