"""M408: the power-fade null result is described as an estimated proxy trend that is not resolved; the old wording is forbidden (rule M408-powerfade-wording) and absent from the payload; W3-mde stays in force."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import language_gate as G

R = {r.rid: r for r in G.RULES}
r = R["M408-powerfade-wording"]
assert not any(ord(c) < 32 for c in r.rx.pattern)
for bad in ("no statistically detectable power fade in this window", "the measured trend is statistically indistinguishable from zero", "What IS comparable is the measured TREND",
            "that no degradation trend is detectable", "The measured interval straddles zero", "The measured interval excludes zero"):
    assert r.hits(bad), bad
for good in ("a trend is not resolved in this window", "the estimated trend is not resolved from zero in this window", "the estimated TREND", "The estimated interval straddles zero",
             "the measured thermics are retained"):
    assert not r.hits(good), good
assert R["W3-mde"].hits("the minimum detectable effect")
a = json.load(open("summary_arrays.json", encoding="utf-8"))
assert "a trend is not resolved in this window" in a["powerFade"]["note"] and a["powerFade"]["note"] == a["fadeModes"]["power"]["trend"]["note"]
assert "estimated trend is not resolved from zero" in a["fadeModes"]["power"]["whyNotProjected"]
assert "estimated TREND" in a["officialDisclosureCorrelation"]["resistance"]["note"] and "estimated TREND" in a["officialDisclosureCorrelation"]["rows"][2]["note"]
assert "no degradation trend is resolved in this window" in a["_retractedLifeEol"]
strings = []
def walk(o):
    if isinstance(o, dict):
        [walk(v) for v in o.values()]
    elif isinstance(o, list):
        [walk(v) for v in o]
    elif isinstance(o, str):
        strings.append(o)
walk(a)
assert not [s[:60] for s in strings if r.hits(s)]
print("OK test_m408_wording")
