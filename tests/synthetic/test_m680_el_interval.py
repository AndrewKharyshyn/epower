"""M680 (N-04 follow-up, spec analyses/M679_spec.md Rev 1.1): known-answer test of the interval constructions C1 (cell-by-side stratified day bootstrap), C2 (stratified delete-one-day jackknife) and C3 (Dirichlet day weights).
Cases: the jackknife equals the textbook variance of a difference of two means of day means; C1 and C3 never lose a cell; determinism; planted-shift coverage on a small design; the selection rule (higher minimum coverage over S2-S4, tie to C2, none);
V1 the new estimate equals the path_a estimate; wording rule. Run: python tests/synthetic/test_m680_el_interval.py"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import numpy as np
import pandas as pd
import early_late_contrast as C

rng = np.random.default_rng(11)

# ---- case 1: one cell, equal drives per day: jackknife variance = s_e^2/G_e + s_l^2/G_l of the day means ----
Ge, Gl, n = 12, 9, 4
Se = np.array([[rng.normal(5, 1) * n] for _ in range(Ge)]); Ne = np.full((Ge, 1), float(n))
Sl = np.array([[rng.normal(6, 1.5) * n] for _ in range(Gl)]); Nl = np.full((Gl, 1), float(n))
w = np.array([1.0])
r = C.c2_interval(Se, Ne, Sl, Nl, w)
me, ml = (Se / Ne)[:, 0], (Sl / Nl)[:, 0]
exp_var = me.var(ddof=1) / Ge + ml.var(ddof=1) / Gl
assert abs(r["se"] ** 2 - exp_var) < 1e-9 and r["df"] == Ge + Gl - 2 and abs(r["estimate"] - (ml.mean() - me.mean())) < 1e-9

# ---- case 2: C1 and C3 never lose a cell (cells with only 2 days per side) and are deterministic ----
Se = np.array([[1.0, 2.0], [3.0, 0.0], [0.0, 5.0], [2.0, 2.0]]); Ne = np.array([[1.0, 1.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
Sl = np.array([[2.0, 3.0], [4.0, 0.0], [0.0, 6.0]]); Nl = np.array([[1.0, 1.0], [1.0, 0.0], [0.0, 1.0]])
w = np.array([0.5, 0.5])
d1 = C.c1_draws(Se, Ne, Sl, Nl, w, 500, np.random.default_rng(1)); d3 = C.c3_draws(Se, Ne, Sl, Nl, w, 500, np.random.default_rng(1))
assert np.isfinite(d1).all() and np.isfinite(d3).all() and len(d1) == 500
assert np.array_equal(d1, C.c1_draws(Se, Ne, Sl, Nl, w, 500, np.random.default_rng(1)))

# ---- case 3: planted shift: coverage over replicates on a small design with day effects ----
def sim(delta, sdd, seed):
    rg = np.random.default_rng(seed)
    cells = 3; days_e, days_l = 14, 12; per = 3
    Ne = np.full((days_e, cells), float(per)); Nl = np.full((days_l, cells), float(per))
    mu = np.array([5.0, 7.0, 9.0])
    Se = (mu + rg.normal(0, sdd, (days_e, 1))) * per + rg.normal(0, 1, (days_e, cells)) * np.sqrt(per)
    Sl = (mu + delta + rg.normal(0, sdd, (days_l, 1))) * per + rg.normal(0, 1, (days_l, cells)) * np.sqrt(per)
    return Se, Ne, Sl, Nl
w3 = np.full(3, 1 / 3)
cov = {c: 0 for c in C.CONSTRUCTIONS}; R = 200
for k in range(R):
    Se_, Ne_, Sl_, Nl_ = sim(1.0, 1.0, 100 + k)
    iv = C.all_intervals(Se_, Ne_, Sl_, Nl_, w3, 300, np.random.default_rng(k))
    for c in C.CONSTRUCTIONS:
        a, b = iv[c]["ci95"]; cov[c] += int(a <= 1.0 <= b)
assert cov["C2"] / R > 0.90 and cov["C3"] / R > 0.85, cov                                    # C1 is allowed to be lower (independence across cells ignores the shared day effect)

# ---- case 4: selection rule ----
def mk(cs):
    return {s: {c: {"coverage95": cs[c][i]} for c in cs} for i, s in enumerate(("S1", "S2", "S3", "S4", "S5"))}
good = {"C1": [0.95] * 5, "C2": [0.95] * 5, "C3": [0.93] * 5}
assert C.select_construction(mk(good)) == "C2"                                              # tie -> C2
better = {"C1": [0.96] * 5, "C2": [0.94] * 5, "C3": [0.93] * 5}
assert C.select_construction(mk(better)) == "C1"                                            # higher minimum over S2-S4
bad = {"C1": [0.80] * 5, "C2": [0.85] * 5, "C3": [0.89] * 5}
assert C.select_construction(mk(bad)) is None
wide = {"C1": [0.995, 0.95, 0.95, 0.95, 0.95], "C2": [0.95] * 5, "C3": [0.95] * 5}
assert C.select_construction(mk(wide)) == "C2"                                              # C1 too wide in S1 -> not admissible

# ---- case 5: V1 the table estimate equals the path_a estimate on a frame ----
def frame(n, day0, ndays, shift=0.0):
    days = rng.integers(0, ndays, n)
    dd = pd.to_datetime(day0) + pd.to_timedelta(days, unit="D")
    return pd.DataFrame({"file": ["f%d" % i for i in range(n)], "date": dd, "day": dd.strftime("%Y-%m-%d"), "T": rng.normal(15, 4, n), "I": rng.normal(100, 20, n),
                         "S": rng.normal(60, 4, n), "dist": rng.uniform(1, 40, n), "reg": ["slow"] * n, "Y2": 10 + shift + rng.normal(0, 1, n)})
e, l = frame(300, "2026-05-15", 40), frame(300, "2026-09-11", 40, 2.0)
pa = C.path_a(e, l, "Y2", nboot=100); pa.pop("_cellsMask")
st = C.setup(e, l, "Y2")
Se_, Sl_ = C.day_tables(st, st["ey"]["Y2"].values, st["ly"]["Y2"].values)
assert abs(C.est_from(Se_, st["Ne"], Sl_, st["Nl"], st["w"]) - pa["estimate"]) < 1e-9
assert C.setup(e, l, "Y2", slow_only=True) is not None

# ---- case 6: the REML variance-component fit recovers planted components (and a zero day effect) ----
rg = np.random.default_rng(5)
def vc_for(sd_day, sd_e, G=120, per=6):
    day = rg.normal(0, sd_day, G)
    ce = np.repeat(np.arange(G), per); y = day[ce] + rg.normal(0, sd_e, G * per)
    st = {"ce": np.zeros(G * per, dtype=int), "cl": np.full(1, -1), "ie": ce, "il": np.zeros(1, dtype=int), "nde": G, "ndl": 1}
    return C.var_components(st, y, np.zeros(1), nboot=40)
v = vc_for(2.0, 3.0)
assert abs(v["sdDay"] - 2.0) < 0.5 and abs(v["sdResid"] - 3.0) < 0.3 and not v["dayEffectIncludesZero"]
v0 = vc_for(0.0, 3.0)
assert v0["sdDay"] < 0.6 and v0["sdDayUsedInScenarios"] >= v0["sdDay"]

# ---- case 7: C2w equals C2 on a design with equal late counts per cell and day (weights never change), and differs when late counts vary ----
Se = np.array([[5.0 * 2], [6.0 * 2], [5.5 * 2], [4.5 * 2]]); Ne = np.full((4, 1), 2.0)
Sl = np.array([[8.0 * 2], [9.0 * 2], [7.0 * 2]]); Nl = np.full((3, 1), 2.0)
a = C.c2_interval(Se, Ne, Sl, Nl, np.array([1.0])); b = C.c2w_interval(Se, Ne, Sl, Nl, np.array([1.0]))
assert abs(a["se"] - b["se"]) < 1e-12                                                       # one cell: the weight is 1 whatever is deleted
Se2 = np.array([[10.0, 4.0], [12.0, 6.0], [11.0, 5.0], [9.0, 3.0]]); Ne2 = np.full((4, 2), 2.0)
Sl2 = np.array([[16.0, 2.0], [18.0, 12.0], [14.0, 8.0]]); Nl2 = np.array([[2.0, 1.0], [2.0, 3.0], [2.0, 2.0]])
w2 = Nl2.sum(0) / Nl2.sum()
a2 = C.c2_interval(Se2, Ne2, Sl2, Nl2, w2); b2 = C.c2w_interval(Se2, Ne2, Sl2, Nl2, w2)
assert a2["estimate"] == b2["estimate"] and a2["se"] != b2["se"] and b2["df"] == a2["df"]

# ---- wording rule ----
import language_gate as G
rule = {x.rid: x for x in G.RULES}["M679-interval-wording"]
assert rule.hits("a valid interval for the matched difference") and not rule.hits("interval with simulated coverage")
print("PASS test_m680_el_interval")
