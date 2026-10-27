"""M526 (analyses/M526_spec.md Rev 1.1): stale corpus-size statements in payload text are corrected or qualified. N1 rule: 0 hits on the whole post-edit payload and on frozen history strings; fires on the old
wording. N2 a planted extra leaf change is caught by the deep diff. N3 idempotent. N4 producer constants equal the payload leaves. Old text absent from payload / producer / splice constants / dumps."""
import ast, copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import language_gate as G
import m526_text_splice as S

A = json.load(open("summary_arrays.json", encoding="utf-8"))
R = {r.rid: r for r in G.RULES}["M526-corpus-size-text"]

def strings(o):
    if isinstance(o, dict):
        for v in o.values(): yield from strings(v)
    elif isinstance(o, list):
        for v in o: yield from strings(v)
    elif isinstance(o, str):
        yield o

# N1: 0 hits on the whole post-edit payload; the frozen history strings are not flagged; the old wording is
assert not [s for s in strings(A) if R.hits(s)]
for hist in ("frozen historical record at the M366 corpus (489 drives): previous published FUEL-12 figures", "M375 / 489 drives; M366 raw-swap provenance, not recomputed",
             "numeric leaves are the one-off 410-drive pass (397 drives with engine-on time) and are not refreshed", "M341: 37 of 37 RAW-class seasonal charts are regenerated on the live 606-drive corpus"):
    assert not R.hits(hist), hist
assert R.hits("RPM empirical-grounding sample (410 drives, refreshed M281) are current.")
assert R.hits("at RPM>1400 it is only ~2.5% of the boost-classified population, so")
assert R.hits("M295: re-derived on the live 446-drive payload") and R.hits("matched the live 446-drive corpus")
assert R.hits("even at the current 320-drive corpus")
# the new loadProxyBasis text keeps '2.5' out of any flagged pattern and says what the basis is
lpb = A["rpmDistribution"]["params"]["loadProxyBasis"]
assert "no traceable basis" in lpb and "historical M89 calibration" in lpb and "only ~2.5%" not in lpb
# all 6 loadProxyBasis copies equal
for c in ("all", "warm", "shoulder", "cold"):
    assert A["seasonalCharts"]["charts"]["RpmDistribution"]["data"][c]["params"]["loadProxyBasis"] == lpb, c

# N3 idempotent
new, changed, bad = S.splice(A)
assert not changed and not bad and new == A
# N2 a planted extra leaf change is caught
plant = copy.deepcopy(A); plant["meta"]["totalDrives"] += 1
assert S.leaf_diff(A, plant) == [("meta", "totalDrives")]
plant2 = copy.deepcopy(A); plant2["rpmDistribution"]["pooledHours"][1] += 0.001
assert S.leaf_diff(A, plant2)
# reverting one allowed leaf to the old text is visible to the splice (it would re-apply it)
rev = copy.deepcopy(A); rev["socHysteresisV2"]["recomputePolicy"] = rev["socHysteresisV2"]["recomputePolicy"].replace(S.REC_NEW, S.REC_OLD)
assert S.splice(rev)[1] == [("socHysteresisV2", "recomputePolicy")]

# N4 producer constants equal the payload leaves (adjacent string literals are merged by the parser)
def producer_const(path, startswith):
    tree = ast.parse(open(path, encoding="utf-8").read())
    hits = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith(startswith)]
    assert len(hits) == 1, (path, startswith, len(hits))
    return hits[0]
assert producer_const("compute_summary_arrays.py", "M89: calc-load-only fuelled proxy") == lpb
assert producer_const("compute_summary_arrays.py", "M119-v2 recomputation is opt-in by design") == A["socHysteresisV2"]["recomputePolicy"]
# old text absent from the producer / splice constants
for f in ("compute_summary_arrays.py", "m295_payload.py", "tools/m373_p2_splice.py"):
    t = open(f, encoding="utf-8").read()
    for old in ("only ~2.5% of the boost-classified population", "re-derived on the live 446-drive payload", "refreshed M281) are current", "even at the current 320-drive corpus"):
        assert old not in " ".join(t.replace("'\n", "").split()) .replace("' '", ""), (f, old)

# rendered dumps (local only): the limitation sentence changed; old wording absent
if os.path.isdir("tabtext"):
    for mode in ("all", "warm", "shoulder", "cold"):
        t = " ".join(open(os.path.join("tabtext", "fuel__%s.txt" % mode), encoding="utf-8").read().split())
        assert "refreshed M281) are current" not in t and "superseded by the live rpmOptBand (M525)" in t, mode
print("OK test_m526_payload_text: 9 leaves, rule 0 hits, controls, producer constants equal leaves")
