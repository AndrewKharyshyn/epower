"""M652: official-disclosure wording. The rule fires on the old wording; the shipped payload and sources no longer contain it. Run: python tests/synthetic/test_m652_disclosure_wording.py"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import language_gate as G
rule = {r.rid: r for r in G.RULES}["M652-official-disclosure-wording"]
for bad in ("motor 150 kW rated vs 66 kW battery cap", "against this study's own measured / modeled figures"):
    assert rule.hits(bad), bad
for good in ("66 kW disclosed battery figure (at 80 % SoC)", "against this study's own logged and estimated figures"):
    assert not rule.hits(good), good
jsx = open("xtrail_summary.jsx", encoding="utf-8").read()
assert "kW battery cap`" not in jsx and "implied <strong>" in jsx and "disclosed battery figure" in jsx
a = json.load(open("summary_arrays.json", encoding="utf-8"))
assert "measured / modeled" not in open("compute_summary_arrays.py", encoding="utf-8").read(), "builder text"
assert "measured / modeled" not in a["officialDisclosureCorrelation"]["basis"] and "logged and estimated figures" in a["officialDisclosureCorrelation"]["basis"]
print("PASS test_m652_disclosure_wording")
