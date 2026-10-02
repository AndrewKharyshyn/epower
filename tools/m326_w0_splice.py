#!/usr/bin/env python3
"""M326 W0 leaf-level splice of summary_arrays.json strings (addendum analyses/M326_W0_addendum.md). Replaces ONLY the 7 declared leaf strings;
asserts the old text (or already-new text, idempotent); never touches any other key. Usage: python tools/m326_w0_splice.py [--dry-run]"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
P = os.path.join(ROOT, "summary_arrays.json")
OLD1 = 'no fuel-rate PID on the great majority of drives; MAF appears on a handful of early logs only, and MAF-derived power is an air-side estimate, not a fuel-energy measurement'
NEW1 = 'the logged fuel rate and fuel counter are calculated by the logger app (Car Scanner, air-flow based) and are present on a subset of drives; they are not an ECU fuel measurement, so fuel energy in is logged volume x assumed E10 LHV; MAF appears on a handful of early logs only, and MAF-derived power is an air-side estimate; engine brake thermal efficiency is therefore model-derived'
OLDN2 = 'Rainflow on the raw SoC trace, 1.0% amplitude floor (twice the PID quantisation step);'
NEWN2 = 'Rainflow on the raw SoC trace, cycles with a range below 1.0 pp dropped (twice the PID quantisation step);'
A = json.load(open(P, encoding="utf-8"))
changed = []
def sub(o, k, old, new, path):
    v = o[k]
    if new in v and old not in v:
        return
    assert v.count(old) == 1, (path, "old text not found exactly once")
    o[k] = v.replace(old, new); changed.append(path)
sub(A["energyPath"]["unobservable"][1], "why", OLD1, NEW1, "energyPath.unobservable[1].why")
for m in ("all", "warm", "shoulder"):
    sub(A["seasonalCharts"]["charts"]["EnergyPath"]["data"][m]["unobservable"][1], "why", OLD1, NEW1, f"seasonalCharts.EnergyPath.{m}.unobservable[1].why")
for i in (26, 27):
    sub(A["records"][i], "note", OLDN2, NEWN2, f"records[{i}].note")
sub(A["rfDodHistogram"], "methodology", "RF_FLOOR_PCT=1.0 amplitude floor", "RF_FLOOR_PCT=1.0 cycle-range floor (pp)", "rfDodHistogram.methodology")
if "--dry-run" not in sys.argv and changed:
    with open(P, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A, f, ensure_ascii=False, indent=1)
print(json.dumps({"changed": changed, "n": len(changed)}))
