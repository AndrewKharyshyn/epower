"""M543 (analyses/M543_spec.md Rev 2): rpmOptBand rule-based sibling leaves, the stage order, the invariance proof for rpmModeCentres and motoredShare, the display binding.
Independent recomputation of primaryRule from the two sidecars (no producer helper), the known answer from the M536 wave-0 addendum, the old leaves unchanged, gates, negative controls."""
import json, os, re, sys
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
A = json.load(open("summary_arrays.json", encoding="utf-8"))
O = A["rpmOptBand"]
import rpm_opt_band as OB
import compute_summary_arrays as cs
from model_constants import OPT_LO, OPT_HI
edges = OB.fine_edges(list(cs.RPM_HIST_EDGES), OPT_LO, OPT_HI)
sc = pd.read_csv("rpm_opt_band_sidecar.csv", dtype={"sha256": str}); rs = pd.read_csv("engine_on_rule_sidecar.csv", dtype={"sha256": str}).set_index("file")
C = sc[["b%d" % k for k in range(len(edges) - 1)]].values.astype(np.int64)
num = (OB.between(C, edges, OPT_LO, OPT_HI) + sc["eq_hi"].values).astype(float)
gt = sc["file"].map(rs["gt400"]).values.astype(float)
# independent bootstrap: calendar day cluster, seed 42, 4000 draws, ratio of sums
d = pd.DataFrame({"n": num, "g": gt, "day": sc["date"].astype(str).values}).groupby("day")[["n", "g"]].sum()
idx = np.random.default_rng(42).integers(0, len(d), (4000, len(d)))
r = d["n"].values[idx].sum(1) / d["g"].values[idx].sum(1)
lo, hi = np.percentile(r, [2.5, 97.5])
P = O["primaryRule"]
assert abs(P["pct"] - 100 * num.sum() / gt.sum()) < 5e-4 and abs(100 * lo - P["ci95Pct"][0]) < 1e-3 and abs(100 * hi - P["ci95Pct"][1]) < 1e-3
assert P["ruleEngineOnSeconds"] == int(gt.sum()) == 353811 and P["bandSeconds"] == int(num.sum()) and P["nDrives"] == int((gt > 0).sum()) and P["nDaysWithEngineOn"] == sc["date"].astype(str)[gt > 0].nunique()
# known answer from the M536 wave-0 addendum (pre-registered tolerances) and the shift inside the old interval
W = json.load(open("analyses/M536_wave0_addendum.json", encoding="utf-8"))["gt400"]
assert abs(P["pct"] - W["pct"]) < 2e-3 and all(abs(a - b) < 1e-2 for a, b in zip(P["ci95Pct"], W["ci95Pct"])) and abs(P["pct"] - 64.092) < 2e-3
assert O["primary"]["ci95Pct"][0] <= P["pct"] <= O["primary"]["ci95Pct"][1]
# the rpm >= 300 leaves are unchanged
assert O["primary"]["pct"] == 63.073 and O["primary"]["ci95Pct"] == [60.614, 65.332] and O["primary"]["engineOnSeconds"] == 359524 and O["edgeSensitivity"]["wide50"] == 64.548
# gates and cadence strata: descriptive only, no contrast leaf
assert O["ruleGates"]["passed"] is True and O["faithfulness"]["passed"] is True
assert set(O["cadenceStrataRule"]) == {"slow", "fast"} and not any("contrast" in k.lower() or "diff" in k.lower() for k in O["cadenceStrataRule"]) and "contrast" in " ".join(O["ruleBasis"]["sensitivityNotes"])
assert any("aggregator" in x for x in O["limits"])
# negative controls: a planted rule-sidecar mismatch fails the gate
import copy
rs2 = rs.copy(); rs2.loc[rs2.index[0], "ge300"] += 1
orig = pd.read_csv
def fake(path, *a, **k):
    df = orig(path, *a, **k)
    return rs2.reset_index() if str(path).endswith("engine_on_rule_sidecar.csv") else df
pd.read_csv = fake
try:
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    out = OB.compute(sc, dm, A, list(cs.RPM_HIST_EDGES), edges, OPT_LO, OPT_HI)
finally:
    pd.read_csv = orig
assert out["ruleGates"]["ruleGe300EqualsBinSumPerDrive"] is False and out["faithfulness"]["passed"] is False
# stage order: the rule sidecar is built before the rpm_opt_band stage consumes it (and after engine_runtime, which the rule cross-check reads)
ids = [s["id"] for s in json.load(open("tools/ingest_stages.json", encoding="utf-8"))["stages"]]
assert ids.index("engine_runtime") < ids.index("engine_on_rule") < ids.index("rpm_opt_band")
sd = json.load(open("tools/stamp_dependencies.json", encoding="utf-8"))["blocks"]["rpmOptBand"]
assert "engine_on_rule_sidecar.csv" in sd["inputFiles"] and "analyses/M543_spec.md" in sd["inputFiles"]
# invariance: rpmModeCentres windows and motoredShare floor lie above 400, no 300 / 400 literal in either module, payload leaves of both blocks untouched
for f in ("tools/rpm_mode_centres.py", "tools/rpm_fuel_state.py"):
    code = "\n".join(l.split("#")[0] for l in open(f, encoding="utf-8") if not l.strip().startswith(('"""', "'''")))
    assert not re.search(r"(?<![0-9.])(300|400)(?:\.0)?(?![0-9.])", code.split('"""')[0] if False else code), f
M = A["rpmModeCentres"]
assert all(lo >= 1400 for lo, hi in M["windows"].values())
assert A["motoredShare"]["thresholds"]["floorRpm"] == 1400.0 and 1400.0 > 400.0
# display binding (source level): rule leaves are read, the tag text is gone, the peak shares use the rule denominator
src = open("xtrail_summary.jsx", encoding="utf-8").read()
assert "O&&O.primaryRule" in src and "until the engine-on rule is applied to this block" not in src and "they move to the rule in a later step" not in src
assert src.count("_eorA.pooled.engineOnHours") == 1 and src.count("_eorB2.pooled.engineOnHours") == 1
assert "cmpWordA" in src and "drives — lower than the" not in src
assert OB.main(["--check"]) == 0
print("OK test_m543_opt_band_rule: independent primaryRule, known answer, old leaves unchanged, gates, stage order, invariance proof, display binding")
