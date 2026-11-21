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
_pf = a["powerFade"]
_lo, _hi = _pf["ci95MohmPerMo"]
_cs = _pf["cadenceSensitivity"]
if _lo <= 0.0 <= _hi:
    assert "a trend is not resolved in this window" in _pf["note"]
else:
    # M721 (Director ruling, Andrii sign-off): the published-specification interval does not span zero: the note says where it lies, that it depends on seed, cadence and temperature handling, that a fade trend is not established and that no fade rate is claimed
    assert "a fade trend is not established in this window and no fade rate is claimed" in _pf["note"] and "depends on the bootstrap seed" in _pf["note"]
    assert "(%d of %d cadence specifications span zero)" % (_cs["nSpecsSpanZero"], _cs["nSpecs"]) in _pf["note"]
    assert "excludes zero on this build" not in _pf["note"] and "before treating it as fade" not in _pf["note"]
    _sf = (_pf.get("cadenceCovariates") or {}).get("specificationSensitivity", {}).get("descriptiveFacts", {}).get("e0LowerEndpointBelowZero")
    if _sf:      # M724 (Andrii sign-off): the note states that seed 42 is the published seed and in how many pre-listed seeds the lower endpoint is below zero
        assert "seed 42 is the published seed and the lower endpoint is below zero in %d of %d pre-listed seeds" % (_sf["nSeeds"], _sf["ofSeeds"]) in _pf["note"]
assert _pf["note"] == a["fadeModes"]["power"]["trend"]["note"]
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
