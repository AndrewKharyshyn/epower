"""M377a known-answer tests for tools/leaf_guard.py (analyses/M377_spec.md Rev 2 P6, control c): an UNEXPECTED loss fails, a declared and
data-conditioned loss passes, a loss whose condition does not hold fails, a leaf that became a container (None -> list) is not a loss, and the
rule file is well formed (no wildcard beyond {i} and {key}). Synthetic arrays only; nothing is read from the repo payload except the rule file."""
import copy, json, os, subprocess, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import leaf_guard as LG

RULES = [
    {"id": "stamp", "rationale": "r", "milestone": "T", "pathTemplate": "_artifactStamps/{key}/note", "condition": "stamp_hash_changed"},
    {"id": "err", "rationale": "r", "milestone": "T", "pathTemplate": "m/error", "condition": "sibling_present", "sibling": "coef"},
    {"id": "blk", "rationale": "r", "milestone": "T", "pathTemplate": "c/{key}/att", "condition": "parent_null_in_current", "matchPrefix": True},
]
PREV = {"a": {"x": 1, "y": [1, 2]}, "ci": None, "m": {"error": "boom", "coef": None},
        "_artifactStamps": {"k1": {"corpusHash": "h1", "note": "n"}, "k2": {"corpusHash": "h1", "note": "n"}},
        "c": {"w": {"att": {"km": 2.5, "bins": [{"n": 3}]}}}}

# identical -> pass
r = LG.guard(PREV, copy.deepcopy(PREV), RULES)
assert r["nLost"] == 0 and r["nUnexpected"] == 0, r

# unexpected loss fails and is named
cur = copy.deepcopy(PREV); del cur["a"]["x"]
r = LG.guard(PREV, cur, RULES)
assert r["nUnexpected"] == 1 and r["unexpected"] == ["a/x"], r

# a whole removed block lists every leaf
cur = copy.deepcopy(PREV); del cur["a"]
r = LG.guard(PREV, cur, RULES)
assert sorted(r["unexpected"]) == ["a/x", "a/y/0", "a/y/1"], r

# None -> container is not a loss (the old leaf path still exists as a node)
cur = copy.deepcopy(PREV); cur["ci"] = [0.1, 0.2]
assert LG.guard(PREV, cur, RULES)["nLost"] == 0

# declared loss passes only when its data condition holds
cur = copy.deepcopy(PREV); del cur["_artifactStamps"]["k1"]["note"]; cur["_artifactStamps"]["k1"]["corpusHash"] = "h2"
r = LG.guard(PREV, cur, RULES)
assert r["nUnexpected"] == 0 and r["expectedByRule"] == {"stamp": 1}, r
cur = copy.deepcopy(PREV); del cur["_artifactStamps"]["k2"]["note"]          # hash unchanged: the note must not vanish
r = LG.guard(PREV, cur, RULES)
assert r["nUnexpected"] == 1 and r["unexpected"] == ["_artifactStamps/k2/note"], r

# sibling_present: error may vanish only when coefficients exist
cur = copy.deepcopy(PREV); del cur["m"]["error"]
assert LG.guard(PREV, cur, RULES)["nUnexpected"] == 1
cur["m"]["coef"] = {"b": 1}
assert LG.guard(PREV, cur, RULES)["nUnexpected"] == 0

# prefix rule: children may vanish only when the block itself is null in the current arrays
cur = copy.deepcopy(PREV); cur["c"]["w"]["att"] = None
r = LG.guard(PREV, cur, RULES)
assert r["nUnexpected"] == 0 and r["expectedByRule"] == {"blk": 2}, r
cur = copy.deepcopy(PREV); cur["c"]["w"]["att"] = {"km": 2.5}                # block alive, bins lost
r = LG.guard(PREV, cur, RULES)
assert r["unexpected"] == ["c/w/att/bins/0/n"], r

# rule validation: wildcards and unknown conditions are refused
for bad in ({"pathTemplate": "a/*"}, {"pathTemplate": "a/{any}"}, {"condition": "nope"}, {"rationale": ""}):
    rule = dict(RULES[0], **bad)
    try:
        LG.check_rules([rule])
    except SystemExit:
        continue
    raise AssertionError("bad rule accepted: %r" % bad)

# the committed rule file is well formed and every rule carries id / rationale / milestone
rules = json.load(open(os.path.join(ROOT, "analyses", "leaf_guard_rules.json"), encoding="utf-8"))
LG.check_rules(rules)
assert len({x["id"] for x in rules}) == len(rules)

# CLI: exit code 1 on an unexpected loss, 0 otherwise
import tempfile
with tempfile.TemporaryDirectory() as td:
    p, c, rp = (os.path.join(td, n) for n in ("prev.json", "cur.json", "rules.json"))
    json.dump(PREV, open(p, "w")); json.dump(RULES, open(rp, "w"))
    bad = copy.deepcopy(PREV); del bad["a"]["x"]
    json.dump(bad, open(c, "w"))
    run = lambda: subprocess.run([sys.executable, os.path.join(ROOT, "tools", "leaf_guard.py"), "--previous", p, "--current", c, "--rules", rp], capture_output=True, text=True).returncode
    assert run() == 1
    json.dump(PREV, open(c, "w"))
    assert run() == 0
print("test_leaf_guard: OK")
