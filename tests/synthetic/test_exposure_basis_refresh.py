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
# mutation: a master without its last 20 rows
cut = dm.iloc[:-20].copy()
b2 = R.build(cut, P)
assert b2["legacy"]["meta"]["gtcSum"] == round(float(cut["gtc"].sum()), 1) < old["legacy"]["meta"]["gtcSum"]
# (the populations are read from drive_master.csv on disk by exposure_splice.populations(): in the ingestion the master on disk is the corpus; the legacy values below follow the dm passed in)
assert b2["legacy"]["cycleByType"] != old["legacy"]["cycleByType"] or b2["legacy"]["metricConvention"] != old["legacy"]["metricConvention"]
# splice: only the block and its stamp
new, changed, bad = R.splice(P, blk, "0" * 32)
assert bad == [] and set(changed) <= set(R.ALLOWED) and changed == ["/exposureBasis", "/_artifactStamps/exposureBasis"]      # the block differs from the M415 one only by its provenance text
_n2, changed_again, _ = R.splice(new, blk, "0" * 32)
assert changed_again == ["/_artifactStamps/exposureBasis"], "a second refresh on the same corpus changes only the stamp (idempotent)"
assert {k: v for k, v in new.items() if k not in ("_artifactStamps", "exposureBasis")} == {k: v for k, v in P.items() if k not in ("_artifactStamps", "exposureBasis")}
assert new["_artifactStamps"]["exposureBasis"]["computationStatus"] == "computed" and "carriedForward" not in new["_artifactStamps"]["exposureBasis"]
_, changed2, bad2 = R.splice(P, b2, "0" * 32)
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
