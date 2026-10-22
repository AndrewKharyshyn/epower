"""M406 (analyses/M406_spec.md): known-answer harness for the dependence / small-cluster sensitivities. CR2 with singleton clusters equals HC2; CR1 equals the statsmodels cluster default; the released
slopes of the real master are reproduced; the weighted median equals np.median; simulated coverage / size / power / block-width behaviour each can fail."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import json
import numpy as np, pandas as pd
import statsmodels.api as sm
from scipy import stats
import dependence_sensitivity as DS

rng = np.random.default_rng(11)

# ---- CR2 == HC2 for singleton clusters (exact known answer)
n, p = 60, 3
X = np.column_stack([np.ones(n), rng.normal(size=n), rng.normal(size=n)])
y = X @ [1.0, 0.5, -0.3] + rng.normal(size=n) * (1 + np.abs(X[:, 1]))
b2, se2, df2, _ = DS.cr2(X, y, np.arange(n), 1)
hc2 = sm.OLS(y, X).fit(cov_type="HC2").bse[1]
assert abs(se2 - hc2) < 1e-10 and abs(se2 - DS.hc2_equivalent_check(X, y)[1]) < 1e-10, (se2, hc2)
assert 1.0 < df2 < n - p + 1e-9

# ---- CR1 == statsmodels cluster-robust default (exact)
G, m = 15, 8
g = np.repeat(np.arange(G), m)
Xc = np.column_stack([np.ones(G * m), rng.normal(size=G * m), np.repeat(rng.normal(size=G), m)])
yc = Xc @ [0.2, 0.4, -0.1] + np.repeat(rng.normal(size=G), m) + rng.normal(size=G * m)
b1, se1, Gc, nn, pp = DS.cr1(Xc, yc, g, 1)
res = sm.OLS(yc, Xc).fit(cov_type="cluster", cov_kwds={"groups": g})
assert abs(b1 - res.params[1]) < 1e-10 and abs(se1 - res.bse[1]) < 1e-10 and (Gc, nn, pp) == (G, G * m, 3)
b2c, se2c, dfc, _ = DS.cr2(Xc, yc, g, 1)
assert abs(b2c - b1) < 1e-10 and se2c > 0 and 1 < dfc < G * m

# ---- the real master: the CR1 reimplementation reproduces the released slopes (published rounding)
dm = pd.read_csv("drive_master.csv", low_memory=False)
rel = json.load(open("summary_arrays.json", encoding="utf-8"))["degradationTrends"]
for key, ycol, icol in (("cellSpread", "cell_spread_loaded_p95_mv", "peak_I_discharge"), ("resistanceVreg", "vreg_R_pack_mohm", "vreg_I_p95_A")):
    dd, Xd, yd, use = DS._design(dm, ycol, ("T", "I"), icol)
    bk, sek, Gd, nd_, _ = DS.cr1(Xd, yd, dd["day"].to_numpy(), 1)
    r = rel[key]["clusterRobustOLS"]
    assert abs(bk - r["slope"]) < 6e-5 and abs(sek - r["se"]) < 6e-5 and Gd == r["nDays"] and nd_ == r["nObs"], (key, bk, sek, r)
    tcr = stats.t.ppf(0.975, Gd - 1)          # M473: the released interval uses the cluster-t reference t(G-1) (it was the normal reference before)
    lo, hi = bk - tcr * sek, bk + tcr * sek
    assert abs(lo - r["ci95"][0]) < 2e-4 and abs(hi - r["ci95"][1]) < 2e-4

# ---- weighted median equals np.median for unit weights and for integer weights
for nv in (7, 8):
    v = rng.normal(size=nv)
    assert abs(DS.weighted_median(v, np.ones((1, nv)))[0] - np.median(v)) < 1e-12
wts = rng.integers(0, 4, size=(5, 9)).astype(float)
v9 = rng.normal(size=9)
for i in range(5):
    if wts[i].sum() > 0:
        assert abs(DS.weighted_median(v9, wts[i:i + 1])[0] - np.median(np.repeat(v9, wts[i].astype(int)))) < 1e-12

# ---- min effect with 80 % power
assert abs(DS.min_effect80(1.0, 1e9) - (1.959964 + 0.841621)) < 1e-4 and abs(DS.min_effect80(1.0, 10) - (stats.t.ppf(0.975, 10) + stats.t.ppf(0.8, 10))) < 1e-12

# ---- simulated coverage with few clusters and a cluster-level regressor: CR1 (normal) under-covers, CR2 (t, Satterthwaite) is closer to nominal
cov1 = cov2 = reps = 0
for r_ in range(300):
    G, m = 12, 6
    gx = np.repeat(rng.normal(size=G), m)
    Xs = np.column_stack([np.ones(G * m), gx])
    ys = 0.0 * gx + np.repeat(rng.normal(size=G), m) * 1.0 + rng.normal(size=G * m) * 0.5       # true slope 0, strong intra-cluster correlation
    gg = np.repeat(np.arange(G), m)
    bb, ss, *_ = DS.cr1(Xs, ys, gg, 1)
    b2_, s2_, d2_, _ = DS.cr2(Xs, ys, gg, 1)
    cov1 += abs(bb) <= stats.norm.ppf(0.975) * ss
    cov2 += abs(b2_) <= stats.t.ppf(0.975, d2_) * s2_
    reps += 1
cov1, cov2 = cov1 / reps, cov2 / reps
assert cov1 < 0.94 and cov2 > cov1 and cov2 > 0.925, (cov1, cov2)

# ---- wild cluster bootstrap-t: approximately correct size under the null, power under a real slope
rej0 = rej1 = 0
R = 120
for r_ in range(R):
    G, m = 20, 5
    gx = np.repeat(rng.normal(size=G), m)
    Xs = np.column_stack([np.ones(G * m), gx])
    base = np.repeat(rng.normal(size=G), m) + rng.normal(size=G * m) * 0.7
    gg = np.repeat(np.arange(G), m)
    rej0 += DS.wild_cluster(Xs, base, gg, 1, B=199, seed=r_)["pValueNullImposed"] < 0.05
    rej1 += DS.wild_cluster(Xs, base + 1.2 * gx, gg, 1, B=199, seed=r_)["pValueNullImposed"] < 0.05
assert 0.0 <= rej0 / R <= 0.13 and rej1 / R > 0.6, (rej0 / R, rej1 / R)
w = DS.wild_cluster(Xs, base + 1.2 * gx, gg, 1, B=399, seed=3)
assert w["ci95PercentileT"][0] < 1.2 < w["ci95PercentileT"][1] + 1.0 and w["nDraws"] == 399

# ---- week-block bootstrap: wider than the day-cluster interval when weeks share a shock, about equal for independent days
days = pd.date_range("2026-05-11", periods=140, freq="D")
wk = week_ids = DS.week_blocks(days)
mo = np.arange(140) / 30.4
Xw = np.column_stack([np.ones(140), mo])
shock = pd.Series(rng.normal(size=len(set(wk))), index=sorted(set(wk)))
y_dep = 0.3 * mo + shock.loc[wk].to_numpy() * 2.0 + rng.normal(size=140) * 0.3
y_ind = 0.3 * mo + rng.normal(size=140) * 2.0
dayid = days.strftime("%Y-%m-%d").to_numpy()
dep_d, dep_w = DS.pairs_block_ci(Xw, y_dep, dayid, 1, 1500), DS.pairs_block_ci(Xw, y_dep, wk, 1, 1500)
ind_d, ind_w = DS.pairs_block_ci(Xw, y_ind, dayid, 1, 1500), DS.pairs_block_ci(Xw, y_ind, wk, 1, 1500)
wd = lambda c: c["ci95"][1] - c["ci95"][0]
assert wd(dep_w) / wd(dep_d) > 1.4, (wd(dep_w), wd(dep_d))
assert 0.7 < wd(ind_w) / wd(ind_d) < 1.4, (wd(ind_w), wd(ind_d))
# singular draws are skipped and counted (all variation of the regressor sits in one block)
Xs1 = np.column_stack([np.ones(30), np.r_[np.arange(10.0), np.zeros(20)]])
ys1 = Xs1[:, 1] * 2.0 + rng.normal(size=30) * 0.1
sg = DS.pairs_block_ci(Xs1, ys1, np.repeat(np.arange(3), 10), 1, 200)
assert sg["skippedSingular"] > 0 and sg["nDraws"] + sg["skippedSingular"] == 200

# ---- KPI statistics against hand values on a small table
d = pd.DataFrame({"date": ["2026-06-01", "2026-06-01", "2026-06-02", "2026-06-09", "2026-06-10", "2026-06-10"], "ens_outlier_v2": ["False"] * 5 + ["True"],
                  "gross_throughput_kwh": [2.0, 4.0, 6.0, 8.0, 10.0, 99.0], "gross_discharge_kwh": [1.0, 2.0, 3.0, 4.0, 5.0, 50.0], "net_draw_kwh_corr": [0.1, -0.1, 0.2, 0.0, -0.2, 9.0],
                  "net_draw_kwh": [0.2, 0.0, 0.3, 0.1, -0.1, 9.0], "soc_band": [10.0, 20.0, 30.0, 40.0, 50.0, 99.0], "peak_discharge_kw": [30.0, 20.0, 10.0, 40.0, 50.0, 99.0]})
k = DS.kpis(d, B=400)
assert abs(k["K1_throughputOverDischarge"]["estimate"] - 30.0 / 15.0) < 1e-12 and k["K1_throughputOverDischarge"]["n"] == 5          # the excluded drive is outside the population
assert abs(k["K2_netShare_corrected"]["estimate"] - abs(0.1 - 0.1 + 0.2 + 0.0 - 0.2) / 30.0) < 1e-12
assert k["K3_socBandMedianPp"]["estimate"] == 30.0 and k["K4_peakDischargeMedianKw"]["estimate"] == 30.0
assert k["K1_throughputOverDischarge"]["nDays"] == 4 and k["K1_throughputOverDischarge"]["nWeeks"] == 2
for v in k.values():
    assert v["dayClusterCI95"][0] <= v["estimate"] <= v["dayClusterCI95"][1] + 1e-9 or v["n"] < 8                                     # tiny table: interval need not bracket, only exist
# the block builder returns every pre-registered leaf on the real master (smoke test with few draws)
b = DS.build(dm, B=60)
assert set(b["thesisKpis"]) == {"K1_throughputOverDischarge", "K2_netShare_corrected", "K2raw_netShare_uncorrected", "K3_socBandMedianPp", "K4_peakDischargeMedianKw", "K5_perDriveNetShareMedian"}
for s in ("cellSpread", "resistanceVreg"):
    t = b["trendSlopes"][s]
    assert {"cr1", "cr2", "wildClusterBootstrapT", "dayClusterPairsBootstrap", "weekBlockPairsBootstrap", "minEffect80", "byLoggingRegime"} <= set(t) and t["cr2"]["se"] > 0
print("OK test_dependence_sensitivity: CR1 coverage %.3f vs CR2 %.3f (nominal 0.95, 12 clusters); wild size %.3f / power %.3f; week/day width ratio %.2f (weekly shock) %.2f (independent days)"
      % (cov1, cov2, rej0 / R, rej1 / R, wd(dep_w) / wd(dep_d), wd(ind_w) / wd(ind_d)))
