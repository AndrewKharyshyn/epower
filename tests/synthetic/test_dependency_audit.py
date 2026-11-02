"""M557 (analyses/M557_spec.md Rev 2): known-answer tests for the dependency-graph classifier in tools/dependency_audit.py."""
import os, sys, json, copy
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import dependency_audit as DA


def N(id_, kind, parents=(), **kw):
    d = {"id": id_, "label": id_, "kind": kind, "source": id_, "parents": list(parents), "derivation": "x"}
    d.update(kw); return d


g = {"nodes": [N("raw1", "raw_logged"), N("raw2", "raw_logged"), N("k_unver", "constant", verified=False), N("k_ver", "constant", verified=True),
               N("T", "derived", ["raw1"]), N("child", "derived", ["T"]), N("sib", "derived", ["raw1"]), N("other", "derived", ["raw2"]),
               N("T2", "derived", ["raw1", "k_unver"]), N("other2", "derived", ["raw2", "k_unver"]), N("other3", "derived", ["raw2", "k_ver"]),
               N("recode", "derived", ["raw1"], sameDerivationAs="T"),
               N("M", "model_output", ["raw1"]), N("Mre", "model_output", ["M"]), N("lat", "latent_unlogged"), N("app", "app_calculated", ["lat"]), N("other_app", "app_calculated", ["lat"])]}
assert DA.validate_graph(g) == []
nodes = DA.index(g)

# KA1: child / parent / sibling / disjoint
assert DA.classify(nodes, "T", ["child"])[0] == "circular"
assert DA.classify(nodes, "child", ["T"])[0] == "circular"
assert DA.classify(nodes, "T", ["sib"])[0] == "shared_raw_input"
assert DA.classify(nodes, "T", ["other"])[0] == "independent"
assert DA.classify(nodes, "T", ["T"])[0] == "circular" and DA.classify(nodes, "T", ["other", "T"])[0] == "circular"
assert DA.classify(nodes, "T", ["recode"])[0] == "coding_check_only" and DA.classify(nodes, "recode", ["T"])[0] == "coding_check_only"
# model adequacy: a model_output descendant of a model_output target
assert DA.classify(nodes, "M", ["Mre"])[0] == "model_adequacy" and DA.classify(nodes, "T", ["child"])[0] == "circular"

# KA2: a shared unverified constant alone is a common-mode factor (conditional independence), a shared verified constant or a shared raw channel behave as stated
c, shared, unver = DA.classify(nodes, "T2", ["other2"])
assert c == "independent_conditional_on_unverified_constant" and unver == {"k_unver"} and shared == set()
assert DA.classify(nodes, "T2", ["other3"])[0] == "independent"
assert DA.classify(nodes, "T2", ["sib"])[0] == "shared_raw_input"
# a shared latent ancestor counts as a shared input
assert DA.classify(nodes, "app", ["other_app"])[0] == "shared_raw_input"

# schema: an app_calculated node without a parent, an unknown parent and a cycle are rejected
bad = copy.deepcopy(g); bad["nodes"].append(N("orphan_app", "app_calculated"))
assert any("without a declared parent" in p[1] for p in DA.validate_graph(bad))
bad = copy.deepcopy(g); bad["nodes"].append(N("x", "derived", ["nope"]))
assert any("unknown parent" in p[1] for p in DA.validate_graph(bad))
bad = copy.deepcopy(g); bad["nodes"][4]["parents"] = ["child"]            # T <- child <- T
assert any("cycle" in p[1] for p in DA.validate_graph(bad))
bad = copy.deepcopy(g); bad["nodes"].append(N("motor_target", "raw_logged"))
assert any("target / command" in p[1] for p in DA.validate_graph(bad))

# KA3: controls: a null mechanism is required; the target must not be a descendant of the control
allowed = ["null", "nonnull", "nonnull_one_sided", "bias_reference", "decision_rule"]
good = {"target": "T", "validators": ["other"], "nullMechanism": "m", "expectedOutcome": "null"}
assert DA.control_problems(nodes, good, allowed) == []
assert DA.control_problems(nodes, {**good, "nullMechanism": ""}, allowed) == ["no null mechanism"]
assert any("descendant" in p for p in DA.control_problems(nodes, {"target": "child", "validators": ["T"], "nullMechanism": "m", "expectedOutcome": "null"}, allowed))
assert any("expectedOutcome" in p for p in DA.control_problems(nodes, {**good, "expectedOutcome": "whatever"}, allowed))

# the payload scan finds exactly the keys of the pattern and respects the exclusions
scan = {"keyPattern": "(?i)(negative_?controls?$|misspec_?control$|.*[a-z]control$)", "exclusions": {"referenceIsControl": "flag"}}
pay = {"a": {"negativeControl": {"x": 1}, "referenceIsControl": True, "b": [{"misspecControl": {}}]}, "_artifactStamps": {"negativeControl": {}}}
hits, seen = DA.scan_controls(pay, scan)
assert hits == ["/a/b[0]/misspecControl", "/a/negativeControl"] and seen == {"referenceIsControl"}

# registry (real files): valid graph, header strings, coverage and the pre-registered classes are in the stored block
graph = json.load(open("channel_dependency_graph.json", encoding="utf-8"))
assert DA.validate_graph(graph) == []
A = json.load(open("summary_arrays.json", encoding="utf-8"))
B = A["channelDependency"]
got = {c["id"]: c["computedClass"] for c in B["claims"]}
for k, v in DA.PRE_REGISTERED.items():
    assert got[k] == v or k == "E6", (k, got[k], v)      # M565: E6 now computes model_adequacy (R2b); its pre-registered shared_raw_input stays recorded as not met
assert got["E6"] == "model_adequacy"
assert all(got[k] == "negative_control" for k in ("C1", "C2", "C3", "C4", "C5", "C6")) and got["C7"] == "decision_rule" and len(B["claims"]) == 13
rel = {c["id"]: c["relation"] for c in B["claims"]}
assert rel["C7"] == "circular"                                   # Director: a decision rule, circular with its target by construction
settled = {c["id"]: c["settledClass"] for c in B["claims"]}
assert settled["E6"] == "model_adequacy" and B["preRegisteredNotMet"] == ["E6"]   # the pre-registered expectation for E6 is recorded as not met
assert not any(c["sharedUnverifiedConstants"] for c in B["claims"])        # the spurious FMEP link of C1 is gone
assert not B["coverage"]["ledgerChecksWithoutClaim"] and not B["coverage"]["scanHitsWithoutClaim"] and not B["coverage"]["controlClaimsWithoutHit"]
assert all(c["declaredClass"] == c["computedClass"] for c in B["claims"] if c["id"] != "E6")   # E6: declared shared_raw_input, computed model_adequacy since M565 (declaration not edited)
print("test_dependency_audit OK")
