"""M641 known-answer tests (analyses/M641_spec.md Rev 1): policy interval rules, the crossing-aware split, support classes, payload invariants."""
import json, os, sys
import numpy as np
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools")); sys.path.insert(0, REPO)
import m641_energy_ladder as L

# constant 10 kW discharge, intervals 1, 2, 4, 8 s (first interval 0)
dt = np.array([0.0, 1.0, 2.0, 4.0, 8.0]); P = np.full(5, 10.0)
def gross(name_val):
    d = L.policy_dt(dt, name_val); disc, chg = L._split(d / 3600.0, P); return disc, chg, d.sum()
d5, c5, s5 = gross(("cap5", 5.0)); assert abs(d5 - 10.0 * (1 + 2 + 4 + 5) / 3600.0) < 1e-12 and c5 == 0.0 and s5 == 12.0          # the 8 s interval is capped at 5 s
d2, _, s2 = gross(("drop2.5", 2.5)); assert abs(d2 - 10.0 * (1 + 2) / 3600.0) < 1e-12 and s2 == 3.0                                # longer than 2.5 s adds nothing
dn, _, sn = gross(("capNone", np.inf)); assert abs(dn - 10.0 * 15 / 3600.0) < 1e-12 and sn == 15.0
d4, _, _ = gross(("drop4", 4.0)); assert abs(d4 - 10.0 * 7 / 3600.0) < 1e-12                                                       # an interval equal to the threshold counts
# crossing: +10 kW then -10 kW over 1 s: discharge and charge are each d*p^2/(2*(|p0|+|p1|)) = 1/3600*100/40 kWh
disc, chg = L._split(np.array([0.0, 1.0 / 3600.0]), np.array([10.0, -10.0]))
assert abs(disc - 100 / 40 / 3600.0) < 1e-12 and abs(chg - 100 / 40 / 3600.0) < 1e-12
# net preserved by the split (non-crossing): charge power gives charge only
disc, chg = L._split(np.array([0.0, 2.0 / 3600.0]), np.array([-6.0, -6.0])); assert disc == 0.0 and abs(chg - 12 / 3600.0) < 1e-12
# classes
assert L.klass(0.95) == ">=0.9" and L.klass(0.85) == "0.8-0.9" and L.klass(0.75) == "0.7-0.8" and L.klass(0.2) == "<0.7"

A = json.load(open(os.path.join(REPO, "summary_arrays.json"), encoding="utf-8"))
E = A["energySupportLadder"]; P_ = E["policies"]
assert abs(P_["cap5"]["grossKwh"] - A["energyUncertaintyMC"]["grossThroughputMC"]["nominalReleasedThroughputKwh"]) < 0.01 and P_["cap5"]["shareOfPublished"] == 1.0
assert P_["drop2.5"]["grossKwh"] < P_["drop3.5"]["grossKwh"] < P_["drop5"]["grossKwh"] < P_["drop10"]["grossKwh"] <= P_["cap5"]["grossKwh"] + 1 and P_["drop1.6"]["grossKwh"] < P_["drop2.5"]["grossKwh"] < P_["cap5"]["grossKwh"] < P_["capNone"]["grossKwh"]
assert all(P_[k]["nDrives"] == 651 and P_[k]["nDays"] > 100 for k in P_) and "no interval" in E["kind"] and "not an error bar or an uncertainty interval" in E["meaning"]
assert sum(E["supportClasses"].values()) == 651 == len(E["perDriveTag"]) and E["coverage"]["drivesWithoutIntegral"] == 14 and "not an estimate of their energy" in E["coverage"]["arithmeticScalingLabel"]
assert "not a coverage or confidence interval" in A["energyUncertaintyMC"]["labelNumericalSensitivity"]
import energy_uncertainty_mc as EM
assert EM.NUMERICAL_SENSITIVITY_LABEL == A["energyUncertaintyMC"]["labelNumericalSensitivity"]
import language_gate as LG
assert "M641-energy-ladder-wording" in LG.scan_text("The ladder is an error bar on the total.") and not LG.scan_text("It is not an error bar or an uncertainty interval, and no interval is drawn.")
print("PASS test_m641_energy_ladder")
