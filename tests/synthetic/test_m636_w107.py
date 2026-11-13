"""M636 (W1-07): the M85 provenance figures are dated and point at the live keys; the old undated wording is a gate rule."""
import json, os, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, REPO)
import language_gate as LG
A = json.load(open(os.path.join(REPO, "summary_arrays.json"), encoding="utf-8"))
C = json.load(open(os.path.join(REPO, "summary_config.json"), encoding="utf-8"))
old1 = "comes from logged BMS sensor readings (time-weighted mean pack ~34.2C, 54.3% of drive-time >=35C, highway thermal rise +17C above ambient)"
old2 = "consistent with the observed logged distance mix (67.6% highway)"
assert "M636-undated-m85-figures" in LG.scan_text(old1) and "M636-undated-m85-figures" in LG.scan_text(old2)
for src in (A["seasonalLife"]["assumptions"], C["seasonalLife"]["assumptions"] if "seasonalLife" in C else A["seasonalLife"]["assumptions"]):
    for txt in (src["hotTail"]["_provenance"], src["_mixProvenanceM85"]):
        assert "M636-undated-m85-figures" not in LG.scan_text(txt)
    assert "at M85, 2026-08-05 corpus" in src["hotTail"]["_provenance"] and "hotTail.packThermalMeasured" in src["hotTail"]["_provenance"]
    assert "67.6% highway at M85, 2026-08-05 corpus" in src["_mixProvenanceM85"]
assert A["seasonalLife"]["hotTail"]["packThermalMeasured"]["timeWeightedMeanPackC"] is not None and "observedMix" in A
print("PASS test_m636_w107")
