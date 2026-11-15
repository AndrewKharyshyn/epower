"""M676 (N-07, spec analyses/M675_spec.md Rev 1.1): known-answer test of tools/changepoints.py on planted series.
Cases: planted single step (location recovered, inside the bootstrap interval), white noise (K = 0 in at least 95 % of replicates at the fixed BIC), two steps, planted trend (trend comparison reported),
minimum segment rules (8 drives and 3 days), exact DP against brute force, day structure (sign per day), V3 variance identity, determinism, stage wiring.
The 200-replicate coverage study at the real structure is offline (python tools/changepoints.py --coverage OUT.json); this test runs a small version for correctness only.
Run: python tests/synthetic/test_m676_changepoints.py"""
import itertools, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import numpy as np
import pandas as pd
import changepoints as C

rng = np.random.default_rng(7)
n = 240
dayidx = np.repeat(np.arange(60), 4)                      # 60 days x 4 drives
feas = C._feasible(dayidx)

# ---- case 1: exact DP equals brute force (K = 1, 2) on a small series ----
yb = np.concatenate([rng.normal(0, 1, 14), rng.normal(5, 1, 14), rng.normal(1, 1, 14)])
db = np.repeat(np.arange(14), 3)
fb = C._feasible(db)
rss, locs = C.partition(yb, fb, 3)
def cost(a, b): s = yb[a:b]; return float(((s - s.mean()) ** 2).sum())
best1 = min((cost(0, i) + cost(i, 42), i) for i in range(8, 35) if fb[0, i] and fb[i, 42])
assert abs(rss[1] - best1[0]) < 1e-9 and locs[1] == [best1[1]]
best2 = min((cost(0, i) + cost(i, j) + cost(j, 42), i, j) for i in range(8, 35) for j in range(i + 8, 35) if fb[0, i] and fb[i, j] and fb[j, 42])
assert abs(rss[2] - best2[0]) < 1e-9 and locs[2] == [best2[1], best2[2]]

# ---- case 2: planted step recovered; K selected = 1; location inside the interval ----
y = rng.normal(0, 1, n) + np.where(np.arange(n) >= 120, 3.0, 0.0)
rss, locs = C.partition(y, feas); bics = C.bic_table(rss, n); K = C.choose_k(bics)
assert K == 1 and abs(locs[1][0] - 120) <= 2, (K, locs[1])
bl, same = C.wild_bootstrap(y, dayidx, feas, 1, locs[1], nboot=150, seed=42)
assert np.percentile(bl[:, 0], 2.5) - 2 <= 120 <= np.percentile(bl[:, 0], 97.5) + 2 and same > 0.8
# V3 identity: RSS at K = 0 is n times the population variance
assert abs(rss[0] - n * np.var(y)) < 1e-6 * rss[0]

# ---- case 3: white noise -> K = 0 in at least 95 % of 200 replicates at the fixed BIC (no tuning) ----
k0 = 0
for r in range(200):
    yy = np.random.default_rng(1000 + r).normal(0, 1, n)
    rr, _ = C.partition(yy, feas); k0 += int(C.choose_k(C.bic_table(rr, n)) == 0)
assert k0 >= 190, "white-noise K=0 criterion failed: %d/200 (stop and revise the spec, no penalty tuning)" % k0

# ---- case 4: two steps recovered ----
y2 = rng.normal(0, 1, n) + np.where(np.arange(n) >= 80, 3.0, 0.0) - np.where(np.arange(n) >= 160, 5.0, 0.0)
rr, ll = C.partition(y2, feas); K2 = C.choose_k(C.bic_table(rr, n))
assert K2 == 2 and abs(ll[2][0] - 80) <= 2 and abs(ll[2][1] - 160) <= 2

# ---- case 5: linear trend: the trend comparison is reported (BIC of the line beats the K = 0 mean) ----
yt = 0.03 * np.arange(n) + rng.normal(0, 1, n)
tr = C._trend(yt, pd.Series(pd.date_range("2026-05-01", periods=n, freq="D")))
rt, _ = C.partition(yt, feas)
assert tr["bic"] < C.bic_table(rt, n)[0] and tr["slopePerDay"] > 0

# ---- case 6: minimum segment rules: no segment shorter than 8 drives or 3 days ----
ys = np.zeros(n); ys[100:105] = 50.0                      # 5-drive spike: cannot be its own segment
rs, ls = C.partition(ys, feas)
for k, lc in enumerate(ls):
    if lc is None: continue
    e = [0] + lc + [n]
    for a, b in zip(e[:-1], e[1:]):
        assert b - a >= C.MIN_DRIVES and dayidx[b - 1] - dayidx[a] + 1 >= C.MIN_DAYS
