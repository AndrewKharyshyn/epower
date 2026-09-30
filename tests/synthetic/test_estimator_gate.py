"""M307/F5 known-answer test: the estimator gate must abort on a flipped primary estimator (or degenerate flag) and pass when unchanged."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
sys.argv = ["x"]
import ingest_core as ic


def arr(primary, degenerate):
    return {"degradationTrends": {"cellSpread": {"primaryEstimator": primary, "mixedEffects": {"degenerate": degenerate}},
                                  "resistanceVreg": {"primaryEstimator": "clusterRobustOLS", "mixedEffects": {"degenerate": True}}}}

same = ic.estimator_gate(arr("mixedEffects", False), arr("mixedEffects", False))
assert same == [], same
try:
    ic.estimator_gate(arr("mixedEffects", False), arr("clusterRobustOLS", True))
    raise SystemExit("FAIL: flipped estimator did not abort")
except ic.Gate as e:
    assert "cellSpread" in str(e) and "resistanceVreg" not in str(e)
ch = ic.estimator_gate(arr("mixedEffects", False), arr("clusterRobustOLS", True), ack="M307 test")
assert len(ch) == 1 and ch[0]["metric"] == "cellSpread"
assert ic.estimator_gate({}, arr("mixedEffects", False)) == []          # no previous block: nothing to compare
print("OK estimator gate: aborts on flip, passes unchanged, records acknowledged change")
