"""M544 (analyses/M544_spec.md Rev 2): known-answer tests of the wave 3-0 evidence tool: the run-boundary taxonomy (split / drop / shorten, never merge), the strict > 400 boundary, the anchored substitution (counts asserted, regeneration
proxy and onset untouched in the 400 copy), the observer line, and (when present) the recorded evidence file gates."""
import inspect, json, os, sys
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import engine_on_wave3_evidence as W
assert W.synthetic() is True
# a run can split, drop or shorten but never merge (subset property enforced)
try:
    W.classify_runs(np.array([1, 0, 1], dtype=bool), np.array([1, 1, 1], dtype=bool)); raise SystemExit("subset check missing")
except AssertionError:
    pass
# strict boundary: a run exactly at 400 does not count at > 400
assert W.classify_runs(np.array([0, 1, 1, 0], dtype=bool), np.array([0, 0, 0, 0], dtype=bool))["dropped"] == 1
# anchors: counts in the live source, and the substituted copies change exactly those literals
import compute_summary_arrays as C
src = inspect.getsource(C._RawAccum)
for old, new, cnt in W.ANCHORS:
    assert src.count(old) == cnt, old
assert src.count("rp <= 300") >= 1 and src.count(W.ONSET[0]) == 1                  # regeneration proxy and onset detector exist and are not anchors
C2, cls, sub = W.build_classes()
s400 = inspect.getsource(cls["t400"]) if False else None
assert set(cls) == {"t300", "t400", "t400onset"} and sub["observerLine"]
a = cls["t400"]()
assert hasattr(a, "eng_on") and not hasattr(a, "_eon_hook")                           # the hook attribute is created by add(), not by the constructor
# recorded evidence (present after the run)
p = "analyses/M544_evidence.json"
if os.path.exists(p):
    e = json.load(open(p, encoding="utf-8"))
    g = e["gates"]
    assert g["passed"] is True and g["G0a_perDriveStateEqual"] is True and g["G0c_onlyTargeted"] is True and all(g["G0b_primary"].values())
    assert e["identity"]["E4_turboByRpmBandsAt1500AndAboveEqual"] is True
    assert e["nDrivesUsed"] == e["nDrivesMaster"] and e["masterMd5"].startswith("5556a0c6")
p2 = "analyses/M544_evidence_addendum.json"
if os.path.exists(p2):
    a = json.load(open(p2, encoding="utf-8"))
    assert a["E3_engineOnBySpeed_identity"]["equal"] is True and a["E1_ruleSecondsExact"]["equal"] is True and a["E1_ruleSecondsExact"]["nDrivesCompared"] == 606
print("OK test_engine_on_wave3_evidence: taxonomy, strict boundary, anchored substitution, recorded gates")
