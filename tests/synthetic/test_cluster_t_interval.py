"""M473 known-answer test: the released cluster-robust OLS interval of the degradation trends is slope +/- t(G-1) x SE (G = day clusters), equal to the dependence-sensitivity CR1 t interval; slope, SE and the equivalence
decisions are unchanged; the evidence-ledger restatement and every reader follow. Also a synthetic data set with a known answer."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import numpy as np, pandas as pd
from scipy import stats
import degradation_trends as DT

# synthetic: 30 day clusters of 4 rows, y = 2 + 0.5 months + cluster noise; the interval must use t(29), not the normal
rng = np.random.default_rng(7)
days = np.repeat(np.arange(30), 4); months = days * 0.1 + np.tile([0, 0.01, 0.02, 0.03], 30)
y = 2 + 0.5 * months + rng.normal(0, 0.3, 30)[days] + rng.normal(0, 0.05, 120)
d = pd.DataFrame(dict(y=y, months=months, day=[f"d{k}" for k in days], T=rng.normal(25, 3, 120)))
r = DT._cluster_ols(d, covars=("T",))
t = stats.t.ppf(0.975, 29)
assert abs(r["ci95"][0] - (r["slope"] - t * r["se"])) < 6e-4 and abs(r["ci95"][1] - (r["slope"] + t * r["se"])) < 6e-4, r
nrm = stats.norm.ppf(0.975)
assert (r["ci95"][1] - r["ci95"][0]) > 2 * nrm * r["se"] + 1e-3 and r["ciReference"] == "t(df=29)", "wider than the normal interval"

# live payload
A = json.load(open("summary_arrays.json", encoding="utf-8")); D = A["degradationTrends"]; S = A["dependenceSensitivity"]["trendSlopes"]
for k in ("cellSpread", "resistanceVreg"):
    c = D[k]["clusterRobustOLS"]; G = c["nDays"]
    tt = stats.t.ppf(0.975, G - 1)
    assert c["ciReference"] == f"t(df={G - 1})"
    assert abs(c["ci95"][0] - (c["slope"] - tt * c["se"])) < 6e-4 and abs(c["ci95"][1] - (c["slope"] + tt * c["se"])) < 6e-4, k
    cr1 = S[k]["cr1"]
    assert abs(c["ci95"][0] - cr1["ci95T_Gminus1"][0]) < 1.5e-4 and abs(c["ci95"][1] - cr1["ci95T_Gminus1"][1]) < 1.5e-4, k       # the released interval equals the CR1 t interval
    assert cr1["ci95NormalAsReleased"][0] > c["ci95"][0] if c["ci95"][0] > 0 else cr1["ci95NormalAsReleased"][0] > c["ci95"][0]
    assert "referenceNote" in cr1 and "M473" in cr1["referenceNote"]
assert D["cellSpread"]["clusterRobustOLS"]["ci95"][0] > 0 and D["resistanceVreg"]["clusterRobustOLS"]["ci95"][0] < 0 < D["resistanceVreg"]["clusterRobustOLS"]["ci95"][1]      # no sign conclusion changes
assert D["cellSpread"]["releasedEquivalence"]["equivalent"] is False and D["cellSpread"]["releasedEquivalence"]["refDist"].startswith("t(df=")
led = A["evidenceLedger"]["rows"][4]["checks"][0]
assert led["ci95"] == D["resistanceVreg"]["clusterRobustOLS"]["ci95"], "the ledger restatement follows the released interval"
print("OK test_cluster_t_interval (cellSpread %s, resistance %s)" % (D["cellSpread"]["clusterRobustOLS"]["ci95"], D["resistanceVreg"]["clusterRobustOLS"]["ci95"]))
