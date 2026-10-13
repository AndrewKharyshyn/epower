#!/usr/bin/env python3
"""M427 splice (Wave A of the external audit 2026-10-13): leaf-level text update of summary_arrays.json after the producer fixes. Nothing numeric changes; drive_master.csv is not read.
  evTraction.caveats[1] (+ the four seasonalCharts EvTraction cohort copies)   F04: 'upper bound' -> 'estimated RPM-defined engine-off share'; text read from the producer in compute_summary_arrays.py (AST)
  observedMix.note                                                            F09: the scenario blend is listed in the order of selectedShare (city/mixed/highway), read from the payload
  generatorTractionRecon._staleness                                           F09: derived from refreshedBlocks / staleBlocks / gtrClosure (gtr_family_refresh_splice.derive_root_staleness)
  eligibility.dataCoverage.energyMissingReasons                              F16: metric-specific missing-energy reasons with support (tools/energy_reasons.py, from the master)
  thermalFuelPenalty methodology, combustionPenalty.note, dutyCycle.note     F18: 'isolates' -> 'a conditional contrast ... entangled' (substring substitution)
  provenanceSensitivity.wording[0]                                            F01: the allowed cell-spread wording follows the released interval (text read from f03_provenance.json)
STOP on any other change (deep diff against the exact expected leaf set). Idempotent: a second run changes nothing.
Usage: python tools/m427_splice.py [--dry-run]"""
import ast, copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
DRY = "--dry-run" in sys.argv

raw = open("summary_arrays.json", "rb").read().decode("utf-8")
A = json.loads(raw)
if json.dumps(A, ensure_ascii=False, indent=1) != raw:
    raise SystemExit("serialisation round-trip differs: refusing to rewrite the file")
N = copy.deepcopy(A)
expected = set()


