"""M421 (audit F14 and F12): the two-pass current offset is worded as a model-derived residual-balance offset conditional on the SoC/capacity ledger (not a calibrated sensor zero, not a real bias, not corrected or recalibrated,
not corroborated by the Ready-mode idle current); the payload, the session ledgers, the producers and the dashboard source no longer carry the old claim wording; the card is `modelled`, not `measured`; the generator-closure note
states the need for an independent electrical reference."""
import json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import language_gate as G

rule = [r for r in G.RULES if r.rid == "M421-offset-claims"][0]
for bad in ("A real, sign-consistent current-sensor offset is corrected", "the offset is a real, sign-consistent bias, not a fitting artefact", "corroborated by an independent idle-hold check", "the independent READY-idle check",
            "Two-pass current-sensor offset recalibrates to -0.40 A", "the offset-corrected net draw", "the offset bootstrap interval excludes zero", "a calibrated sensor zero", "sensor-offset residual".replace("sensor-offset residual", "current-sensor bias")):
    assert rule.hits(bad), bad
for good in ("A model-derived residual-balance current offset is applied to net-draw metrics (conditional on the SoC/capacity ledger; not a calibrated sensor zero)", "the offset is not separable from zero", "offset-adjusted",
             "The stationary Ready-mode current carries auxiliary load and is not a zero reference", "two-pass residual-balance offset is re-estimated to -0.40 A"):
    assert not rule.hits(good), good
A = json.load(open("summary_arrays.json", encoding="utf-8"))
C = json.load(open("summary_config.json", encoding="utf-8"))
assert not G.scan_payload(A, [rule]) and not G.scan_payload(C, [rule])
# the old wording is gone from every producer that wrote it and from the dashboard source
for p in ("compute_summary_arrays.py", "crosscheck_events.py", "energy_uncertainty_mc.py", "tools/dependence_sensitivity.py", "xtrail_summary.jsx"):
    t = open(p, encoding="utf-8").read()
    assert not re.search(r"current-sensor (?:offset|bias)|sensor-offset residual|offset-corrected|offset correction|real, sign-consistent|not a fitting artefact", t), p
jsx = open("xtrail_summary.jsx", encoding="utf-8").read()
i = jsx.index('title="A model-derived residual-balance current offset is applied to net-draw metrics')
card_start = jsx.rindex("<ConclusionItem", 0, i)
assert jsx[card_start:i].startswith('<ConclusionItem status="modelled"'), "the offset card must not be tagged measured"
for must in ("function offsetCapBand(", "S.offsetUncertainty?.pointEstimateA", "not an uncertainty of a sensor zero", "is not a zero reference", "not separable from zero", "Calibrating a sensor zero needs a zero-current reference",
             "Physical validation of the generator split would need an independent electrical reference", "model consistency, not physical validation"):
    assert must in jsx, must
# the displayed numbers come from one source
ou = A["offsetUncertainty"]
assert abs(A["offset2pA"] - ou["pointEstimateA"]) < 1e-9 if "offset2pA" in A else True
assert A["capacityBasis"]["offsetModelTest"]["acceptance"]["acceptI2R"] is False and "dual report only" in A["capacityBasis"]["offsetModelTest"]["decision"]
assert len(ou["capacitySensitivity"]["rows"]) >= 2
ci = open(".github/workflows/ci.yml", encoding="utf-8").read()
assert "test_m421_wording.py" in ci
print("OK test_m421_wording")
