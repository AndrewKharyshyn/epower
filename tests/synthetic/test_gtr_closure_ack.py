"""M466 known-answer tests for tools/gtr_closure_refresh.apply_ack: the scoped acknowledgement of the closure-refresh stops accepts EXACTLY the bound stop / escalation lists and refuses
every mismatch (wrong master, wrong per-drive hash, wrong list hash, extra or missing item, an additional stop). Pure functions on synthetic dicts; nothing is read from or written to the repo."""
import copy, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import gtr_closure_refresh as C

MD5, PD = "a" * 32, "b" * 64
delta = {"stops": [{"rule": "flag/verdict flip", "path": "/fGen/pointBelow0p5AllVariants"}, {"rule": "flag/verdict flip", "path": "/fGen/stopTriggered"}],
         "escalations": [{"rule": "ESC", "path": "/fGen/variantMax"}, {"rule": "ESC", "path": "/per100km/regenToBatt"}]}


def mk(d, **over):
    ack = {"ruling": "TEST", "driveMasterMd5": MD5, "perDriveSha256": PD, "stopsSha256": C._stops_sha(d), "stops": copy.deepcopy(d["stops"]), "escalations": copy.deepcopy(d["escalations"])}
    ack.update(over)
    return ack


p, rec = C.apply_ack(delta, mk(delta), MD5, PD)
assert p == [] and rec["stops"] == delta["stops"] and rec["escalations"] == delta["escalations"]
for bad in ({"driveMasterMd5": "0" * 32}, {"perDriveSha256": "0" * 64}, {"stopsSha256": "0" * 64}, {"ruling": ""}, {"stops": delta["stops"][:1]}, {"escalations": delta["escalations"][:1]},
            {"escalations": delta["escalations"] + [{"rule": "ESC", "path": "/interval/hi"}]}, {"stops": delta["stops"] + [{"rule": "key set", "path": "/x"}]}):
    p, rec = C.apply_ack(delta, mk(delta, **bad), MD5, PD)
    assert rec is None and p and "refused" in p[0], bad
# an additional actual stop (key set / CI exit) makes the old acknowledgement refuse: nothing but the exact bound set is ever accepted
d2 = copy.deepcopy(delta); d2["stops"].append({"rule": "estimate outside previous 95% CI", "path": "/fGen"})
p, rec = C.apply_ack(d2, mk(delta), MD5, PD)
assert rec is None and "refused" in p[0]
p, rec = C.apply_ack({"stops": [], "escalations": []}, mk({"stops": [], "escalations": []}), MD5, PD)
assert rec is None and "nothing to acknowledge" in p[0]
print("test_gtr_closure_ack: OK")