def producer_string(path, startswith):
    """The single string constant in `path` (Python joins adjacent literals) that starts with `startswith`."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    c = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith(startswith)]
    if len(c) != 1:
        raise SystemExit("producer string %r: %d matches in %s (need 1)" % (startswith, len(c), path))
    return c[0]


# F04: evTraction caveat
NEW_EV = producer_string("compute_summary_arrays.py", "The +/-3 s nearest-sample channel alignment")
OLD_EV = "The +/-3 s channel alignment and the 3 s state debounce both bias engine-off upward: every EV distance and time figure is an upper bound."
ev_paths = ["evTraction"] + ["seasonalCharts/charts/EvTraction/data/%s" % m for m in ("all", "warm", "shoulder", "cold")]
for p in ev_paths:
    o = N
    for k in p.split("/"):
        o = o[k]
    if o["caveats"][1] not in (OLD_EV, NEW_EV):
        raise SystemExit("unexpected text at %s/caveats/1: %r" % (p, o["caveats"][1][:80]))
    if o["caveats"][1] != NEW_EV:
        o["caveats"][1] = NEW_EV
        expected.add("/" + p + "/caveats/1")

# F09: observedMix note order, from selectedShare
om = N["observedMix"]
sel = om["selectedShare"]
old_mix, new_mix = "selected 50/40/10 (city/mixed/highway)", "selected %g/%g/%g (city/mixed/highway)" % (sel["city"], sel["mixed"], sel["highway"])
if old_mix in om["note"]:
    om["note"] = om["note"].replace(old_mix, new_mix)
    expected.add("/observedMix/note")
elif new_mix not in om["note"]:
    raise SystemExit("observedMix.note: neither the old nor the new blend text is present")

# F09: root GTR staleness derived from the child records
import gtr_family_refresh_splice as GF
G = N["generatorTractionRecon"]
d = GF.derive_root_staleness(G)
if G.get("_staleness") != d:
    G["_staleness"] = d
    expected.add("/generatorTractionRecon/_staleness")

# F16: metric-specific reasons for the master rows without a gross-energy integral, computed from the master by the same module the producer uses
import pandas as pd
import energy_reasons as ER
dmr = pd.read_csv("drive_master.csv", low_memory=False)
if len(dmr) != A["meta"]["totalDrives"]:
    raise SystemExit("master row count differs from the payload meta.totalDrives")
blk = ER.energy_missing_reasons(dmr)
dc = N["eligibility"]["dataCoverage"]
if dc.get("energyMissingReasons") != blk:
    dc["energyMissingReasons"] = blk
    expected.add("/eligibility/dataCoverage/energyMissingReasons")

# F18: 'isolates' -> conditional contrast in the cold-start fuel narrative (substring substitution on every leaf that carries it)
SUBS18 = [('(isolates enrichment+cold-friction; day-clustered bootstrap, seed 42, ', '(a conditional contrast at matched RPMxload; enrichment, cold friction, oil and coolant state and demand stay entangled; day-clustered bootstrap, seed 42, '), ('(isolates series-hybrid strategy; the dominant term); ', '(a conditional duty contrast at matched road speed; strategy, coolant, oil and catalyst state and demand stay entangled; the larger of the two contrasts); '), ('Isolates enrichment + cold-friction from duty cycle and charge strategy. ', 'A conditional contrast at matched RPM x load; enrichment, cold friction, oil and coolant state and demand stay entangled, so it is not attributed to one mechanism. '), ('Engine-on fraction (rpm>400) at matched road speed, cold vs warm. The dominant mechanism of the trip penalty: the series-hybrid runs the ICE more when cold (catalyst light-off + cold charge/idle strategy).', 'Engine-on fraction (rpm>400) at matched road speed, cold vs warm: a descriptive conditional contrast. The series-hybrid runs the ICE more when cold; catalyst light-off, cold charge/idle strategy, coolant and oil state and demand stay entangled, so it is not attributed to one mechanism.')]
sub_paths = []


def walk18(o, p):
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, str):
                nv = v
                for a, b in SUBS18:
                    nv = nv.replace(a, b)
                if nv != v:
                    o[k] = nv
                    sub_paths.append(p + "/" + k)
            else:
                walk18(v, p + "/" + k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            walk18(v, p + "/%d" % i)


walk18(N, "")
expected.update(sub_paths)

# F01: the F03 allowed-wording leaf follows the interval (text from f03_provenance.json, the builder's output)
f03 = json.load(open("f03_provenance.json", encoding="utf-8"))
new_w = f03["wording"][0]
hits = []


def walk(o, p):
    if isinstance(o, dict):
        for k, v in o.items():
            walk(v, p + "/" + k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            walk(v, p + "/%d" % i)
    elif isinstance(o, str) and (o.startswith("cell-spread trend not resolved over the ") and o.endswith("(not 'no degradation')")):
        hits.append(p)


walk(N, "")
for p in hits:
    o = N
    ks = p.strip("/").split("/")
    for k in ks[:-1]:
        o = o[int(k)] if isinstance(o, list) else o[k]
    k = ks[-1]
    o[int(k) if isinstance(o, list) else k] = new_w
    expected.add(p)
if len(hits) > 1:
    raise SystemExit("more than one F03 wording leaf: %r" % hits)


def diff(a, b, p=""):
    if type(a) is not type(b):
        return [p]
    if isinstance(a, dict):
        return [x for k in sorted(set(a) | set(b)) for x in diff(a.get(k), b.get(k), p + "/" + k)]
    if isinstance(a, list):
        return [x for i, (u, v) in enumerate(zip(a, b)) for x in diff(u, v, p + "/%d" % i)] if len(a) == len(b) else [p + " len"]
    return [p] if a != b else []


changed = diff(A, N)
# the root staleness is a dict replacing a dict: its leaves are reported one by one, so compare by prefix
def covered(c):
    return any(c == e or c.startswith(e + "/") for e in expected)


stray = [c for c in changed if not covered(c)]
if stray:
    raise SystemExit("unexpected changed leaves: %r" % stray[:10])
print(json.dumps({"expectedLeafRoots": sorted(expected), "nChangedLeaves": len(changed)}, indent=1))
if not DRY and changed:
    with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(N, ensure_ascii=False, indent=1))
    print("wrote summary_arrays.json")
elif not changed:
    print("nothing to change (already applied)")
