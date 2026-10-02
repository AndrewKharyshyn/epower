#!/usr/bin/env python3
"""M334 exact-string leaf edit of summary_arrays.json (spec analyses/M334_spec.md rev 2): seasonalCharts.charts.ThermalFuelPenalty.statisticalUnit wording
('penalty' -> 'association'; no reproducing builder text was found in the repository, so the carried leaf is edited here only). Idempotent; asserts old/new text;
touches no other string.  Usage: python tools/m334_splice.py [--dry-run]"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARR = os.path.join(ROOT, "summary_arrays.json")
OLD = ("cold-start (coolant<60C) fuel-accumulator penalty: trip-level naive ratio, matched-operating-point combustion penalty, matched-speed duty-cycle, idle L/hr, "
       "continuous coolant/oil-temperature covariate model")
NEW = ("cold-start (coolant<60C) fuel-accumulator association: trip-level naive ratio, matched-operating-point fuel-rate association, matched-speed duty-cycle, idle L/hr, "
       "continuous coolant/oil-temperature covariate model")
A = json.load(open(ARR, encoding="utf-8"))
c = A["seasonalCharts"]["charts"]["ThermalFuelPenalty"]
changed = []
if c["statisticalUnit"] == OLD:
    c["statisticalUnit"] = NEW
    changed.append("seasonalCharts.charts.ThermalFuelPenalty.statisticalUnit")
else:
    assert c["statisticalUnit"] == NEW, c["statisticalUnit"]
# GTR status table row (carried block, no builder): the fuel flow is logged/app-calculated, not an 'ECU fuel-flow PID' measurement (Director review: contradicted the banner)
row = A["generatorTractionRecon"]["audit"][0]
OLD_Q, NEW_BASIS = "Fuel flow", "logger-app-calculated fuel rate (L/h) and counter; coverage and definition are in the Fuel-tab banner"
if row["q"] == OLD_Q and row["status"] == "measured":
    assert row["basis"].startswith("ECU fuel-flow PID"), row["basis"]
    row["status"], row["basis"] = "logged", NEW_BASIS
    changed.append("generatorTractionRecon.audit[0]")
else:
    assert row["q"] == OLD_Q and row["status"] == "logged" and row["basis"] == NEW_BASIS, row
if "--dry-run" not in sys.argv and changed:
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A, f, ensure_ascii=False, indent=1)
print(json.dumps({"changed": changed, "n": len(changed)}))
