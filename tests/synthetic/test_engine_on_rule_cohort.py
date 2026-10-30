"""M542 (analyses/M542_spec.md Rev 2): engineOnRule.byCohort and aggregatorSensitivity. Independent recomputation from the tracked sidecar and seasonal_drive_master.csv (no producer helper for the numbers):
cohort partition, per-cohort seconds / hours, the day-clustered intervals (seed 42, 4000 draws, days resampled within the cohort), identity with the stored cohort histograms (incl. the rpm > 6000 term),
the last-versus-mean aggregator figures and tripwires, cold exploratory flag, the M543 pointer, planted-mismatch negative controls, --check idempotence."""
import copy, json, os, sys
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
A = json.load(open("summary_arrays.json", encoding="utf-8"))
B = A["engineOnRule"]
sc = pd.read_csv("engine_on_rule_sidecar.csv")
sdm = pd.read_csv("seasonal_drive_master.csv", low_memory=False, usecols=["file", "thermal_regime"]).set_index("file")["thermal_regime"]
lab = sc["file"].map(sdm).fillna("unclassified").values
assert set(B["byCohort"]) == set(lab) and sum(v["nDrives"] for v in B["byCohort"].values()) == len(sc) == 606
cc = A["seasonalCharts"]["_meta"]["cohortCounts"]
for k, v in B["byCohort"].items():
    m = lab == k; d = sc[m]
    assert v["nDrives"] == int(m.sum()) == cc[k]
    assert v["engineOnSeconds"] == int(d["gt400"].sum()) and v["ge300Seconds"] == int(d["ge300"].sum()) and v["lowRpmBandSeconds"] == int((d["ge300"] - d["gt400"]).sum()) and v["validSeconds"] == int(d["n_valid"].sum())
    assert v["nDays"] == d["date"].nunique() and v["exploratory"] == (v["nDays"] < 10)
    days = d.groupby("date")[["gt400", "n_valid"]].sum()
    idx = np.random.default_rng(42).integers(0, len(days), (4000, len(days)))
    r = days["gt400"].values[idx].sum(1) / days["n_valid"].values[idx].sum(1)
    lo, hi = np.percentile(r, [2.5, 97.5])
    assert abs(100 * lo - v["engineOnPctOfValid"]["ci95Pct"][0]) < 1e-3 and abs(100 * hi - v["engineOnPctOfValid"]["ci95Pct"][1]) < 1e-3, k
    hist = A["seasonalCharts"]["charts"]["RpmDistribution"]["data"][k]["pooledHours"]
    H = d[["h%d" % i for i in range(13)]].values
    assert [round(float(x) / 3600, 3) for x in H.sum(0)] == hist
    assert (d["ge300"].values == H[:, 1:].sum(1) + d["gt6000"].values).all()
assert sum(v["engineOnSeconds"] for v in B["byCohort"].values()) == B["pooled"]["engineOnSeconds"] == int(sc["gt400"].sum())
assert B["byCohort"]["cold"]["exploratory"] is True and "exploratory" in B["byCohort"]["cold"]["note"] and B["byCohort"]["warm"]["exploratory"] is False
g = B["cohortGates"]
assert g["passed"] is True and g["G1CohortPartition"] is True and g["G3MeanColumnsIdenticalToM540Sidecar"] is True and g["nValidLastEqualsNValid"] is True and B["faithfulness"]["cohortGatesPassed"] is True
# aggregator sensitivity: last vs mean, from the sidecar columns
S = B["aggregatorSensitivity"]
gt, gtl, ge, gel = (sc[c].values.astype(float) for c in ("gt400", "gt400_last", "ge300", "ge300_last"))
assert abs(S["pooled"]["engineOnHoursLast"] - gtl.sum() / 3600) < 1e-4 and abs(S["pooled"]["engineOnHoursMean"] - gt.sum() / 3600) < 1e-4
assert abs(S["pooled"]["bandHoursLast"] - (gel - gtl).sum() / 3600) < 1e-4 and abs(S["pooled"]["bandRelDiffPct"] - 100 * ((gel - gtl).sum() - (ge - gt).sum()) / (ge - gt).sum()) < 1e-3
assert S["tripwires"]["pooledEngineOnOver1Pct"] == bool(abs(100 * (gtl.sum() - gt.sum()) / gt.sum()) >= 1.0)
assert set(S["byCohort"]) == set(B["byCohort"]) and set(S["byCadenceStratum"]) <= {"fast", "slow", "unlabelled"}
assert "untested" in S["definition"]
# pointers and plumbing
assert any("until M543" in x for x in B["limits"]) and not any("until M542" in x for x in B["limits"])
assert "until M543" in open("language_gate.py", encoding="utf-8").read() and "until M542" not in open("language_gate.py", encoding="utf-8").read()
sd = json.load(open("tools/stamp_dependencies.json", encoding="utf-8"))["blocks"]["engineOnRule"]
assert "analyses/M542_spec.md" in sd["inputFiles"] and "seasonal_drive_master.csv" in sd["inputFiles"]
# negative controls: a planted cohort-histogram mismatch and a planted partition error fail their gates
import engine_on_rule_block as EB
dm = pd.read_csv("drive_master.csv", low_memory=False)
A2 = copy.deepcopy(A); A2["seasonalCharts"]["charts"]["RpmDistribution"]["data"]["warm"]["pooledHours"][3] += 0.5
rg = sc["file"].map(pd.read_csv("cadence_regime.csv").set_index("file")["regime"]).fillna("unlabelled").values
assert EB.cohort_blocks(sc, dm, A2, rg)["cohortGates"]["G2"]["warm"]["binsEqualStoredCohortHistogram"] is False
A3 = copy.deepcopy(A); A3["seasonalCharts"]["_meta"]["cohortCounts"]["cold"] = 14
assert EB.cohort_blocks(sc, dm, A3, rg)["cohortGates"]["G2StoredCohortCountsEqual"] is False
bad = sc.copy(); bad.loc[0, "n_valid_last"] += 1
assert EB.cohort_blocks(bad, dm, A, rg)["cohortGates"]["nValidLastEqualsNValid"] is False
assert EB.main(["--check"]) == 0
print("OK test_engine_on_rule_cohort: partition, independent cohort figures and intervals, stored-histogram identity, aggregator sensitivity, negatives")
