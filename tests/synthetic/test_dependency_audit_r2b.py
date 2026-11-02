"""M565 (analyses/M565_spec.md Rev 2): known answers KC1-KC13 of the R2b sibling rule (responseNode) in tools/dependency_audit.py."""
import copy, hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import dependency_audit as DA


def N(id_, kind, parents=(), **kw):
    d = {"id": id_, "label": id_, "kind": kind, "source": id_, "parents": list(parents), "derivation": "x"}
    d.update(kw); return d


g = {"nodes": [N("raw1", "raw_logged"), N("cov", "raw_logged"), N("resp", "derived", ["raw1"]), N("resp2", "derived", ["raw1"]), N("other_raw", "raw_logged"),
               N("A", "model_output", ["resp", "cov"], responseNode="resp"), N("B", "model_output", ["resp", "cov"], responseNode="resp"), N("B2", "model_output", ["resp", "cov"], responseNode="resp"),
               N("C", "model_output", ["resp", "cov"]), N("D", "model_output", ["resp2", "cov"], responseNode="resp2"),
               N("Achild", "model_output", ["A"], responseNode=None), N("Arecode", "model_output", ["resp", "cov"], responseNode="resp", sameDerivationAs="A"),
               N("E", "model_output", ["resp"]), N("F", "model_output", ["resp"])]}
for n in g["nodes"]:
    if n.get("responseNode") is None:
        n.pop("responseNode", None)
assert DA.validate_graph(g) == []
nd = DA.index(g)
cl = lambda t, v: DA.classify(nd, t, v)
# KC1 siblings with the same responseNode; KC12 the shared ancestors come back unchanged (compared with the same pair without the declaration)
c, data, unv = cl("A", ["B"])
assert c == "model_adequacy" and data == {"raw1", "cov"} - {"cov"} | {"cov"} - {"cov"} or data == {"raw1"} | ({"cov"} & data), (c, data)
plain = copy.deepcopy(g)
for n in plain["nodes"]:
    n.pop("responseNode", None)
c2, data2, unv2 = DA.classify(DA.index(plain), "A", ["B"])
assert c2 == "shared_raw_input" and data2 == data and unv2 == unv, (c2, data2, data)      # KC2 (same derived parent, no declaration) and KC12
# KC3 different responseNode; KC9 declared on one side only
assert cl("A", ["D"])[0] == "shared_raw_input" and cl("A", ["C"])[0] == "shared_raw_input" and cl("C", ["A"])[0] == "shared_raw_input"
# KC4 child of the target is circular / the existing model_adequacy branch comes first (both are model_output descendants)
assert cl("A", ["Achild"])[0] == "model_adequacy" and cl("Achild", ["A"])[0] == "circular" and cl("A", ["A"])[0] == "circular"
# KC8 sameDerivationAs first
assert cl("A", ["Arecode"])[0] == "coding_check_only"
# KC6 mixed validators; KC10 several siblings
assert cl("A", ["B", "C"])[0] == "shared_raw_input" and cl("A", ["B", "B2"])[0] == "model_adequacy"
# KC5 raw validator, KC11 schema errors
assert cl("A", ["raw1"])[0] == "circular"
for mut, msg in ((lambda n: n.update(responseNode="resp"), "E"), ):
    pass
bad = copy.deepcopy(g); [n.update(responseNode="resp2") for n in bad["nodes"] if n["id"] == "E"]
assert any("derived parent" in p[1] for p in DA.validate_graph(bad))              # resp2 is not a parent of E
bad = copy.deepcopy(g); [n.update(responseNode="raw1") for n in bad["nodes"] if n["id"] == "E"]
assert any("derived parent" in p[1] for p in DA.validate_graph(bad))              # not a derived node
bad = copy.deepcopy(g); bad["nodes"].append(N("Z", "derived", ["raw1"], responseNode="resp"))
assert any("not a model_output" in p[1] for p in DA.validate_graph(bad))          # wrong kind
assert cl("A", [])[0] != "model_adequacy"                                       # KC14 an empty validator list is never a sibling pair
# KC7 real registry: relation / computedClass of all 13 claims, the trigger set and the audit file hash
graph = json.load(open("channel_dependency_graph.json", encoding="utf-8")); claims = json.load(open("independence_claims.json", encoding="utf-8"))
assert DA.validate_graph(graph) == []
rn = DA.index(graph)
expect = {"E1": "coding_check_only", "E2": "shared_raw_input", "E3": "circular", "E4": "model_adequacy", "E5": "model_adequacy", "E6": "model_adequacy",
          "C1": "shared_raw_input", "C2": "shared_raw_input", "C3": "shared_raw_input", "C4": "model_adequacy", "C5": "model_adequacy", "C6": "model_adequacy", "C7": "circular"}
got = {c["id"]: DA.classify(rn, c["target"], c["validators"])[0] for c in claims["claims"]}
assert got == expect, {k: (got[k], expect[k]) for k in expect if got[k] != expect[k]}
A = json.load(open("summary_arrays.json", encoding="utf-8"))["channelDependency"]
assert {r["id"]: r["relation"] for r in A["claims"]} == expect
assert {r["id"]: r["computedClass"] for r in A["claims"] if r["id"].startswith("E")} == {k: v for k, v in expect.items() if k.startswith("E")}
assert {r["id"]: r["computedClass"] for r in A["claims"] if r["id"].startswith("C")} == {"C1": "negative_control", "C2": "negative_control", "C3": "negative_control", "C4": "negative_control", "C5": "negative_control", "C6": "negative_control", "C7": "decision_rule"}
assert sorted(map(tuple, A["triggers"])) == sorted([("E2", "the ledger text says 'independent' but the computed class is shared_raw_input"), ("E3", "the ledger text says 'independent' but the computed class is circular"),
                                                    ("E6", "computed model_adequacy differs from the pre-registered shared_raw_input"), ("E6", "declared shared_raw_input differs from computed model_adequacy")])
assert A["preRegisteredNotMet"] == ["E6"] and "E6" not in A["settledOverrides"] and "C6" in A["settledOverrides"]
assert hashlib.sha256(open("analyses/M557_audit_result.json", "rb").read()).hexdigest() == A["blindAudit"]["resultSha256"]
assert A["inputs"]["graphSha256"] == hashlib.sha256(open("channel_dependency_graph.json", "rb").read()).hexdigest()
# KC13 the scan never reads the tool's own output block
hits, _ = DA.scan_controls({"channelDependency": {"xControl": 1}, "a": {"bControl": 2}}, claims["scan"])
assert hits == ["/a/bControl"], hits
print("test_dependency_audit_r2b OK")
