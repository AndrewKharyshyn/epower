"""Stamp policy gap (found at the M714 hand-over): the on-demand payload blocks WITHOUT an ingestion stage must have a `carried` entry in tools/restamp_ingest.STAMP_POLICY, otherwise the first ingestion with new drives
stops at restamp_ingest ("stale stamp(s) without a policy entry"). If a stage is added for one of them later this test fails: the policy entry must then be reconsidered (regen vs carried)."""
import copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import restamp_ingest as R

ON_DEMAND = {"reverseInference": ["tools/reverse_mask.py"], "engineStartHazard": ["tools/start_hazard.py"], "stepResistance": ["tools/step_events.py", "tools/step_resistance.py"],
             "oemCrossCheckC1": ["tools/oem_crosscheck.py", "tools/rpm_window_cache.py"], "oemCrossCheckC2": ["tools/oem_crosscheck.py", "tools/rpm_window_cache.py"]}
A = json.load(open("summary_arrays.json", encoding="utf-8"))
stages = json.load(open("tools/ingest_stages.json", encoding="utf-8"))["stages"]
cmds = " ".join(" ".join(s["cmd"]) for s in stages)
for k, prod in ON_DEMAND.items():
    assert k in A and k in A["_artifactStamps"], k
    assert k in R.STAMP_POLICY and R.STAMP_POLICY[k][0] == "carried", ("on-demand block without a carried policy entry", k)
    for f in prod:
        assert os.path.exists(f), f
        assert os.path.basename(f) not in cmds, ("a stage now runs the producer of %s: reconsider its policy" % k, f)

# M720: exposureScenarios HAS a stage now (scenario_refresh): its carried entry stays as the restamp-time fallback (restamp_ingest runs before the stage; the stage splice then writes a computed stamp over it)
assert R.STAMP_POLICY["exposureScenarios"][0] == "carried" and "scenario_refresh.py" in cmds
A_ES = "exposureScenarios"

# the stale-stamp plan: every on-demand stamp that turns stale is planned as carried at a basis; a stale key without a policy still stops the stage
stamps = {k: dict(copy.deepcopy(A["_artifactStamps"][k]), basisNDrives=665) for k in list(ON_DEMAND) + [A_ES]}
plan = R.plan(stamps, "0" * 32, 700)
assert sorted(p[0] for p in plan) == sorted(list(ON_DEMAND) + [A_ES]) and all(p[1] == "carried" and p[3] == 665 for p in plan)
bad = dict(stamps, noPolicyBlockX={"corpusHash": "old"})
try:
    R.plan(bad, "0" * 32, 700)
    raise AssertionError("a stale stamp without a policy entry must stop the stage")
except ValueError as ex:
    assert "noPolicyBlockX" in str(ex)
# up-to-date stamps are not stale
assert R.plan(stamps, stamps["oemCrossCheckC1"]["corpusHash"], 665) == []
print("test_stamp_policy_ondemand: ok")
