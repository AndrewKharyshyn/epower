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

# field_changed: a source key may vanish only from an entry whose rerunMilestone changed
FR = [{"id": "src", "rationale": "r", "milestone": "T", "pathTemplate": "rb/{i}/source/R", "condition": "field_changed", "entryDepth": 2, "field": "rerun"}]
P2 = {"rb": [{"rerun": "M375", "source": {"O": "o", "R": "r"}}]}
C2 = {"rb": [{"rerun": "M376", "source": {"O": "o2"}}]}
r = LG.guard(P2, C2, FR)
assert r["nUnexpected"] == 0 and r["expectedByRule"] == {"src": 1}, r
C3 = {"rb": [{"rerun": "M375", "source": {"O": "o"}}]}                   # same milestone: the loss is unexpected
assert LG.guard(P2, C3, FR)["nUnexpected"] == 1

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

# ---- M426: the three data-conditioned conditions, tested with the COMMITTED rules (analyses/leaf_guard_rules.json) on synthetic arrays ----
CR = {x["id"]: x for x in json.load(open(os.path.join(ROOT, "analyses", "leaf_guard_rules.json"), encoding="utf-8"))}
def sel(*ids): return [CR[i] for i in ids]
def coh_prev():
    return {"seasonalCharts": {"_meta": {"cohortSuppressedBelowMinSupport": {"minDrivesForStatistics": 10, "nObserved": {"cold": 7}}},
                               "charts": {"EnergyIntensity": {"coverage": {"cold": {"n_drives": 0, "status": "no_observations"}}}}},
            "comparisonCube": {"_meta": {"minSupport": {"drives": 10, "days": 3}}},
            "cohortMeta": {"cold": {"nObserved": 7, "suppressed": "below_min_support", "inferenceAvailable": False, "eligibleForCohortView": 0, "nDaysObserved": 3}},
            "fuelStates": {"groups": {"cohort cold_insufficient": {"nTrips": 7, "litres": 1.0}}}}
def coh_cur():
    return {"seasonalCharts": {"_meta": {"cohortSuppressedBelowMinSupport": {"minDrivesForStatistics": 10, "nObserved": {}}},
                               "charts": {"EnergyIntensity": {"coverage": {"cold": {"n_drives": 12, "km": 143.6}}}}},
            "comparisonCube": {"_meta": {"minSupport": {"drives": 10, "days": 3}}},
            "cohortMeta": {"cold": {"inferenceAvailable": True, "eligibleForCohortView": 12, "nDaysObserved": 5}},
            "fuelStates": {"groups": {"cohort cold": {"nTrips": 11, "litres": 9.7}}}}
CRULES = sel("cohort-support-crossed-nObserved", "cohort-support-crossed-suppressed", "cohort-support-crossed-suppressed-list", "cohort-support-crossed-coverage-EnergyIntensity", "cohort-support-crossed-fuelStates-group")
r = LG.guard(coh_prev(), coh_cur(), CRULES)
assert r["nLost"] == 6 and r["nUnexpected"] == 0, r                                                  # the crossing is expected (incl. the renamed group's leaves)
def cmut(f, which="cur"):
    p, c = coh_prev(), coh_cur(); f(c if which == "cur" else p); return LG.guard(p, c, CRULES)["nUnexpected"]
assert cmut(lambda c: c["cohortMeta"]["cold"].__setitem__("eligibleForCohortView", 9)) > 0            # n < min drives
assert cmut(lambda c: c["cohortMeta"]["cold"].__setitem__("nDaysObserved", 2)) > 0                    # days < min days
assert cmut(lambda c: c["cohortMeta"]["cold"].__setitem__("inferenceAvailable", False)) > 0           # not available now
assert cmut(lambda c: c["comparisonCube"]["_meta"]["minSupport"].__setitem__("drives", 8)) > 0        # the threshold itself changed
assert cmut(lambda c: c["comparisonCube"]["_meta"]["minSupport"].__setitem__("days", 2)) > 0
assert cmut(lambda c: c["seasonalCharts"]["_meta"]["cohortSuppressedBelowMinSupport"].__setitem__("minDrivesForStatistics", 8)) > 0
assert cmut(lambda c: c["seasonalCharts"]["_meta"]["cohortSuppressedBelowMinSupport"]["nObserved"].__setitem__("cold", 12)) > 0   # still listed as suppressed
assert cmut(lambda c: c["fuelStates"]["groups"].pop("cohort cold")) > 0                               # the renamed group is missing
assert cmut(lambda c: c["seasonalCharts"]["charts"]["EnergyIntensity"]["coverage"]["cold"].__setitem__("n_drives", 9)) > 0
assert cmut(lambda p: p["cohortMeta"]["cold"].__setitem__("inferenceAvailable", True), "prev") > 0   # it was already available before: not a crossing
p_, c_ = coh_cur(), coh_prev()                                                                       # reverse direction: available -> suppressed
assert LG.guard(p_, c_, CRULES)["nUnexpected"] > 0

