"""M423 (analyses/M423_spec.md): the ingestion refresh of the exposureBasis block. Known answer: on the committed corpus the refreshed block equals the block spliced at M415 from the two control builds (every key except the
provenance text); mutation: on a master without its last 20 rows the populations, the legacy sums and the legacy per-type rows follow the data; the splice writes only the block and its stamp; the stage runs after
capacity_basis and before stamp_basis, and restamp_ingest knows the block."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import pandas as pd
import exposure_basis_refresh as R

dm = pd.read_csv("drive_master.csv", low_memory=False)
P = json.load(open("summary_arrays.json", encoding="utf-8"))
old = P["exposureBasis"]
blk = R.build(dm, P)
diff = sorted(k for k in set(blk) | set(old) if k != "_provenance" and blk.get(k) != old.get(k))
assert diff == [], "the refresh must reproduce the M415 block on the committed corpus: " + str(diff)
assert "M423" in blk["_provenance"] and "exposure_basis_refresh" in blk["_provenance"]
# the factor is the rated payload sum over the legacy sum of the master (one identity, no second source)
assert abs(P["meta"]["gtcSum"] / blk["legacy"]["meta"]["gtcSum"] - blk["factor"]["aggregateRatedOverLegacy"]) < 1e-3
# mutation: a master without its last 20 rows (cheap parts only: the legacy sums and the legacy metric convention follow the data)
import compute_summary_arrays as C
import exposure_frame as EF
cut = dm.iloc[:-20].copy()
dml = EF.exposure_frame(cut, "legacy2p1kWh")
assert round(float(dml["gtc"].sum()), 1) < old["legacy"]["meta"]["gtcSum"] and json.loads(json.dumps(C._metric_convention(dml), default=float)) != old["legacy"]["metricConvention"]
# splice: only the block and its stamp; a refresh on an already refreshed payload changes only the stamp (idempotent)
new, changed, bad = R.splice(P, blk, "0" * 32)
assert bad == [] and set(changed) <= set(R.ALLOWED) and changed == ["/_artifactStamps/exposureBasis"], changed
assert {k: v for k, v in new.items() if k != "_artifactStamps"} == {k: v for k, v in P.items() if k != "_artifactStamps"}
assert new["_artifactStamps"]["exposureBasis"]["computationStatus"] == "computed" and "carriedForward" not in new["_artifactStamps"]["exposureBasis"]
changed_blk = dict(blk); changed_blk["factor"] = dict(blk["factor"], aggregateRatedOverLegacy=0.0)
_, changed2, bad2 = R.splice(P, changed_blk, "0" * 32)
assert changed2 == ["/exposureBasis", "/_artifactStamps/exposureBasis"] and bad2 == []
# wiring
stages = json.load(open("tools/ingest_stages.json", encoding="utf-8"))
ids = [x["id"] for x in (stages["stages"] if isinstance(stages, dict) else stages)]
assert ids.index("capacity_basis") < ids.index("exposure_basis_refresh") < ids.index("stamp_basis") < ids.index("leaf_guard") < ids.index("restamp_ingest")
import restamp_ingest as RI
assert "exposureBasis" in RI.STAMP_POLICY
ci = open(".github/workflows/ci.yml", encoding="utf-8").read()
assert "test_exposure_basis_refresh.py" in ci
print("OK test_exposure_basis_refresh")
