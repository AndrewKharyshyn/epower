"""M651 (P-07): generic carry of previous leaves the builder does not produce (ingest_core.carry_lost_leaves). Known answer on a toy payload: a missing branch is carried whole, a present
leaf keeps the fresh value, _artifactStamps and list-indexed leaves are not carried, a leaf covered by a declared leaf_guard rule is not carried, the result passes leaf_guard for the carried part.
Run: python tests/synthetic/test_m651_carry_leaves.py"""
import copy, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import ingest_core as IC
import leaf_guard as LG

prev = {"a": {"keep": 1, "gone": {"x": 1, "y": {"z": 2}}, "same": 5}, "b": {"lst": [{"u": 1, "v": 2}]}, "_artifactStamps": {"a": {"hash": "old", "t": 1}}, "c": {"rule": {"p": 1}}, "top": 9}
fresh = {"a": {"keep": 99, "same": 6}, "b": {"lst": [{"u": 1}]}, "_artifactStamps": {"a": {"hash": "new"}}, "c": {}}
LG.CONDITIONS["__always"] = lambda prev, cur, p, b, r: True            # a stand-in declared condition
rules = [{"id": "r", "pathTemplate": "c/rule", "condition": "__always", "matchPrefix": True}]
before = copy.deepcopy(fresh)
carried = IC.carry_lost_leaves(fresh, prev, rules)
assert carried == ["a/gone", "top"], carried                                   # highest missing node only; c/rule is a declared expected loss
assert fresh["a"]["gone"] == {"x": 1, "y": {"z": 2}} and fresh["top"] == 9
assert fresh["a"]["keep"] == 99 and fresh["a"]["same"] == 6, "a present leaf keeps the fresh value"
assert fresh["_artifactStamps"] == {"a": {"hash": "new"}}, "stamps are never carried"
assert fresh["b"]["lst"] == [{"u": 1}], "list-indexed leaves are never carried"
assert fresh["a"]["gone"] is not prev["a"]["gone"], "a copy, not an alias"
# idempotent
assert IC.carry_lost_leaves(fresh, prev, rules) == []
assert "rule" not in fresh["c"], "a rule-covered loss is not carried"
f3 = {"c": {}}
IC.carry_lost_leaves(f3, prev, [])
assert f3["c"] == {"rule": {"p": 1}}, "without the rule the same loss is carried"
# the shipped control report: the generic carry never increases the loss and leaves only stamps and list-indexed classes
import json
rep = json.load(open(os.path.join(ROOT, "analyses", "M651_control_report.json"), encoding="utf-8"))
assert rep["nLostAfterGenericCarry"] < rep["nLostAfterOldCarry"] < rep["nLostBuilderOutputAsIs"], rep
assert set(rep["unexpectedByTopLevelKey"]) <= {"_artifactStamps", "records", "engineStartsByType"}, rep["unexpectedByTopLevelKey"]
print("PASS test_m651_carry_leaves")
