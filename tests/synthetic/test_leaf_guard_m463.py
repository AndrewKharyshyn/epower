"""M463 known-answer tests for the five leaf_guard conditions added for the M119-v2 refit ingestion (analyses/M463_leaf_guard_addendum.md): each fires on the declared case
and FAILS (loss stays unexpected) on the negative cases. Synthetic arrays only; the rule file is checked for well-formedness."""
import copy, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import leaf_guard as LG

T = dict(prevMode="carriedForward", curMode="fresh", prevCorpus=489, curCorpus=606)


def v2(mode, n, frozen, **kw):
    return dict({"recomputeMode": mode, "corpusSizeAtRecompute": n, "frozenBasis": frozen}, **kw)


def unexpected(prev, cur, rules):
    return LG.guard(prev, cur, rules)["unexpected"]


# ---- refit_recompute_transition ----
R_REFIT = [dict(id="r", rationale="r", milestone="T", pathTemplate="socHysteresisV2/grid", condition="refit_recompute_transition", matchPrefix=True, **T),
           dict(id="s", rationale="r", milestone="T", pathTemplate="socHysteresisV2/staleWaiver", condition="refit_recompute_transition", **T),
           dict(id="k", rationale="r", milestone="T", pathTemplate="socHysteresisV2/stab", condition="refit_recompute_transition", matchPrefix=True, anchorDepth=1, **T)]
PREV = {"socHysteresisV2": v2("carriedForward", 489, True, grid=[[1, 2], [3, 4]], staleWaiver="w", stab=[{"name": "a"}])}
CUR = {"socHysteresisV2": v2("fresh", 606, False, grid=[[1, 2]])}
assert unexpected(PREV, CUR, R_REFIT) == [], unexpected(PREV, CUR, R_REFIT)                      # shrink inside the exact transition passes
c = copy.deepcopy(CUR); c["socHysteresisV2"]["corpusSizeAtRecompute"] = 607
assert unexpected(PREV, c, R_REFIT)                                                              # other corpus size fails
c = copy.deepcopy(CUR); c["socHysteresisV2"]["recomputeMode"] = "carriedForward"
assert unexpected(PREV, c, R_REFIT)                                                              # not a fresh recompute fails
p = copy.deepcopy(PREV); p["socHysteresisV2"]["recomputeMode"] = "fresh"
assert unexpected(p, CUR, R_REFIT)                                                               # previous already fresh fails (one-shot)
c = copy.deepcopy(CUR); c["socHysteresisV2"]["frozenBasis"] = True
assert unexpected(PREV, c, R_REFIT)                                                              # frozen basis fails
c = copy.deepcopy(CUR); del c["socHysteresisV2"]["grid"]
assert unexpected(PREV, c, R_REFIT)                                                              # deleted block (not a shrink) fails
c = copy.deepcopy(CUR); c["other"] = 1; p = copy.deepcopy(PREV); p["other"] = {"x": 1}; p["other"]["x"] = 1; del c["other"]
assert unexpected(p, c, R_REFIT) == ["other/x"]                                                  # a path outside the templates fails

# ---- f03_list_cleared_by_refit (manifest check) ----
man = json.load(open(os.path.join(ROOT, "raw_manifest.json"), encoding="utf-8"))["files"]
name = next(r["raw_name"] for r in man if r.get("raw_name") and os.path.exists(os.path.join(ROOT, "raw", r["raw_name"].replace("_", " ", 1))))
R_F03 = [dict(id="f", rationale="r", milestone="T", pathTemplate="socHysteresisV2/f03/{i}", condition="f03_list_cleared_by_refit", **T)]
P = {"socHysteresisV2": v2("carriedForward", 489, True, f03=[name])}
C = {"socHysteresisV2": v2("fresh", 606, False, f03=[])}
assert unexpected(P, C, R_F03) == [], unexpected(P, C, R_F03)                                    # emptied and the file matches the manifest sha256
C2 = {"socHysteresisV2": v2("fresh", 606, False, f03=[name])}
assert unexpected(P, C2, R_F03) == ["socHysteresisV2/f03/0"] or LG.guard(P, C2, R_F03)["nLost"] == 0   # still listed: not a loss (the leaf exists)
P3 = {"socHysteresisV2": v2("carriedForward", 489, True, f03=["no_such_file.csv"])}
assert unexpected(P3, C, R_F03) == ["socHysteresisV2/f03/0"]                                     # unknown file fails
C4 = {"socHysteresisV2": v2("fresh", 606, False, f03=None)}
assert unexpected(P, C4, R_F03)                                                                  # list deleted/None (not an empty list) fails