PH = sel("placeholder-row-observed-CycleByType")
def ph_prev(): return {"seasonalCharts": {"charts": {"CycleByType": {"data": {"shoulder": [{"label": "Urban", "lo": 9.0, "classKey": "urban"}, {"label": "Mixed Highway", "classKey": "mixed_highway", "n": 0, "status": "not_observed", "reason": "none"}]}}}}}
def ph_cur(): return {"seasonalCharts": {"charts": {"CycleByType": {"data": {"shoulder": [{"label": "Urban", "lo": 9.0, "classKey": "urban"}, {"label": "Mixed Highway", "lo": 8.3, "hi": 8.3, "avg": 8.3, "med": 8.3, "classKey": "mixed_highway"}]}}}}}
r = LG.guard(ph_prev(), ph_cur(), PH)
assert r["nLost"] == 3 and r["nUnexpected"] == 0, r
def pmut(f):
    c = ph_cur(); f(c["seasonalCharts"]["charts"]["CycleByType"]["data"]["shoulder"]); return LG.guard(ph_prev(), c, PH)["nUnexpected"]
assert pmut(lambda rows: rows[1].__setitem__("status", "not_observed")) > 0                           # still a placeholder
assert pmut(lambda rows: rows[1].__setitem__("classKey", "highway")) > 0                              # a different class took the slot
assert pmut(lambda rows: rows.__setitem__(1, {"label": "Mixed Highway", "classKey": "mixed_highway"})) > 0   # no observed value at all
assert pmut(lambda rows: rows[1].update({"n": 0})) > 0                                                # a zero count is not observed
c = ph_cur(); del c["seasonalCharts"]["charts"]["CycleByType"]["data"]["shoulder"][1]
assert LG.guard(ph_prev(), c, PH)["nUnexpected"] > 0                                                   # the row vanished
pp = ph_prev(); pp["seasonalCharts"]["charts"]["CycleByType"]["data"]["shoulder"][0]["lo"] = 1.0       # a REAL (non-placeholder) leaf may never vanish
cc = ph_cur(); del cc["seasonalCharts"]["charts"]["CycleByType"]["data"]["shoulder"][0]["lo"]
assert LG.guard(pp, cc, PH)["unexpected"] == ["seasonalCharts/charts/CycleByType/data/shoulder/0/lo"]

CL = sel("cellspread-rows-moved-to-complement")
def cs_prev(): return {"serialDependence": {"trendSlopes": {"cellSpread": {"rowsRule": {"classification": "procedure-dependent", "rowsIncludingZero": ["a", "b", "c"], "rowsExcludingZero": ["d"]}}}}}
def cs_cur(): return {"serialDependence": {"trendSlopes": {"cellSpread": {"rowsRule": {"classification": "procedure-dependent", "rowsIncludingZero": ["a"], "rowsExcludingZero": ["d", "b", "c"]}}}}}
def rr(c): return c["serialDependence"]["trendSlopes"]["cellSpread"]["rowsRule"]
r = LG.guard(cs_prev(), cs_cur(), CL)
assert r["nLost"] == 2 and r["nUnexpected"] == 0, r
c = cs_cur(); rr(c)["rowsIncludingZero"] = ["c", "a"]; rr(c)["rowsExcludingZero"] = ["d", "b"]
assert LG.guard(cs_prev(), c, CL)["nUnexpected"] == 0                                                  # reordered rows: still the same names
c = cs_cur(); rr(c)["classification"] = "stable"
assert LG.guard(cs_prev(), c, CL)["nUnexpected"] == 2                                                  # classification flip is refused
c = cs_cur(); rr(c)["rowsExcludingZero"] = ["d"]
assert LG.guard(cs_prev(), c, CL)["nUnexpected"] == 2                                                  # names dropped, not moved
c = cs_cur(); rr(c)["rowsExcludingZero"] = ["d", "b", "c", "z"]
assert LG.guard(cs_prev(), c, CL)["nUnexpected"] == 2                                                  # union changed
c = cs_cur(); rr(c)["rowsIncludingZero"] = ["a", "b", "c"]
assert LG.guard(cs_prev(), c, CL)["nUnexpected"] == 0                                                  # nothing lost
print("test_leaf_guard M426 conditions: OK")

# the renamed fuelStates group must carry a counterpart of every lost leaf; rule parameters are validated
assert cmut(lambda c: c["fuelStates"]["groups"]["cohort cold"].pop("litres")) == 1
for bad in ({"condition": "moved_to_complement_list", "listField": ""}, {"condition": "placeholder_row_observed", "allowedLeaves": []}, {"condition": "sibling_present", "sibling": None}):
    try:
        LG.check_rules([dict(RULES[0], **bad)])
    except SystemExit:
        continue
    raise AssertionError("rule with a missing parameter accepted: %r" % bad)
print("test_leaf_guard M426 review fixes: OK")
