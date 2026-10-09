"""M389 known-answer test: the restamp stage plans exactly the stale stamps, stops on a stale key without a policy or a carried key without a basis, and is idempotent."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
import restamp_ingest as R

LIVE, OLD = "b" * 32, "a" * 32
st = {"seasonalCharts": {"corpusHash": OLD}, "generatorTractionRecon": {"corpusHash": OLD},
      "masterRefitAudit": {"corpusHash": OLD, "basisNDrives": 489}, "cohortMeta": {"corpusHash": LIVE}, "meta": "not a stamp"}
p = R.plan(st, LIVE, 554)
assert [t[0] for t in p] == ["generatorTractionRecon", "masterRefitAudit", "seasonalCharts"], p            # fresh stamp (cohortMeta) and non-dict untouched
kinds = {t[0]: t[1] for t in p}
assert kinds == {"generatorTractionRecon": "gtr", "masterRefitAudit": "carried", "seasonalCharts": "regen"}
assert [t for t in p if t[0] == "masterRefitAudit"][0][3] == 489                                            # basis read from the stamp, never typed
assert "554-drive" in [t for t in p if t[0] == "seasonalCharts"][0][2]
try:
    R.plan({"newBlock": {"corpusHash": OLD}}, LIVE, 554)
    raise SystemExit("FAIL: stale key without a policy did not stop")
except ValueError as e:
    assert "newBlock" in str(e)
try:
    R.plan({"masterRefitAudit": {"corpusHash": OLD}}, LIVE, 554)
    raise SystemExit("FAIL: carried key without a basis did not stop")
except ValueError as e:
    assert "masterRefitAudit" in str(e)
assert R.plan({k: dict(v, corpusHash=LIVE) if isinstance(v, dict) else v for k, v in st.items()}, LIVE, 554) == []   # idempotent: nothing stale
print("OK restamp_ingest: plans stale stamps, stops on unknown key / missing basis, idempotent")
