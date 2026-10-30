"""M540 (analyses/M540_spec.md Rev 2): the engineOnRule block. Independent recomputation of the payload leaves from the tracked sidecars (no producer helper for the numbers): the engine-on / band / >= 300 seconds equal the phase-1
evidence sidecar drive by drive (one-time gate on the 606 overlapping drives), the pre-registered expected values, the identity with the stored rpmDistribution, the closed-band complement, the exact-400 evidence, the integration
cross-check sign, the stage / stamp / restamp plumbing, a planted-mismatch negative control, --check idempotence."""
import json, os, sys
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
A = json.load(open("summary_arrays.json", encoding="utf-8"))
B = A["engineOnRule"]
sc = pd.read_csv("engine_on_rule_sidecar.csv"); ev = pd.read_csv("engine_on_evidence_sidecar.csv"); dm = pd.read_csv("drive_master.csv", low_memory=False)
# one-time gate: the production sidecar equals the phase-1 evidence sidecar drive by drive (ge300, gt400, valid seconds)
m = sc.merge(ev, on="file")
assert len(m) == len(sc) == len(ev) == 606
assert (m["ge300"] == m["g_ge300"]).all() and (m["gt400"] == m["g_gt400"]).all() and (m["n_valid"] == m["grid_valid_s"]).all()
p = B["pooled"]
assert p["ge300Seconds"] == int(sc["ge300"].sum()) == 359524 and p["engineOnSeconds"] == int(sc["gt400"].sum()) == 353811 and p["validSeconds"] == int(sc["n_valid"].sum())
assert p["lowRpmBandSeconds"] == p["ge300Seconds"] - p["engineOnSeconds"] == 5713                                         # closed band = the exact complement of > 400 inside >= 300
assert abs(p["engineOnHours"] - 98.2808) < 1e-3 and abs(p["ge300Hours"] - 99.8678) < 1e-3 and abs(p["lowRpmBandHours"] - 1.5870) < 1.5e-3
assert p["nDrives"] == 606 and p["nDays"] == 121
assert abs(p["engineOnPctOfValid"]["pct"] - 42.6369) < 2e-3 and abs(p["engineOnPctOfValid"]["ci95Pct"][0] - 38.7513) < 0.02 and abs(p["engineOnPctOfValid"]["ci95Pct"][1] - 46.1924) < 0.02
assert abs(p["lowRpmBandPctOfGe300"]["pct"] - 1.589) < 2e-3 and abs(p["lowRpmBandPctOfGe300"]["ci95Pct"][0] - 1.4583) < 0.02 and abs(p["lowRpmBandPctOfGe300"]["ci95Pct"][1] - 1.7457) < 0.02
# independent day-clustered interval of the engine-on share (seed 42, 4000 draws, whole days)
dd = sc.groupby("date")[["gt400", "n_valid"]].sum()
idx = np.random.default_rng(42).integers(0, len(dd), (4000, len(dd)))
r = dd["gt400"].values[idx].sum(1) / dd["n_valid"].values[idx].sum(1)
lo, hi = np.percentile(r, [2.5, 97.5])
assert abs(100 * lo - p["engineOnPctOfValid"]["ci95Pct"][0]) < 1e-3 and abs(100 * hi - p["engineOnPctOfValid"]["ci95Pct"][1]) < 1e-3
# identity with the stored rpmDistribution (13 integer bins, rounded hours equal exactly)
H = sc[["h%d" % k for k in range(13)]].values
assert [round(float(v) / 3600, 3) for v in H.sum(0)] == A["rpmDistribution"]["pooledHours"]
assert (sc["ge300"].values == H[:, 1:].sum(1) + sc["gt6000"].values).all()
cls = sc["file"].map(dm.set_index("file")["drive_type"]).values
for k, v in B["byClass"].items():
    assert [round(float(x) / 3600, 3) for x in H[cls == k].sum(0)] == A["rpmDistribution"]["byClass"][k]["hours"]
    assert v["engineOnSeconds"] == int(sc[cls == k]["gt400"].sum()) and v["nDays"] >= 10
assert sum(v["engineOnSeconds"] for v in B["byClass"].values()) + B.get("unclassified", {}).get("engineOnSeconds", 0) == p["engineOnSeconds"]
assert B["unclassified"]["nDrives"] == int((~np.isin(cls, list(B["byClass"]))).sum())
# exact-400 evidence and the cross-check sign
be = B["boundaryEvidence"]
assert be["exact400Seconds"] == int(sc["eq400"].sum()) == 53 and be["nDrivesWithExact400"] == int((sc["eq400"] > 0).sum()) and be["maxExact400SecondsPerDrive"] == int(sc["eq400"].max())
ic = B["integrationCrossCheck"]
assert ic["integrationTermHours"] > 0 and abs(ic["integrationTermHours"] - (p["engineOnHours"] - A["engineRuntime"]["totals"]["supportedOnHours"])) < 2e-4 and ic["flag"] == "within"
assert B["faithfulness"]["passed"] is True and B["faithfulness"]["secondsRpmGt6000"] == int(sc["gt6000"].sum())
# rule block names and separate names
assert B["rule"]["thresholdRpm"] == 400.0 and B["rule"]["boundary"] == "gt" and B["rule"]["bandClosedRpm"] == [300.0, 400.0] and B["displayed"] is True
# plumbing
assert "engine_on_rule" in [s["id"] for s in json.load(open("tools/ingest_stages.json", encoding="utf-8"))["stages"]]
sd = json.load(open("tools/stamp_dependencies.json", encoding="utf-8"))["blocks"]["engineOnRule"]
assert sd["readsRaw"] is True and sd["producer"] == "tools/engine_on_rule_block.py" and "analyses/M540_spec.md" in sd["inputFiles"]
assert "engineOnRule" in open("tools/restamp_ingest.py", encoding="utf-8").read()
st = A["_artifactStamps"]["engineOnRule"]
assert st["computedAt"] <= st["includedInReleaseAt"] and st["corpusHash"] == B["provenance"]["masterMd5"]
# negative control: a planted bin mismatch fails the faithfulness gate
import engine_on_rule_block as EB
bad = sc.copy(); bad.loc[0, "h3"] += 7
assert EB.compute(bad, dm, A)["faithfulness"]["passed"] is False
bad2 = sc.copy(); bad2.loc[0, "ge300"] += 1
assert EB.compute(bad2, dm, A)["faithfulness"]["perDriveIdentityGe300"] is False
assert EB.main(["--check"]) == 0
print("OK test_engine_on_rule_block: independent recomputation, identity gates, expected values, plumbing, negatives")
