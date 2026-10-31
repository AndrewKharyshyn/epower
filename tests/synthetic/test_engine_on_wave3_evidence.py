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
# anchors: the evidence tool re-creates _RawAccum from its source with literal substitutions. Since M545 G0 the literals are gone (the stored gate is the named constant ENGINE_ON_STORED_RPM, called through
# tools/engine_on_blocks.py), so the tool is ARCHIVAL (its recorded outputs are the M544 evidence); the registry anchors must be absent from the live source and the constant must be 300
import compute_summary_arrays as C
src = inspect.getsource(C._RawAccum)
assert C.ENGINE_ON_STORED_RPM == 300
for old, new, cnt in W.ANCHORS:
    assert src.count(old) == 0, ("literal gate reappeared", old)
assert src.count("rp <= 300") >= 1 and src.count(W.ONSET[0]) == 1                  # regeneration proxy and onset detector exist and are not anchors
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
