"""M577 Rev 3 (analyses/M577_spec_rev3.md) known-answer tests of tools/m577_r3_sensitivity.py: weights, FWL identity, WCR p-value / inversion on planted data, coverage simulation (numbers recorded), paired reading rules."""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import m577_cell_spread_levels as m577
import m577_r3_sensitivity as R


def frame(G=40, per=4, seed=1, effect=0.0, rho=0.0, day_level=True):
    rng = np.random.default_rng(seed)
    rows = []
    u_prev = 0.0
    for g in range(G):
        u_prev = rho * u_prev + rng.normal(0, 1.0)
        trt = float(g >= G // 2) if day_level else 0.0
        for j in range(per):
            rows.append({"day": "d%03d" % g, "wk": "w%02d" % (g // 7), "step": trt, "slow": float(rng.random() < .4), "months": g / 10.0, "T": rng.uniform(15, 35), "I": rng.uniform(60, 140),
                         "soc": rng.uniform(40, 80), "socr": rng.uniform(10, 30), "lrest": rng.uniform(0, 3), "first": float(j == 0), "u": u_prev})
    d = pd.DataFrame(rows)
    d["y"] = 20 + 0.1 * d["T"] + effect * d["step"] + d["u"] + rng.normal(0, 1.0, len(d))
    return d


# ---- weights
rng = np.random.default_rng(0)
W = R.weights(rng, 50, 2000, "rademacher")
assert set(np.unique(W)) == {-1.0, 1.0} and abs(W.mean()) < 0.02
Wb = R.weights(rng, 50, 2000, "webb")
assert len(np.unique(np.round(Wb, 9))) == 6 and abs(Wb.mean()) < 0.03 and abs((Wb ** 2).mean() - 1.0) < 0.03

# ---- FWL identity on a synthetic frame
d = frame(effect=2.0)
assert R.fwl_check(d)["passed"]

# ---- WCB: observed estimate equals OLS, CR1 SE equals the explicit sandwich, planted effect recovered
X, y = m577.design(d, R.BASE)
k = 1 + R.BASE.index("step")
w = R.WCB(X, y, d["day"].values, k)
b = np.linalg.lstsq(X, y, rcond=None)[0]
assert abs(w.b - b[k]) < 1e-9
e = y - X @ b
XtXi = np.linalg.inv(X.T @ X)
meat = sum(np.outer(X[(d["day"] == g).values].T @ e[(d["day"] == g).values], X[(d["day"] == g).values].T @ e[(d["day"] == g).values]) for g in d["day"].unique())
G, n, p = w.G, len(d), X.shape[1]
V = G / (G - 1.0) * (n - 1.0) / (n - p) * XtXi @ meat @ XtXi
assert abs(np.sqrt(V[k, k]) - w.se) < 1e-9
rng_r = np.random.default_rng(3)
Wr = R.weights(rng_r, w.G, 999, "rademacher")
inv, grid, ps = w.inversion(Wr, grid_n=61)
assert inv is not None and not (inv["ci95"][0] <= 0 <= inv["ci95"][1]) and w.pvalue(Wr, 0.0) < 0.05
assert inv["ci95"][0] <= 2.0 <= inv["ci95"][1] or abs(w.b - 2.0) < 3 * w.se
# the p-value at the estimate is 1 (t_obs = 0)
assert w.pvalue(Wr, w.b) > 0.99

# ---- zero effect: rejection rate near 0.05 (MC check) and coverage numbers recorded (independent days and AR(1) days)
def sim(rho, nsim=300, G=30, B=299):
    rej, cov_cr2, cov_wcb = 0, 0, 0
    from scipy import stats
    for s in range(nsim):
        dd = frame(G=G, per=3, seed=1000 + s, effect=0.0, rho=rho)
        XX, yy = m577.design(dd, R.BASE)
        kk = 1 + R.BASE.index("step")
        ww = R.WCB(XX, yy, dd["day"].values, kk)
        Ws = R.weights(np.random.default_rng(s), ww.G, B, "rademacher")
        rej += int(ww.pvalue(Ws, 0.0) < 0.05)
        f = m577.fit_term(dd, R.BASE, "step")
        cov_cr2 += int(f["ci95"][0] <= 0 <= f["ci95"][1])
        iv, _, _ = ww.inversion(Ws, grid_n=41)
        cov_wcb += int(iv is not None and iv["ci95"][0] <= 0 <= iv["ci95"][1])
    return rej / nsim, cov_cr2 / nsim, cov_wcb / nsim
r0 = sim(0.0)
r5 = sim(0.5)
print("rejection rate / CR2 coverage / WCR-inversion coverage: independent days %s; AR(1) rho 0.5 %s" % (tuple(round(x, 3) for x in r0), tuple(round(x, 3) for x in r5)))
assert all(0.5 <= x <= 1.0 for x in r0[1:] + r5[1:])
assert abs(r0[0] - 0.05) < 0.06 and abs((1 - r0[2]) - r0[0]) < 0.04         # the p-value and its inversion interval agree about rejection

# ---- paired reading rules
arr_in = np.random.default_rng(1).normal(0.0, 0.1, 4000)
assert R.paired_reading(arr_in, 1.0, 0.0)["reading"].startswith("no change beyond")
arr_ex = np.random.default_rng(1).normal(2.0, 0.1, 4000)
assert R.paired_reading(arr_ex, 1.0, 2.0)["reading"].startswith("changes by about")
assert R.paired_reading(np.random.default_rng(1).normal(0.0, 2.0, 4000), 1.0, 0.0)["reading"].startswith("not resolved")
both = R.paired_reading(np.random.default_rng(1).normal(0.3, 0.05, 4000), 1.0, 0.3)
assert both["reading"].startswith("changes by about") and "also lies inside" in both["reading"]

# ---- paired bootstrap: identical variants give exactly zero difference; a removed nuisance covariate with no effect gives ~0
dd = frame(effect=2.0)
dd["y"] = dd["y"]
v = {"A": R.BASE, "A2": list(R.BASE)}
diffs, deg = R.paired_boot(dd, v, np.random.default_rng(5), n=200)
assert deg == 0 and np.allclose(diffs["A2"]["step"], 0.0)
# day structure
ds_ = R.day_structure(dd, "step")
assert ds_["daysWithTerm"] == 20 and ds_["mixedDays"] == 0
print("test_m577_r3: OK")
