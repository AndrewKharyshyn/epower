"""M642 (W1-17): the official-disclosure block states only what the Nissan sheet states; old claims are gate rules; builder source and payload carry the same wording."""
import json, os, re
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import sys
sys.path.insert(0, REPO)
import language_gate as LG
A = json.load(open(os.path.join(REPO, "summary_arrays.json"), encoding="utf-8"))
O = A["officialDisclosureCorrelation"]
src = open(os.path.join(REPO, "compute_summary_arrays.py"), encoding="utf-8").read()
jsx = open(os.path.join(REPO, "xtrail_summary.jsx"), encoding="utf-8").read()
cfg = json.load(open(os.path.join(REPO, "summary_config.json"), encoding="utf-8"))
old = ["independently corroborates this study's central framing", "a standardized long-pulse DCIR at 80% SoC", "Lab figure at gentle current, new battery.", "(new, benign protocol)",
       "First external anchor for a constant previously carried as thresholdVerified: false", "The capacity-fade threshold gains its first external anchor", "order-of-magnitude corroboration only", "bracketing the 20,000-GTC scenario threshold"]
for t in old:
    assert "M642-official-sheet-claims" in LG.scan_text(t), t
assert not LG.scan_text("events are independently corroborated by all three other physical detectors")
# payload: wording present, old claims absent
assert "carries no evidence for or against" in O["verdictHeadline"] and "independently" not in O["verdictHeadline"] and "tolerated" not in O["verdictHeadline"] and "(unverified)" in O["verdictHeadline"]
assert "states no test protocol, pulse length or temperature" in O["resistance"]["note"] and O["rows"][2]["note"] == O["resistance"]["note"]
r0, r4, r5 = O["rows"][0], O["rows"][4], O["rows"][5]
assert r0["parameter"] == "Rated capacity" and r0["verdict"] == "not_comparable" and "no capacity is measured here" in r0["ours"] and "nothing is compared" in r0["note"] and "5.84" not in r0["ours"]
assert "new battery condition" in r4["official"] and "benign" not in r4["official"] and "states no current, load or protocol" in r4["note"]
assert r5["verdict"] == "scenario_only" and "may vary with driving style" in O["capacityFadeAnchor"]["note"] and "14 years or that mileage" in O["capacityFadeAnchor"]["note"]
assert "arithmetic scenario with no evidentiary weight" in O["capacityFadeAnchor"]["note"] and r5["note"] == O["capacityFadeAnchor"]["note"] and "BRACKETS" not in O["capacityFadeAnchor"]["note"]
prov = O["official"]["_provenance"]
assert "edd2e4719e54c73feff940a2afc87733ddddce71e47579b42336bb423582b3c8" in prov and "test-protocol outputs" not in prov and "Conditions the sheet states" in prov and "published under Article 10" in prov
assert "(unverified)" in O["resistance"]["note"] and "What IS comparable" not in O["resistance"]["note"]
assert prov == cfg["officialDisclosure"]["_provenance"]
# builder source carries the same wording (anti-drift between the builder and the spliced leaves)
for frag in ("carries no evidence for or against", "states no test protocol, '", "nothing is compared", "This is an arithmetic scenario with no evidentiary weight", "new battery condition", "states no current, load or protocol"):
    assert frag.replace("'", "") in src.replace("'", "").replace('"', '').replace("\\", "") or frag in src, frag
for gone in ("standardized long-pulse DCIR", "Lab figure at gentle current", "benign protocol", "First external anchor for a constant", "independently '\n            'corroborates"):
    assert gone not in src, gone
# dashboard
assert "scenario_only:" in jsx and "external reference, not a validation" in jsx and "An arithmetic scenario with no evidentiary weight" in jsx and "gains its first external anchor" not in jsx and "Assumption restated, not an estimate" not in jsx
print("PASS test_m642_official_wording")
