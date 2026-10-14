#!/usr/bin/env python3
"""M429 splice (analyses/M429_spec.md Rev 2, gate G2): leaf-level update of summary_arrays.json from the script-written analyses/M429_result.json (tools/m429_soak.py, which also passed gate G1).
Only the leaves listed in the spec may change; the deep diff against the current payload must stay inside this list and nothing else may differ. Idempotent.
Usage: python tools/m429_splice.py [--dry-run]    then   python tools/m429_soak.py verify   (gate G3)"""
import ast, copy, hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
DRY = "--dry-run" in sys.argv
R = json.load(open("analyses/M429_result.json", encoding="utf-8"))
raw = open("summary_arrays.json", "rb").read().decode("utf-8")
A = json.loads(raw)
if json.dumps(A, ensure_ascii=False, indent=1) != raw:
    raise SystemExit("serialisation round-trip differs: refusing to rewrite the file")
if R["_provenance"]["masterMd5"] != hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest():
    raise SystemExit("M429_result.json was computed on a different master")
if not all(g["ok"] for g in R["G1"]):
    raise SystemExit("gate G1 did not pass in the result file")

# the producer's methodology text (single source of truth: the AST constant of compute_summary_arrays.py)
tree = ast.parse(open("compute_summary_arrays.py", encoding="utf-8").read())
cands = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("M223.1 (P0.1, enhancement plan): extends ")]
if len(cands) != 1:
    raise SystemExit("producer methodology string: %d matches (need 1)" % len(cands))

ALLOWED = [
    "/heatSoakCarryover/soakTauCI", "/heatSoakCarryover/method", "/heatSoakCarryover/soakTauCiMethod", "/heatSoakCarryover/soakDecayRateK", "/heatSoakCarryover/soakDecayRateKCI",
    "/heatSoakCarryover/soakHalfLifeCI", "/heatSoakCarryover/soakTauMethodTable", "/heatSoakCarryover/soakTauLeaveOneDay", "/heatSoakCarryover/soakTauGapSplit",
    "/interDriveCarryover/thermalDecay/battery/tauCI", "/interDriveCarryover/thermalDecay/battery/tauCiMethod",
    *["/interDriveCarryover/thermalDecay/%s/%s" % (c, k) for c in ("coolant", "oil") for k in ("tauCI", "tauCiMethod", "decayRateK", "decayRateKCI", "halfLifeCI", "methodTable", "leaveOneDay", "gapSplit")],
    "/interDriveCarryover/methodology",
]
N = copy.deepcopy(A)
N["heatSoakCarryover"] = R["heatSoakCarryover"]
td = N["interDriveCarryover"]["thermalDecay"]
td["coolant"], td["oil"] = R["coolant"], R["oil"]
td["battery"]["tauCI"] = R["heatSoakCarryover"]["soakTauCI"]
td["battery"]["tauCiMethod"] = R["heatSoakCarryover"]["soakTauCiMethod"]
N["interDriveCarryover"]["methodology"] = cands[0]


def diff(a, b, p=""):
    if type(a) is not type(b):
        return [p]
    if isinstance(a, dict):
        return [x for k in sorted(set(a) | set(b)) for x in diff(a.get(k), b.get(k), p + "/" + k)]
    if isinstance(a, list):
        return [x for i, (u, v) in enumerate(zip(a, b)) for x in diff(u, v, p + "/%d" % i)] if len(a) == len(b) else [p + " len"]
    return [p] if a != b else []


d = diff(A, N)
stray = [x for x in d if not any(x == a or x.startswith(a + "/") for a in ALLOWED)]
if stray:
    raise SystemExit("unexpected changed leaves (outside the G2 list): %r" % stray[:10])
roots = sorted({next(a for a in ALLOWED if x == a or x.startswith(a + "/")) for x in d})
print(json.dumps({"nChangedLeaves": len(d), "changedRoots": roots}, indent=1))
if not DRY and d:
    with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(N, ensure_ascii=False, indent=1))
    print("wrote summary_arrays.json")
elif not d:
    print("nothing to change (already applied)")
