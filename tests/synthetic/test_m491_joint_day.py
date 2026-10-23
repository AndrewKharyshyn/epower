"""M491 known-answer tests (spec analyses/M491_spec.md Rev 2, KAT1-KAT3 and the drop rule): the joint calendar-day bootstrap of a difference of ratios of sums against the former independent-cohort design.
KAT1 all dates shared with an identical multiplicative day shock (>= 30 days, >= 60 drives per cohort): joint width / independent width < 0.5. KAT2 disjoint dates (30 days per cohort): the mean width ratio over 20 seeds
is within 0.9-1.1 (joint) and 0.95-1.05 (stratified, which reduces to the independent design). KAT3 opposite day shocks (negative covariance): the joint interval is wider (mean ratio over 20 seeds > 1.1).
Draws with an empty cohort are dropped, counted and reproducible. The module is also exercised on its generator contract (same seed, same draws)."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import joint_day_bootstrap as J

N_DRAWS = 4000
width = lambda x: float(np.quantile(x, 0.975) - np.quantile(x, 0.025))


def days(dates, ratio, shock, den):
    return pd.DataFrame({"num": ratio * shock * den / 100.0, "den": den}, index=pd.Index(dates, name="day"))


def widths(a, b, seed, which=("joint", "indep", "strat")):
    out = {}
    if "joint" in which:
        out["joint"] = width(J.joint_difference(a, b, np.random.default_rng(seed), N_DRAWS)[0])
    if "indep" in which:
        out["indep"] = width(J.independent_difference(a, b, np.random.default_rng(seed + 10_000), N_DRAWS))
    if "strat" in which:
        out["strat"] = width(J.stratified_difference(a, b, np.random.default_rng(seed + 20_000), N_DRAWS)[0])
    return out


rg = np.random.default_rng(1)
# KAT1: 40 shared dates, identical multiplicative day shock, 2 drives per date and cohort (80 drives per cohort)
dates = ["d%02d" % i for i in range(40)]
shock = rg.lognormal(0, 0.25, 40)
den = rg.uniform(15, 40, 40)
A = days(dates, 10.0, shock, den); B = days(dates, 11.0, shock, den)
w = np.mean([widths(A, B, s)["joint"] / widths(A, B, s)["indep"] for s in range(20)])
assert w < 0.5, ("KAT1 joint/independent width ratio", w)

# KAT2: disjoint dates, 30 days per cohort, independent shocks
da, db = ["a%02d" % i for i in range(30)], ["b%02d" % i for i in range(30)]
r_joint, r_strat = [], []
for s in range(20):
    r = np.random.default_rng(100 + s)
    A2 = days(da, 10.0, r.lognormal(0, 0.25, 30), r.uniform(15, 40, 30)); B2 = days(db, 11.0, r.lognormal(0, 0.25, 30), r.uniform(15, 40, 30))
    ww = widths(A2, B2, s)
    r_joint.append(ww["joint"] / ww["indep"]); r_strat.append(ww["strat"] / ww["indep"])
assert 0.9 <= np.mean(r_joint) <= 1.1, ("KAT2 joint ratio", np.mean(r_joint))
assert 0.95 <= np.mean(r_strat) <= 1.05, ("KAT2 stratified ratio", np.mean(r_strat))

# KAT3: opposite day shocks on 40 shared dates (negative covariance of the two ratios): the independent design is too narrow
r_neg = []
for s in range(20):
    r = np.random.default_rng(200 + s)
    sh = r.lognormal(0, 0.25, 40); dn = r.uniform(15, 40, 40)
    A3 = days(dates, 10.0, sh, dn); B3 = days(dates, 10.0, 2.0 - np.clip(sh, 0, 1.9), dn)
    ww = widths(A3, B3, s, which=("joint", "indep"))
    r_neg.append(ww["joint"] / ww["indep"])
assert np.mean(r_neg) > 1.1, ("KAT3 negative covariance joint/independent", np.mean(r_neg))

# drop rule: one cohort has a single date, so many draws contain no date of that cohort: dropped, counted, reproducible
A4 = days(["x00"], 10.0, np.array([1.0]), np.array([20.0]))
B4 = days(["x%02d" % i for i in range(1, 30)], 11.0, np.ones(29), np.full(29, 20.0))
d1 = J.joint_difference(A4, B4, np.random.default_rng(5), N_DRAWS)
d2 = J.joint_difference(A4, B4, np.random.default_rng(5), N_DRAWS)
assert d1[3] > 0 and d1[3] == d2[3] and len(d1[0]) == N_DRAWS - d1[3] and np.array_equal(d1[0], d2[0]) and d1[4] == 30 and d1[5] == 0
# a single shared date: every kept draw has the same difference
A5 = days(["z"], 10.0, np.array([1.0]), np.array([20.0])); B5 = days(["z"], 12.0, np.array([1.0]), np.array([20.0]))
dd = J.joint_difference(A5, B5, np.random.default_rng(1), 100)
assert dd[3] == 0 and np.allclose(dd[0], 2.0) and dd[5] == 1
# strata sizes: shared, a-only and b-only dates are counted
A6 = days(["s1", "s2", "a1"], 10.0, np.ones(3), np.full(3, 10.0)); B6 = days(["s1", "s2", "b1", "b2"], 10.0, np.ones(4), np.full(4, 10.0))
r6 = J.joint_difference(A6, B6, np.random.default_rng(1), 50)
assert r6[4] == 5 and r6[5] == 2
print("test_m491_joint_day OK (KAT1 %.3f, KAT2 %.3f / %.3f, KAT3 %.3f, dropped %d of %d)" % (w, np.mean(r_joint), np.mean(r_strat), np.mean(r_neg), d1[3], N_DRAWS))