# ---- fit_attempts_shortened_converged ----
R_FIT = [dict(id="a", rationale="r", milestone="T", pathTemplate="m/attempts/{i}/{key}", condition="fit_attempts_shortened_converged")]
P = {"m": {"attempts": [{"method": "nm", "converged": False, "error": "x"}, {"method": "lbfgs", "converged": True, "error": None}]}}
C = {"m": {"attempts": [{"method": "lbfgs", "converged": True, "error": None}]}}
assert unexpected(P, C, R_FIT) == [], unexpected(P, C, R_FIT)
C = {"m": {"attempts": [{"method": "lbfgs", "converged": False, "error": "boom"}]}}
assert unexpected(P, C, R_FIT)                                                                   # final attempt not converged fails
C = {"m": {"attempts": []}}
assert unexpected(P, C, R_FIT)                                                                   # empty list fails
C = {"m": {}}
assert unexpected(P, C, R_FIT)                                                                   # deleted list fails

# ---- list_shortened_nonempty ----
R_LST = [dict(id="l", rationale="r", milestone="T", pathTemplate="h/{key}/seq/{i}", condition="list_shortened_nonempty")]
P = {"h": {"cold": {"seq": ["a", "b", "c", "d"]}}}
assert unexpected(P, {"h": {"cold": {"seq": ["a", "b", "c"]}}}, R_LST) == []
assert unexpected(P, {"h": {"cold": {"seq": []}}}, R_LST)                                        # emptied fails
assert unexpected(P, {"h": {}}, R_LST)                                                           # deleted fails

# ---- two_part_switch ----
R_TP = [dict(id="t", rationale="r", milestone="T", pathTemplate="c/{key}/{key}", condition="two_part_switch", matchPrefix=True, threshold=0.25)]
tp = {"zeroShare": 0.29, "twoPart": {"pPositive": {"n": 3}}}
bm = {"zeroShare": 0.24, "bootMedian": {"bootMedian": 1.0}}
assert unexpected({"c": {"a": {"x": tp}}}, {"c": {"a": {"x": bm}}}, R_TP) == []                 # twoPart -> bootMedian when zeroShare falls below the threshold
assert unexpected({"c": {"a": {"x": bm}}}, {"c": {"a": {"x": tp}}}, R_TP) == []                 # bootMedian -> twoPart when it rises to the threshold
assert unexpected({"c": {"a": {"x": tp}}}, {"c": {"a": {"x": dict(bm, zeroShare=0.27)}}}, R_TP)   # zeroShare still above the threshold: a loss fails
assert unexpected({"c": {"a": {"x": tp}}}, {"c": {"a": {"x": {"zeroShare": 0.24}}}}, R_TP)       # no bootMedian counterpart fails
assert unexpected({"c": {"a": {"x": tp}}}, {"c": {"a": {"x": dict(bm, twoPart={})}}}, R_TP)       # both structures present is not a switch

# ---- rule file ----
rules = json.load(open(os.path.join(ROOT, "analyses", "leaf_guard_rules.json"), encoding="utf-8"))
LG.check_rules(rules)
m463 = [r for r in rules if r["milestone"] == "M463"]
assert m463 and all(r["id"].startswith("m463-") for r in m463)
assert all(r["condition"] in LG.CONDITIONS for r in m463)
print("test_leaf_guard_m463 OK")
