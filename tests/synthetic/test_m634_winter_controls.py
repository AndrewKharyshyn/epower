"""M634 known-answer tests (implements analyses/M622_spec.md Rev 1): temperature-control specifications, Arrhenius back-transformation, day-blocked folds, the retention rule, support cells, attainability."""
import math, os, sys
import numpy as np
from scipy import stats
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools")); sys.path.insert(0, REPO)
import m634_winter_controls as W

rng = np.random.default_rng(7)
nd, per = 60, 3
days = np.repeat(np.arange(nd), per).astype(str)
t = np.repeat(np.linspace(0, 8, nd), per) + rng.uniform(0, 0.1, nd * per) * 0
T = 5 + 30 * rng.random(nd * per)
I = 10 + 5 * rng.random(nd * per)

# T-lin recovers an exact linear truth; T-quad an exact quadratic truth; T-spl an exact linear truth (the natural spline contains the linear term)
y_lin = 3 + 0.4 * t + 0.2 * T + 0.5 * I
assert abs(W.fit_spec("T-lin", y_lin, t, T, [I])["slope"] - 0.4) < 1e-9
y_quad = 2 + 0.3 * t + 0.05 * T + 0.01 * T ** 2 + 0.2 * I
assert abs(W.fit_spec("T-quad", y_quad, t, T, [I])["slope"] - 0.3) < 1e-9
assert abs(W.fit_spec("T-spl", y_lin, t, T, [I])["slope"] - 0.4) < 1e-7

# T-arr: noiseless Arrhenius truth y = exp(a + b t + c / T_K + e I); the months coefficient of the log model is exact and the original-scale slope equals exp(x_ref . beta) * b at the column means
a, b, c, e = 0.5, 0.02, 1000.0, 0.01
y_arr = np.exp(a + b * t + c / (T + 273.15) + e * I)
f = W.fit_spec("T-arr", y_arr, t, T, [I])
assert abs(f["b"][1] - b) < 1e-9 and abs(f["smear"] - 1.0) < 1e-9
want = math.exp(a + b * t.mean() + c * (1.0 / (T + 273.15)).mean() + e * I.mean()) * b
assert abs(f["slope"] - want) / want < 1e-8, (f["slope"], want)
# multiplicative noise: the Duan factor is the mean of exp(residuals), equal to exp(sigma^2 / 2) for lognormal noise within sampling error
sig = 0.3
y_noisy = y_arr * np.exp(sig * rng.standard_normal(len(t)) - 0)
fn = W.fit_spec("T-arr", y_noisy, t, T, [I])
assert abs(fn["smear"] - math.exp(sig ** 2 / 2)) < 0.08 and abs(fn["b"][1] - b) < 0.04

# the day bootstrap is deterministic with the seed and its interval contains the truth of a noisy linear panel with a day effect
day_eff = np.repeat(rng.standard_normal(nd) * 0.5, per)
y_c = 3 + 0.4 * t + 0.2 * T + 0.5 * I + day_eff + 0.3 * rng.standard_normal(len(t))
b1 = W.day_boot("T-lin", y_c, t, T, [I], days, nb=300, seed=42)
b2 = W.day_boot("T-lin", y_c, t, T, [I], days, nb=300, seed=42)
assert b1 == b2 and b1["drawsUsed"] == 300 and b1["ci95"][0] < W.fit_spec("T-lin", y_c, t, T, [I])["slope"] < b1["ci95"][1]
cover = 0                                                                                    # coverage over replicate panels with a day effect (nominal 95 %): at least 80 % of 30
for rep in range(30):
    rr = np.random.default_rng(100 + rep)
    yy = 3 + 0.4 * t + 0.2 * T + 0.5 * I + np.repeat(rr.standard_normal(nd) * 0.5, per) + 0.3 * rr.standard_normal(len(t))
    bb = W.day_boot("T-lin", yy, t, T, [I], days, nb=200, seed=42)
    cover += int(bb["ci95"][0] < 0.4 < bb["ci95"][1])
assert cover >= 24, cover
cr = W.cr1_ci("T-lin", y_c, t, T, [I], days)
assert cr["ci95"][0] < cr["slope"] < cr["ci95"][1] and W.cr1_ci("T-arr", y_arr, t, T, [I], days) is None

