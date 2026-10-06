"""M384: known-answer cases of the regen parity comparator (tools/parity_compare.py), Director ruling: exact | superset (extra DICT keys only at splice-registered paths,
arrays of equal length) | differs; plus the registry (read from the owning splices) must cover every extra leaf found by the no-cache diagnostic (analyses/M384_parity_diag.json)."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import parity_compare as PC

P = ["/phaseEnergy/blindAudit", "/rows[i]/maxDrive", "/rows[i]/n"]
F = {"a": 1, "phaseEnergy": {"x": 1.5}, "rows": [{"label": "u", "lo": 1.0}, {"label": "h", "lo": 2.0}]}
cp = lambda: json.loads(json.dumps(F))

assert PC.compare(F, cp(), P)["verdict"] == "exact"
S = cp(); S["a"] = 2
r = PC.compare(F, S, P); assert r["verdict"] == "differs" and "a" in r["reasons"][0]                       # changed value
S = cp(); S["phaseEnergy"]["blindAudit"] = {"k": {"v": 1}, "w": 2}
r = PC.compare(F, S, P); assert r["verdict"] == "superset" and r["additiveLeaves"] == 2, r                   # registered extra subtree
S = cp(); S["rows"][0]["maxDrive"] = "f"; S["rows"][1]["maxDrive"] = "g"
r = PC.compare(F, S, P); assert r["verdict"] == "superset" and r["additiveLeaves"] == 2 and r["additiveKeys"] == ["/rows[i]/maxDrive"], r
S = cp(); S["phaseEnergy"]["other"] = 1
assert PC.compare(F, S, P)["verdict"] == "differs"                                                            # extra key outside the registered patterns
S = cp(); S["rows"][0]["median"] = 1
assert PC.compare(F, S, P)["verdict"] == "differs"                                                            # extra key in an array element, not registered
S = cp(); S["rows"].append({"label": "z", "lo": 3.0, "maxDrive": "q"})
r = PC.compare(F, S, P); assert r["verdict"] == "differs" and "array length" in r["reasons"][0], r              # stored array longer: never additive
S = cp(); del S["phaseEnergy"]
assert PC.compare(F, S, P)["verdict"] == "differs"                                                            # fresh leaf missing in stored
S = cp(); S["rows"] = S["rows"][:1]
assert PC.compare(F, S, P)["verdict"] == "differs"                                                            # stored array shorter
assert PC.compare({"x": 1}, {"x": 1.0}, [])["verdict"] == "differs"                                          # as strict as the canonical-JSON equality it replaces
assert PC.compare({"x": None}, {"x": 0}, [])["verdict"] == "differs"

reg = PC.registry()
assert reg["CrawlStopGo"] == ["/phaseEnergy/blindAudit"] and "[i]/maxDrive" in reg["EngineStartsByType"] and len(reg["EngineStartsByType"]) == 11, reg
diag = json.load(open(os.path.join(ROOT, "analyses", "M384_parity_diag.json"), encoding="utf-8"))
for name, e in diag["charts"].items():
    d = e["diffStoredVsFresh"]
    assert d["nChanged"] == 0 and d["nOnlyInFresh"] == 0
    bad = [p for p in d["onlyInStored"] if not PC._allowed(p, reg[name])]
    assert not bad and d["nOnlyInStored"] == len(d["onlyInStored"]) or d["nOnlyInStored"] > 40, (name, bad)   # the report lists the first 40; all listed ones are registered
print("OK test_parity_compare")
