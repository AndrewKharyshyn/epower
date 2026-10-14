"""M418: the thermalSupportLedger block and its dashboard component carry no survival / failure-to-warm-up / typical-warm-up wording (rule M418-thermal-censoring), state the right-censoring reading, and the stage / CI wiring exists."""
import json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import language_gate as G

R = {r.rid: r for r in G.RULES}
rule = R["M418-thermal-censoring"]
for bad in ("The drive failed to warm up", "never warmed up", "typical warm-up time", "median warm-up time of 400 s", "a survival curve", "winter warm-up", "measured fuel rate"):
    assert rule.hits(bad), bad
for good in ("right-censored (observation ended before the threshold)", "median warm-up time (reachers only)", "time-to-event estimate", "Median of reachers only (165 of 370)"):
    assert not rule.hits(good), good
a = json.load(open("summary_arrays.json", encoding="utf-8"))
blk = a["thermalSupportLedger"]
strings = []
def walk(o):
    if isinstance(o, dict):
        [walk(v) for v in o.values()]
    elif isinstance(o, list):
        [walk(v) for v in o]
    elif isinstance(o, str):
        strings.append(o)
walk(blk)
assert not [s[:80] for s in strings if rule.hits(s)]
r435 = R["M435-thermal-tte"]                                  # M435 amends the Kaplan-Meier part of the M418 rule: only the named estimate is allowed
assert r435.hits("Kaplan-Meier estimate") and r435.hits("a survival model of the warm-up") is False and not r435.hits("Kaplan-Meier (product-limit) estimate of the time to 80 C")
assert not [s[:80] for s in strings if r435.hits(s)]
bad = re.compile(r"\b(significant(?:ly)?|confirmed|robust|stable|detected|detectable|corrected|proves?|demonstrates|measured)\b", re.I)
assert not [s[:80] for s in strings if bad.search(s)]
assert any("right-censored" in s and "key-off" in s for s in blk["censoringReading"])
assert any("not identifiable" in s for s in blk["censoringReading"]) and any("not a time-to-event estimate" in s or "not a time-to-event" in s for s in blk["censoringReading"])
jsx = open("xtrail_summary.jsx", encoding="utf-8").read()
for must in ("function ThermalSupport(", "S.thermalSupportLedger", "reachers only", "cohort median not identifiable without an assumption on censoring", "selection on the outcome", "warm-start rule of this curve"):
    assert must in jsx, must
assert "penalty" not in jsx[jsx.index("function ThermalSupport("):jsx.index("function ThermalWarmupLag(")].replace("fuelPenalty", "").lower()   # the payload key is allowed in code, not in display text (M339)
stages = json.load(open("tools/ingest_stages.json", encoding="utf-8"))
ids = [x["id"] for x in (stages["stages"] if isinstance(stages, dict) else stages)]
assert "thermal_support_ledger" in ids and ids.index("thermal_support_ledger") > ids.index("refresh_raw_seasonal") and ids.index("thermal_support_ledger") > ids.index("cohort_arrays")
ci = open(".github/workflows/ci.yml", encoding="utf-8").read()
assert "test_thermal_support_ledger.py" in ci and "test_m418_wording.py" in ci
print("OK test_m418_wording")
