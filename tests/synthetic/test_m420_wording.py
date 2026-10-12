"""M420: the integrationScenarios block and its dashboard component carry no total / combined / accuracy / error wording (rule M420-integration-scenarios), keep the Director's required statements (deterministic
recomputation, day-to-day variability, reference scaling, separate Monte Carlo reference with its omitted components) and the stage / CI wiring exists."""
import json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import language_gate as G

rule = [r for r in G.RULES if r.rid == "M420-integration-scenarios"][0]
for bad in ("The shift is exact on this corpus", "an interval around the nominal", "the total uncertainty of the throughput", "an error budget", "the true throughput", "the accuracy of the throughput", "hold variants bracket the truth"):
    assert rule.hits(bad), bad
for good in ("a deterministic recomputation on this corpus", "not an uncertainty of the total", "would understate total uncertainty", "the Monte Carlo interval alone understates the sensitivity of the throughput", "reference scaling; CAP_KWH=2.1 verified:false"):
    assert not rule.hits(good), good
A = json.load(open("summary_arrays.json", encoding="utf-8"))
B = A["integrationScenarios"]
strings = []


def walk(o):
    if isinstance(o, dict):
        [walk(v) for v in o.values()]
    elif isinstance(o, list):
        [walk(v) for v in o]
    elif isinstance(o, str):
        strings.append(o)


walk(B)
assert not [s[:80] for s in strings if rule.hits(s)]
bad = re.compile(r"\b(significant(?:ly)?|confirmed|robust|corrected|worst[- ]case|bounds?|bias|measured throughput|true throughput)\b", re.I)
assert not [s[:80] for s in strings if bad.search(s)], [s[:80] for s in strings if bad.search(s)]
reading = " ".join(B["reading"])
for must in ("deterministic recomputation", "day-to-day variability", "not an uncertainty of the total", "not an identified ground truth", "reference scaling"):
    assert must in reading, must
assert "not a statement of physical accuracy" in B["monteCarlo"]["reading"] and "I/V lag beyond the tolerance sweep" in " ".join(B["monteCarlo"]["omitted"])
assert any("not a causal cadence effect" in r["definition"] for r in B["carriedStudies"])
assert all("verified:false" in " ".join([r["definition"], r.get("applies", "")]) or "CAP_KWH" not in r["definition"] for r in B["capacityReferences"])
jsx = open("xtrail_summary.jsx", encoding="utf-8").read()
comp = jsx[jsx.index("function IntegrationScenarios("):jsx.index("function ProvenanceBlock(")]
for must in ("S.integrationScenarios", "a deterministic recomputation on this corpus", "Day-to-day variability of the ratio", "reference scaling; CAP_KWH=2.1 verified:false", "Monte Carlo reference (separate; conditional)", "alone understates the sensitivity of the throughput"):
    assert must in comp or must in jsx, must
assert not re.search(r"penalty|total uncertainty|error budget|accuracy of the", comp, re.I)
stages = json.load(open("tools/ingest_stages.json", encoding="utf-8"))
ids = [x["id"] for x in (stages["stages"] if isinstance(stages, dict) else stages)]
assert "integration_scenarios" in ids and ids.index("integration_scenarios") > ids.index("stage_raw") and ids.index("integration_scenarios") > ids.index("thermal_support_ledger") and ids.index("integration_scenarios") < ids.index("restamp_ingest")
ci = open(".github/workflows/ci.yml", encoding="utf-8").read()
assert "test_integration_scenarios.py" in ci and "test_m420_wording.py" in ci
print("OK test_m420_wording")
