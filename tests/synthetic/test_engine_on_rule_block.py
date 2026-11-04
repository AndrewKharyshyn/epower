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
sc6 = sc[sc["file"].isin(ev["file"])]      # M575: the evidence corpus (the first 606 drives); the production sidecar grows with every ingestion
assert len(m) == len(sc6) == len(ev) == 606 and len(sc) == len(dm)
assert (m["ge300"] == m["g_ge300"]).all() and (m["gt400"] == m["g_gt400"]).all() and (m["n_valid"] == m["grid_valid_s"]).all()
p = B["pooled"]
assert p["ge300Seconds"] == int(sc["ge300"].sum()) and p["engineOnSeconds"] == int(sc["gt400"].sum()) and p["validSeconds"] == int(sc["n_valid"].sum())
assert int(sc6["ge300"].sum()) == 359524 and int(sc6["gt400"].sum()) == 353811      # known answers of the evidence corpus
assert p["lowRpmBandSeconds"] == p["ge300Seconds"] - p["engineOnSeconds"] and int(sc6["ge300"].sum()) - int(sc6["gt400"].sum()) == 5713      # closed band = the exact complement of > 400 inside >= 300
assert abs(sc6["gt400"].sum() / 3600 - 98.2808) < 1e-3 and abs(sc6["ge300"].sum() / 3600 - 99.8678) < 1e-3 and abs((sc6["ge300"].sum() - sc6["gt400"].sum()) / 3600 - 1.5870) < 1.5e-3
assert abs(p["engineOnHours"] - sc["gt400"].sum() / 3600) < 1e-3 and abs(p["ge300Hours"] - sc["ge300"].sum() / 3600) < 1e-3
assert p["nDrives"] == len(sc) and p["nDays"] == sc["date"].nunique()
def _boot(df, col, den):      # day-clustered percentile bootstrap, seed 42, 4000 draws
    g = df.groupby("date")[[col, den]].sum(); ix = np.random.default_rng(42).integers(0, len(g), (4000, len(g)))
    q = 100 * g[col].values[ix].sum(1) / g[den].values[ix].sum(1)
    return 100 * g[col].sum() / g[den].sum(), np.percentile(q, 2.5), np.percentile(q, 97.5)
e6 = _boot(sc6, "gt400", "n_valid"); b6 = _boot(sc6.assign(low=sc6["ge300"] - sc6["gt400"]), "low", "ge300")      # known answers of the evidence corpus (606 drives)
assert abs(e6[0] - 42.6369) < 2e-3 and abs(e6[1] - 38.7513) < 0.02 and abs(e6[2] - 46.1924) < 0.02
assert abs(b6[0] - 1.589) < 2e-3 and abs(b6[1] - 1.4583) < 0.02 and abs(b6[2] - 1.7457) < 0.02
ef = _boot(sc, "gt400", "n_valid"); bf = _boot(sc.assign(low=sc["ge300"] - sc["gt400"]), "low", "ge300")      # the payload (all drives)
assert abs(p["engineOnPctOfValid"]["pct"] - ef[0]) < 2e-3 and abs(p["engineOnPctOfValid"]["ci95Pct"][0] - ef[1]) < 0.02 and abs(p["engineOnPctOfValid"]["ci95Pct"][1] - ef[2]) < 0.02
assert abs(p["lowRpmBandPctOfGe300"]["pct"] - bf[0]) < 2e-3 and abs(p["lowRpmBandPctOfGe300"]["ci95Pct"][0] - bf[1]) < 0.02 and abs(p["lowRpmBandPctOfGe300"]["ci95Pct"][1] - bf[2]) < 0.02
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
assert be["exact400Seconds"] == int(sc["eq400"].sum()) and int(sc6["eq400"].sum()) == 53 and be["nDrivesWithExact400"] == int((sc["eq400"] > 0).sum()) and be["maxExact400SecondsPerDrive"] == int(sc["eq400"].max())
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
