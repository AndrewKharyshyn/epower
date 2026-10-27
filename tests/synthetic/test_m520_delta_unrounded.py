"""M520 Part B known-answer test: deltaVsPrimary is the difference of the UNROUNDED fleet figures, not of the three-decimal headlines."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import compute_summary_arrays as cs

rows = [{"fuelL": 1.234567, "distKm": 10.123457, "dE_kWh": 0.31}, {"fuelL": 2.000001, "distKm": 33.3333, "dE_kWh": -0.2}]
u = cs._hf_unrounded(rows)
fuel, dist, dE = 1.234567 + 2.000001, 10.123457 + 33.3333, 0.31 - 0.2
assert abs(u["rawFleetL100"] - fuel / dist * 100) < 1e-12
assert abs(u["socBalancedFleetL100"] - (fuel - dE / (0.30 * cs._HF_LHV)) / dist * 100) < 1e-12
assert u["rawFleetL100"] != round(u["rawFleetL100"], 3)                                           # the helper does not round

A = json.load(open("summary_arrays.json", encoding="utf-8"))["socBalancedFuel"]
s, d = A["allAccumulatorSensitivity"], A["allAccumulatorSensitivity"]["deltaVsPrimary"]
rounded_diff = round(s["socBalancedFleetL100"] - A["socBalancedFleetL100"], 6)
assert abs(d["socBalancedFleetL100"] - rounded_diff) <= 0.001 + 1e-9                               # consistent with the displayed headlines within their rounding
assert d["socBalancedFleetL100"] != rounded_diff or abs(rounded_diff) < 1e-9, "delta still equals the difference of the rounded headlines"
assert s["socBalancedFleetL100"] == round(s["socBalancedFleetL100"], 3) and A["socBalancedFleetL100"] == round(A["socBalancedFleetL100"], 3)   # headlines stay rounded displays
print("test_m520_delta_unrounded: OK")