fe = C._feasible(np.repeat(np.arange(8), 2))              # 16 drives on 8 days: 8 drives span 4 days
assert fe[0, 8] and not fe[0, 7]
fd = C._feasible(np.repeat(np.arange(3), 8))              # 8 drives within 1 day: fails the days rule
assert not fd[0, 8] and fd[0, 24]

# ---- case 7: day structure: one Rademacher sign per calendar day ----
nd, inv = C._day_groups(dayidx)
assert nd == 60 and (np.bincount(inv) == 4).all()

# ---- case 8: determinism (seed 42) ----
a = C.wild_bootstrap(y, dayidx, feas, 1, locs[1], nboot=60, seed=42)
b = C.wild_bootstrap(y, dayidx, feas, 1, locs[1], nboot=60, seed=42)
assert (a[0] == b[0]).all() and a[1] == b[1]

# ---- case 9: control A removes a step that is pure temperature (planted), keeps a true one ----
temp = rng.normal(10, 4, n); temp[120:] += 10               # temperature steps at 120
yT = 0.5 * temp + rng.normal(0, 0.5, n)                     # no step beyond temperature
edges = [0, 120, n]
cA = C.control_A(yT, dayidx, edges, temp, 200, 42)
st = cA["steps"][0]
assert st["withoutBeta"]["ci95"][0] > 0 and st["withBeta"]["ci95"][0] < 0 < st["withBeta"]["ci95"][1]
yS = 0.5 * temp + 4.0 * (np.arange(n) >= 120) + rng.normal(0, 0.5, n)
cS = C.control_A(yS, dayidx, edges, temp, 200, 42)["steps"][0]
assert cS["withBeta"]["ci95"][0] > 2.0

# ---- case 10: control B 'not estimable' below 30 post drives; day-clustered CI ----
tb = np.full(n, 10.0)
rB = C.control_B(y, dayidx, 232, tb, 100, 42)
assert rB["status"] == "not estimable"
m_, ci = C.day_cluster_ci(np.arange(8.0), np.repeat([0, 1], 4), nboot=200, seed=1)
assert abs(m_ - 3.5) < 1e-9 and ci[0] <= 3.5 <= ci[1]

# ---- case 11: reference comparison rule: inside AND within 7 days ----
class _M:  # minimal master stand-in for compare_reference
    pass
blk = {"series": {"X9": {"status": "computed", "changePoints": [{"date": "2026-08-27", "nominal95IntervalDaysUncalibrated": [-10, 10]}, {"date": "2026-08-10", "nominal95IntervalDaysUncalibrated": [-30, 30]}]}}}
mm = pd.DataFrame({"file": ["20260511_185709.csv", "20260512_111617.csv"], "date": ["2026-05-11", "2026-11-09"]})
cmp_ = C.compare_reference(blk, mm)["series"]["X9"]["comparisons"]
upd = [r for r in cmp_ if r["reference"] == "softwareUpdate"]
assert upd[0]["coincidesAgainstUncalibratedInterval"] is True and upd[1]["insideUncalibratedInterval"] is True and upd[1]["coincidesAgainstUncalibratedInterval"] is False         # 15 days away: inside but not within 7 d

# ---- case 12: small coverage study runs and reports (no threshold here) ----
cv = C.coverage_study(reps=3, nboot=30)
assert set(cv) >= {"coverage95", "kEqualsOneRate", "flag"}

# ---- stage wiring and language rules ----
ids = [s["id"] for s in json.load(open("tools/ingest_stages.json", encoding="utf-8"))["stages"]]
assert ids.index("exposure_vector") < ids.index("change_points") < ids.index("stamp_basis")
import language_gate as G
rule = {x.rid: x for x in G.RULES}["M675-changepoint-wording"]
assert rule.hits("detects the software update") and rule.hits("a detected capacity fade") and rule.hits("the selected resistance increase") and rule.hits("a software update effect") and not rule.hits("level shift in the logged series")
rule2 = {x.rid: x for x in G.RULES}["M676-uncalibrated-interval"]
assert rule2.hits("the 95 % CI of the change point") and rule2.hits("change point localised to 3 days") and not rule2.hits("nominal 95 % interval, uncalibrated")
print("PASS test_m676_changepoints")
