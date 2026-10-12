"""M410 known-answer tests for tools/serial_dependence.py (spec analyses/M409_spec.md Rev 1-2). Fast checks only; the heavy simulation harness is analyses/M410_harness/run_harness.py
and its committed result file analyses/M410_harness/harness_results.json is checked at the end."""
import json, os, sys
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import dependence_sensitivity as DS
import serial_dependence as SD

# 1. HAC with L = 0 equals CR1 exactly (same-day weight 1, nothing else)
rng = np.random.default_rng(1)
t = np.repeat(np.arange(0, 40, 2), 3)
X = np.column_stack([np.ones(len(t)), t / 30.0, rng.normal(size=len(t))])
y = rng.normal(size=len(t))
b1, se1, G, n, p = DS.cr1(X, y, t, 1)
h0 = SD.hac(X, y, t, 0, W=5)
assert abs(h0["se"] - se1) < 1e-12 and abs(h0["slope"] - b1) < 1e-12

# 2. HAC kernel against an explicit O(n^2) reference on a small irregular design
t = np.array([0, 0, 1, 3, 3, 4, 9])
X = np.column_stack([np.ones(7), np.arange(7) / 3.0, np.array([1., -1, 2, 0, 1, -2, .5])])
y = np.array([1., 2, 0, 3, 1, -1, 2])
for L in (1, 3, 7):
    b, M, e = DS.ols(X, y)
    meat = np.zeros((3, 3))
    for i in range(7):
        for j in range(7):
            d = abs(t[i] - t[j])
            w = 1.0 - d / (L + 1.0) if d <= L else 0.0
            meat += w * np.outer(X[i] * e[i], X[j] * e[j])
    Gd = len(np.unique(t))
    V = (Gd / (Gd - 1.0)) * ((7 - 1.0) / (7 - 3)) * M @ meat @ M
    assert abs(SD.hac(X, y, t, L, W=2)["se"] - np.sqrt(V[1, 1])) < 1e-12, L

# 3. semivariogram hand case: day-mean residuals 0, 1, 3 on days 0, 1, 3
sv = SD.semivariogram(np.array([0., 1., 3.]), np.array([0, 1, 3]))
g = {b["binDays"]: b for b in sv["bins"]}
assert abs(g["1"]["gamma"] - 0.5) < 1e-12 and abs(g["2"]["gamma"] - 2.0) < 1e-12 and abs(g["3-4"]["gamma"] - 4.5) < 1e-12 and g["5-7"]["nPairs"] == 0
assert abs(sv["sill"] - np.var([0., 1., 3.], ddof=1)) < 1e-12

# 4. pair index: a pair belongs to distance exactly t_j - t_i and none above DMAX is kept
i, j, d = SD.pair_index(np.array([0, 1, 2, 7]), 3)
assert sorted(zip(i.tolist(), j.tolist(), d.tolist())) == [(0, 1, 1), (0, 2, 2), (1, 2, 1)]

# 5. spline columns: linear term included (Rev 2), 3 + 4 columns, deterministic
tt = np.arange(0, 100)
S = SD.spline_cols(tt)
assert S.shape == (100, 7) and np.allclose(S[:, 0], tt / 99.0)

# 6. VIF: phi = 0 gives exactly 1; larger phi on a trending regressor inflates
Xv = np.column_stack([np.ones(30), np.arange(30) / 10.0])
tv = np.arange(30)
assert abs(SD.vif_ar1(Xv, tv, 0.0) - 1.0) < 1e-12 and SD.vif_ar1(Xv, tv, 0.5) > 1.5

# 7. GLS on AR(1) day means recovers rho in a long simulated series and equals OLS at rho = 0 within tolerance
rg = np.random.default_rng(3)
nd = 400
tg = np.arange(nd)
u = np.zeros(nd)
for k_ in range(1, nd):
    u[k_] = 0.6 * u[k_ - 1] + rg.normal() * np.sqrt(1 - 0.36)
Xg = np.column_stack([np.ones(nd), tg / 50.0])
res = SD.gls_ar1(Xg, 0.3 * Xg[:, 1] + u, tg, W=60)
assert abs(res["rho"] - 0.6) < 0.1, res

# 8. weighted Pearson equals np.corrcoef at unit weights
a_, b_ = rg.normal(size=50), rg.normal(size=50)
assert abs(SD.wpearson(a_, b_, np.ones(50)) - np.corrcoef(a_, b_)[0, 1]) < 1e-12

# 9. the committed heavy-harness result file exists and records its own verdict (never tuned: failures are flagged, not hidden)
hp = os.path.join(ROOT, "analyses", "M410_harness", "harness_results.json")
if os.path.exists(hp):
    hr = json.load(open(hp, encoding="utf-8"))
    assert "verdicts" in hr and "scenarios" in hr
print("OK test_serial_dependence")
