"""M658 (N-06, spec analyses/M657_spec.md Rev 1.1): known-answer test of tools/n06_bms_power_map.aggregate on a constructed drive set.
Input direction, kW era: constant reported values per pack-temperature bin that rise with temperature (10 C: 40, 15 C: 45, 20 C: 50, 25 C: 55 kW), a thin bin (30 C, 3 drives) that must be 'not shown',
a bin 35 C with 12 drives all at the logged maximum. Output direction: all at the logged maximum. Checks: medians, logged-maximum share, support ladder, degenerate intervals, estimator flag,
at-the-logged-maximum flags, contiguity and monotone wording, the I x V pair of shares, deterministic bootstrap. Run: python tests/synthetic/test_m658_bms_power_map.py"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import n06_bms_power_map as N

DAYS = ["2026-10-%02d" % d for d in range(1, 13)]           # 12 days
stats, meta = {}, {}


def add(fname, day, period, cells_in, cells_out, iv=None):
    d_in = {"era": "kW", "nSamples": 0, "nDropped": 0, "droppedSeconds": 0.0, "seconds": 0.0, "nOnGrid": 0, "cells": {}, "medianGapS": 1.0, "maxValue": 63.75,
            "secondsAtDriveMax": 0.0, "secondsAtOrAboveFlag": 0.0, "longestRunAtDriveMaxS": 0.0, "nearMaxValues": [63.75, 63.75000000000001]}
    d_out = json.loads(json.dumps(d_in))
    for tgt, cells in ((d_in, cells_in), (d_out, cells_out)):
        for key, val in cells.items():
            tgt["cells"][key] = {"s": 1000.0, "n": 1000, "h": {"%.2f" % val: 1000.0}}
            tgt["seconds"] += 1000.0; tgt["nSamples"] += 1000; tgt["nOnGrid"] += 1000
            if val >= 63.70:
                tgt["secondsAtDriveMax"] += 1000.0; tgt["secondsAtOrAboveFlag"] += 1000.0; tgt["longestRunAtDriveMaxS"] = 1000.0
    if iv:
        d_in["ivCheck"] = iv
    stats[fname] = {"file": fname, "dir": {"input": d_in, "output": d_out}}
    meta[fname] = {"date": day, "period": period}


n = 0
for tb, val in ((10, 40.0), (15, 45.0), (20, 50.0), (25, 55.0)):
    for i in range(12):                                         # 12 drives, one per day, per bin
        n += 1
        add("f%03d.csv" % n, DAYS[i], 0.5 if i % 2 == 0 else 2.0, {"%d|60-63" % tb: val}, {"%d|60-63" % tb: 63.75},
            iv={"atMax": {"s": 0.0, "exceed": 0.0}, "belowMax": {"s": 100.0, "exceed": 10.0}, "chargeAbove50kWSeconds": 50.0, "pairedSeconds": 100.0})
for i in range(3):                                              # thin bin
    n += 1
    add("f%03d.csv" % n, DAYS[i], 0.5, {"30|60-63": 58.0}, {"30|60-63": 63.75})
for i in range(12):                                             # all at the logged maximum
    n += 1
    add("f%03d.csv" % n, DAYS[i], 2.0, {"35|60-63": 63.75}, {"35|60-63": 63.75},
        iv={"atMax": {"s": 200.0, "exceed": 20.0}, "belowMax": {"s": 0.0, "exceed": 0.0}, "chargeAbove50kWSeconds": 150.0, "pairedSeconds": 200.0})

B = N.aggregate(stats, meta, nb=400)
ev = B["eras"]["kW"]["input"]
c = ev["cells"]
for tb, val in ((10, 40.0), (15, 45.0), (20, 50.0), (25, 55.0)):
    r = c["%d|60-63" % tb]
    assert r["status"] == "supported" and r["nDrives"] == 12 and r["nDays"] == 12 and abs(r["essDays"] - 12.0) < 1e-6, (tb, r)
    assert r["median"] == val and r["p5"] == val and r["p95"] == val and r["maxShare"] == 0.0 and r["belowMaxMedian"] == val, (tb, r)
    assert r["ci95"]["median"] == [val, val] and "median" in r["degenerateIntervals"] and r["medianOfMedians"] == val and r["estimatorDependent"] is False
    assert r["medianAtLoggedMaximum"] is False
assert c["30|60-63"]["status"] == "not shown" and "fewer than 10 drives" in c["30|60-63"]["reason"] and "median" not in c["30|60-63"]
r = c["35|60-63"]
assert r["status"] == "supported" and r["maxShare"] == 1.0 and r["medianAtLoggedMaximum"] is True and r["p95AtLoggedMaximum"] is True and r["belowMaxMedian"] is None
# ladder (SoC 55-66 pooled) and range / contiguity / monotone wording
lad = ev["ladderSoc55to66"]
assert [lad[str(t)]["status"] for t in (10, 15, 20, 25, 30, 35)] == ["supported"] * 4 + ["not shown", "supported"]
assert ev["supportedPackTempOuterBinEdgesC"] == [10, 40] and ev["supportedPackTempBinsC"] == [10, 15, 20, 25, 35] and ev["supportedBinsContiguous"] is False    # 30 C is a gap
assert "no ordered relation is established" in ev["monotone"]["belowMaxMedian"], ev["monotone"]
# the same data without the gap bin: contiguous 10..25 increasing
stats2 = {f: s for f, s in stats.items() if not any(k.startswith("30|") or k.startswith("35|") for k in s["dir"]["input"]["cells"])}
B2 = N.aggregate(stats2, meta, nb=400)
e2 = B2["eras"]["kW"]["input"]
assert e2["supportedBinsContiguous"] is True and e2["monotone"]["belowMaxMedian"] == "kW era, input direction, SoC 55-66 %: below-maximum median is higher in each warmer supported bin (10, 15, 20, 25 C, lower bin edges); descriptive, not a temperature effect", e2["monotone"]
assert "no ordered relation is established" in e2["monotone"]["maxShare"], "ties (all 0) are not ordered"
# output direction: everything at the logged maximum
out = B["eras"]["kW"]["output"]["cells"]["10|60-63"]
assert out["maxShare"] == 1.0 and out["medianAtLoggedMaximum"] is True
# I x V pair of shares (limit below the maximum: 10 / 100 per drive; at the maximum: 20 / 200)
iv = ev["saturation"]["loggedPowerAboveReportedLimit"]
assert iv["limitBelowMaximum"]["share"] == 0.1 and iv["limitAtLoggedMaximum"]["share"] == 0.1, iv
assert ev["saturation"]["pattern"] == "maximum absent in some supported bin" and ev["saturation"]["supportedCellsWithMaximum"] == 1
# distinct values are counted on the grid, not as floats; fixed texts present
assert ev["saturation"]["distinctValuesWithin1kWBelowMaximum"] == 1 and "notIndependentlyReproduced" in B and len(B["reading"]) == 6 and "power" in iv
# determinism and regimes
assert json.dumps(N.aggregate(stats, meta, nb=400), sort_keys=True) == json.dumps(B, sort_keys=True)
assert ev["cadenceRegimeSensitivity"]["fast"]["nDrives"] + ev["cadenceRegimeSensitivity"]["slow"]["nDrives"] == len(stats)
# falsification: a map whose supported cells cover too little channel time says so
few = {f: s for f, s in list(stats.items())[:5]}
assert "no map is shown" in N.aggregate(few, meta, nb=100)["eras"]["kW"]["input"].get("coverageFalsification", "")
# bins and bands
assert N.t_bin(12.3) == 10 and N.t_bin(-0.1) == -5 and N.soc_band(39.9) == "<40" and N.soc_band(40) == "40-50" and N.soc_band(72) == "72-100" and N.soc_band(100) == "72-100"
# language rule and stage wiring
import language_gate as G
rule = {r.rid: r for r in G.RULES}["M658-bms-map-wording"]
for bad in ("the BMS limited regeneration at 5 C", "this is the true limit", "the battery limits charging", "regenerative acceptance falls", "value caused by the cold"):
    assert rule.hits(bad), bad
for good in ("BMS-reported possible power at the logged maximum", "descriptive, not a capability claim"):
    assert not rule.hits(good), good
ids = [s["id"] for s in json.load(open("tools/ingest_stages.json", encoding="utf-8"))["stages"]]
assert ids.index("signal_validity") < ids.index("bms_power_map") < ids.index("stamp_basis")
assert "bms_map_cache/" in open(".gitignore", encoding="utf-8").read()
print("PASS test_m658_bms_power_map")
