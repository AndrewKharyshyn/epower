"""M307/F5 known-answer test (relaxed by M614, spec analyses/M614_spec.md Rev 1 R1/T9): the estimator gate aborts on a changed HEADLINE estimator or headline rule and passes when they are
unchanged; a change of the mixed-effects validity flags alone is reported (EST_VALIDITY_NOTES), never a stop."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
sys.argv = ["x"]
import ingest_core as ic


def arr(primary, degenerate, rule=None, valid=None):
    me = {"degenerate": degenerate}
    if valid is not None:
        me["valid"] = valid
    cs = {"primaryEstimator": primary, "mixedEffects": me}
    if rule is not None:
        cs["headlineEstimatorRule"] = rule
    return {"degradationTrends": {"cellSpread": cs, "resistanceVreg": {"primaryEstimator": "clusterRobustOLS", "mixedEffects": {"degenerate": True}}}}

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
# M614 (R1/T9): same headline estimator and rule, only the validity flag changes: reported, not a stop
R = "fixed: clusterRobustOLS (M614)"
r = ic.estimator_gate(arr("clusterRobustOLS", False, R, True), arr("clusterRobustOLS", True, R, False))
assert r == [] and len(ic.EST_VALIDITY_NOTES) == 1 and ic.EST_VALIDITY_NOTES[0]["metric"] == "cellSpread" and ic.EST_VALIDITY_NOTES[0]["mixedEffectsValid"] == [True, False], ic.EST_VALIDITY_NOTES
assert ic.estimator_gate(arr("clusterRobustOLS", False, R, True), arr("clusterRobustOLS", False, R, True)) == [] and ic.EST_VALIDITY_NOTES == []
# a change of the headline rule (None -> M614 rule, or any other change) is a stop
try:
    ic.estimator_gate(arr("clusterRobustOLS", True), arr("clusterRobustOLS", True, R))
    raise SystemExit("FAIL: a headline-rule change did not abort")
except ic.Gate as e:
    assert "headlineEstimatorRule" in str(e)
assert len(ic.estimator_gate(arr("clusterRobustOLS", True), arr("clusterRobustOLS", True, R), ack="M614 test")) == 1
# C5: every validity field is noted (valid, validity components, reCovarianceSingular), never a stop
def arr2(validity, valid, sing):
    a = arr("clusterRobustOLS", False, R, valid)
    a["degradationTrends"]["cellSpread"]["mixedEffects"].update(validity=validity, reCovarianceSingular=sing)
    return a
v1 = {"fitted": True, "converged": True, "seFinitePositive": True, "seNotBlownUp": True}
assert ic.estimator_gate(arr2(v1, True, False), arr2(dict(v1, converged=False), True, False)) == [] and ic.EST_VALIDITY_NOTES[0]["changed"] == ["validity"], ic.EST_VALIDITY_NOTES
assert ic.estimator_gate(arr2(v1, True, False), arr2(v1, True, True)) == [] and ic.EST_VALIDITY_NOTES[0]["changed"] == ["reCovarianceSingular"]
assert ic.estimator_gate(arr2(v1, True, False), arr2(v1, True, False)) == [] and ic.EST_VALIDITY_NOTES == []
print("OK estimator gate: aborts on a headline estimator or rule change, passes unchanged, reports validity-flag changes without stopping, records acknowledged change")
