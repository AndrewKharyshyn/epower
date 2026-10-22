"""M474 test: the capacity statement of the Health card is bound to the computed capacityBasis keys (point, interval, n, method range, kWh scale) and carries the audit's readings: the scale is of the logged signal, not full /
accessible capacity or SOH; it does not show whether 2.1 kWh is gross and the fitted scale usable; 5 Ah is documentary. The payload keys carry an interval and an n; the language rule fires on the affirmative claims only."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import language_gate as G
A = json.load(open("summary_arrays.json", encoding="utf-8")); cb = A["capacityBasis"]
assert cb["ahPer100"]["point"] and len(cb["ahPer100"]["bootstrapCI95"]) == 2 and cb["ahPer100"]["bootstrapCI95"][0] < cb["ahPer100"]["point"] < cb["ahPer100"]["bootstrapCI95"][1]
assert len(cb["kWhPer100"]["bootstrapCI95"]) == 2 and len(cb["ahPer100"]["methodRange"]) == 2 and cb["population"]["nDrives"] > 100 and cb["population"]["nDays"] > 50 and cb["population"]["nEvents"] > 1000
jsx = open("xtrail_summary.jsx", encoding="utf-8").read()
for needle in ("S.capacityBasis.ahPer100.point", "S.capacityBasis.kWhPer100?.point", "bootstrapCI95", "S.capacityBasis.population?.nDrives", "S.capacityBasis.population?.nDays", "methodRange",
               "not full capacity, accessible capacity or state of health", "It does not show whether 2.1 kWh is a gross capacity", "documentary reference"):
    assert needle in jsx, needle
assert "no capacity observable" not in jsx.lower()
for bad in ("the fitted scale confirms that 2.1 kWh is gross", "the fitted scale gives the usable capacity"):
    assert any(r.rid == "M474-capacity-scale-readings" and r.hits(bad) for r in G.RULES), bad
for good in ("not a measured capacity", "It does not show whether 2.1 kWh is a gross capacity and the fitted scale the usable part"):
    assert not any(r.rid == "M474-capacity-scale-readings" and r.hits(good) for r in G.RULES), good
print("OK test_capacity_narrative (scale %s Ah, %d drives, %d days)" % (cb["ahPer100"]["point"], cb["population"]["nDrives"], cb["population"]["nDays"]))