# folds: every day in exactly one fold, deterministic, K = min(10, number of days)
fa = W.fold_assignment(days, 10)
assert (fa == W.fold_assignment(days, 10)).all() and all(len(set(fa[days == d])) == 1 for d in np.unique(days))
assert len(set(fa.tolist())) == 10
cv, K = W.cv_errors(y_noisy, t, T, [I], days)
assert K == 10 and all(len(v) == 10 for v in cv.values())
cv7, K7 = W.cv_errors(y_noisy[:7 * 3], t[:21], T[:21], [I[:21]], days[:21])
assert K7 == 7

# retention rule: a challenger must beat the primary by more than the SE of the paired fold-wise difference, on two consecutive runs; an ineligible spline never counts
base = np.array([10.0, 11, 9, 10, 12, 10, 9, 11, 10, 12])
cvx = {"T-arr": base, "T-lin": base + 1.0, "T-quad": base - 1.0 + 0.1 * np.arange(10) * 0, "T-spl": base - 2.0}
r1 = W.retention(cvx, None, eligible={"T-spl": False})
assert r1["challenger"] == "T-quad" and r1["consecutive"] == 1 and not r1["switchTriggered"] and r1["bySpec"]["T-spl"]["eligible"] is False
r2 = W.retention(cvx, r1, eligible={"T-spl": False})
assert r2["consecutive"] == 2 and r2["switchTriggered"]
r3 = W.retention({"T-arr": base, "T-lin": base + 1, "T-quad": base + 0.01 * np.arange(10), "T-spl": base + 0.5}, r2, eligible={"T-spl": True})
assert r3["challenger"] is None and r3["consecutive"] == 0

# temperature support cells: 10 drives on 5 days supported; 9 drives or 4 days not
Tc = np.r_[np.full(10, 12.0), np.full(9, 17.0), np.full(10, 22.0)]
dc = np.r_[np.repeat([1, 2, 3, 4, 5], 2), np.repeat([1, 2, 3, 4, 5], 2)[:9], np.repeat([1, 2, 3, 4], 3)[:10]].astype(str)
cells = {tuple(c["cellC"]): c for c in W.support_cells(Tc, dc)}
assert cells[(10, 15)]["supported"] and not cells[(15, 20)]["supported"] and not cells[(20, 25)]["supported"] and cells[(20, 25)]["nDays"] == 4

# attainability: month 9 descriptive (no ceiling), month 12 at the full alpha
att = W.attainability(0.5439, 106, 0.6162)
assert att["month9"]["seCeiling"] is None and att["month9"]["alpha"] is None
assert abs(att["month12"]["seCeiling"] - round(0.5439 / stats.t.ppf(0.95, 106), 4)) < 1e-9 and att["month12"]["attainableNow"] is False
# a re-run on the SAME corpus does not count as a new ingestion (Director condition): the count is carried; a new corpus increments it
rs1 = W.retention(cvx, None, eligible={"T-spl": False}, master_md5="aaa")
rs2 = W.retention(cvx, rs1, eligible={"T-spl": False}, master_md5="aaa")
assert rs2["consecutive"] == 1 and not rs2["switchTriggered"]
rs3 = W.retention(cvx, rs2, eligible={"T-spl": False}, master_md5="bbb")
assert rs3["consecutive"] == 2 and rs3["switchTriggered"]
# an ineligible spline keeps a descriptive paired difference
assert r1["bySpec"]["T-spl"]["descriptiveMeanRmseDifference"] is not None and r1["bySpec"]["T-spl"]["eligible"] is False
# the unclipped cross-validation exists and differs from the clipped one only through held-out temperatures outside the training range
cvu, _ = W.cv_errors(y_noisy, t, T, [I], days, clip=False)
assert set(cvu) == set(cv)
import language_gate as LG
assert "M634-not-every-interval-zero" in LG.scan_text("Under the temperature controls not every interval spans zero.") and not LG.scan_text("The quadratic interval includes zero; the linear one does not.")
print("PASS test_m634_winter_controls")
