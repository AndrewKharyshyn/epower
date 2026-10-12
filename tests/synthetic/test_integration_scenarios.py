"""M420 (audit F17) known-answer tests for tools/integration_scenarios.py: synthetic I/V series with hand-computed energies for the baseline and every single-choice scenario, the aggregation (ratio, per-drive spread,
day-cluster interval), the live-block gates (baseline reproduces the master, D1 reproduces offsetGrossSensitivity, drive set equals the Monte Carlo set, pre-registered inMonteCarlo flags, net-draw antisymmetry of the hold
variants) and the absence of any pooled field."""
import json, os, sys
import numpy as np
import pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import integration_scenarios as S

T0 = pd.Timestamp("2026-06-01 12:00:00")


def ser(times_s, vals):
    return pd.DataFrame({"t": [T0 + pd.Timedelta(seconds=float(x)) for x in times_s], "v": np.asarray(vals, float)})


def iv(times_s, p_kw, v_volts=400.0, v_times=None):
    """Current series (charge-positive) giving the discharge-positive power p_kw at constant V."""
    I = ser(times_s, -(np.asarray(p_kw, float) * 1000.0 / v_volts))
    vt = times_s if v_times is None else v_times
    return I, ser(vt, np.full(len(vt), v_volts))


H = 1.0 / 3600.0
close = lambda a, b, tol=1e-9: abs(a - b) < tol
# 1. constant power: every interpolation rule gives the same energy
I, V = iv([0, 1, 2, 3], [10, 10, 10, 10])
for kw in ({}, {"mode": "left"}, {"mode": "right"}):
    d, c = S.integrate(I, V, **kw)
    assert close(d, 10 * 3 * H) and c == 0.0, (kw, d, c)
# 2. linear ramp 0..10 kW over four 1 s intervals: trapezoid 20, left-hold 15, right-hold 25 (kW s)
I, V = iv([0, 1, 2, 3, 4], [0, 2.5, 5, 7.5, 10])
assert close(S.integrate(I, V)[0], 20 * H) and close(S.integrate(I, V, mode="left")[0], 15 * H) and close(S.integrate(I, V, mode="right")[0], 25 * H)
# 3. discharge-to-charge crossing (+10 to -10 kW in 1 s): linear split 2.5 / 2.5, left-hold 10 discharge, right-hold 10 charge (kW s)
I, V = iv([0, 1], [10, -10])
d, c = S.integrate(I, V)
assert close(d, 2.5 * H) and close(c, 2.5 * H)
d, c = S.integrate(I, V, mode="left"); assert close(d, 10 * H) and c == 0.0
d, c = S.integrate(I, V, mode="right"); assert d == 0.0 and close(c, 10 * H)
# 4. an 8 s gap at 10 kW: cap 5 s -> 5 s, no bridging -> 0 s, cap 10 s -> 8 s, cap 3 s -> 3 s, cap 2 s -> 2 s
I, V = iv([0, 8], [10, 10])
assert close(S.integrate(I, V)[0], 10 * 5 * H) and S.integrate(I, V, no_bridge=True)[0] == 0.0
assert close(S.integrate(I, V, cap_s=10)[0], 10 * 8 * H) and close(S.integrate(I, V, cap_s=3)[0], 10 * 3 * H) and close(S.integrate(I, V, cap_s=2)[0], 10 * 2 * H)
I, V = iv([0, 5], [10, 10])                        # an interval of exactly 5 s is not "longer than 5 s": no-bridging keeps it
assert close(S.integrate(I, V, no_bridge=True)[0], 10 * 5 * H)
# 5. voltage samples 0.2 s after the current samples: nearest matches all four (3 s), backward-only drops the first current sample (2 s)
I, V = iv([0, 1, 2, 3], [10, 10, 10, 10], v_times=[0.2, 1.2, 2.2, 3.2])
assert close(S.integrate(I, V)[0], 10 * 3 * H) and close(S.integrate(I, V, direction="backward")[0], 10 * 2 * H)
I, V = iv([0, 1, 2, 3], [10, 10, 10, 10], v_times=[0.8, 1.8, 2.8, 3.8])      # voltage 0.8 s after the first current sample only: at 500 ms that sample drops (3 matched samples, 2 s), at 1000 ms all four match (3 s)
assert close(S.integrate(I, V, tol_ms=1000)[0], 10 * 3 * H) and close(S.integrate(I, V, tol_ms=500)[0], 10 * 2 * H)
# 6. offset: the gross integral moves for a one-sided signal (discharge down for a discharge signal, charge up for a charge signal)
I, V = iv([0, 1, 2, 3], [10, 10, 10, 10]); d, c = S.integrate(I, V, offset_a=1.0)
assert close(d, (25 - 1) * 0.4 * 3 * H) and c == 0.0
I, V = iv([0, 1, 2, 3], [-10, -10, -10, -10]); d, c = S.integrate(I, V, offset_a=1.0)
assert d == 0.0 and close(c, (25 + 1) * 0.4 * 3 * H)
# 7. gap inventory
I, V = iv([0, 1, 12, 13, 50], [10] * 5)
g = S.gap_inventory(I, V)
assert (g["n5"], g["n10"], g["n30"]) == (2, 2, 1) and close(g["s5"], 11 + 37) and close(g["excessBeyondCapS"], 6 + 32)

# 8. aggregation: two days, two drives each; hand-computed ratio, spread and interval ordering
scen = [("X1", "alignment", "estimator choice", "test", {}, True), ("D2", "offset", "data process", "test", {}, True)]
mk = lambda day, b, x: {"file": day + str(b), "day": day, "e": {"S0": (b, 0.0), "X1": (x, 0.0), "D2": (x, 0.0)}}
drives = [mk("2026-06-01", 1.0, 1.1), mk("2026-06-01", 2.0, 2.0), mk("2026-06-02", 3.0, 2.7), mk("2026-06-02", 0.05, 0.0)]
rows, base = S.aggregate(drives, scen)
r = rows[0]
assert close(base["grossThroughputKwh"], 6.05) and base["nDays"] == 2 and base["nDrives"] == 4
assert close(r["grossThroughputKwh"], 5.8) and close(r["ratioToBaseline"], 5.8 / 6.05, 1e-6) and close(r["shiftKwh"], -0.25)
assert r["perDriveRatio"]["nDrives"] == 3 and r["perDriveRatio"]["nUndefined"] == 1 and close(r["perDriveRatio"]["median"], 1.0) and close(r["perDriveRatio"]["min"], 0.9) and close(r["perDriveRatio"]["max"], 1.1)
lo, hi = r["dayVariabilityOfRatio95"]; assert lo <= r["ratioToBaseline"] <= hi
assert rows[1]["dayVariabilityOfRatio95"] is None and "deterministic" in rows[1]["dayVariabilityNote"]      # D2 / D3 carry no variability interval
assert S.ratio_ci([1.1, 2.0], [1.0, 2.0]) == S.ratio_ci([1.1, 2.0], [1.0, 2.0])                                # seeded: reproducible

# 9. live block
A = json.load(open("summary_arrays.json", encoding="utf-8"))
B = A["integrationScenarios"]
ck = B["checks"]
assert all(v["pass"] for v in ck.values()) and set(ck) == {"baselineReproducesMaster", "d1ReproducesOffsetGrossSensitivity", "driveSetMatchesMonteCarlo"}
assert B["baseline"]["nDrives"] == int(pd.read_csv("drive_master.csv", low_memory=False)["gross_discharge_kwh"].notna().sum()) and not B["excludedDrives"]
rows = {x["id"]: x for x in B["scenarios"]}
assert list(rows) == [x[0] for x in S.SCENARIOS]
for sid, *_rest, mc in S.SCENARIOS:
    assert rows[sid]["inMonteCarlo"] == mc, sid
assert [rows[k]["inMonteCarlo"] for k in ("A0", "A1", "A2", "A3", "B1", "B2", "C1", "C3")] == [True, True, True, False, False, False, False, "partial"]
assert rows["D2"]["dayVariabilityOfRatio95"] is None and rows["D3"]["dayVariabilityOfRatio95"] is None and rows["D1"]["dayVariabilityOfRatio95"] is not None
assert abs(rows["B1"]["netDrawShiftKwh"] + rows["B2"]["netDrawShiftKwh"]) < 5e-4, "net draw: the left- and right-hold shifts are exactly opposite (trapezoid net = mean of the two)"
for x in B["scenarios"]:
    assert close(x["shiftDischargeKwh"] + x["shiftChargeKwh"], x["shiftKwh"], 5e-4) and x["nDrives"] == B["baseline"]["nDrives"] and x["nDays"] == B["baseline"]["nDays"]
    pr = x["perDriveRatio"]; assert pr["min"] <= pr["p10"] <= pr["median"] <= pr["p90"] <= pr["max"]
    if x["dayVariabilityOfRatio95"]:
        assert x["dayVariabilityOfRatio95"][0] <= x["ratioToBaseline"] <= x["dayVariabilityOfRatio95"][1]
gi = B["baseline"]["gapInventory"]
assert gi["n5"] >= gi["n10"] >= gi["n30"] > 0
assert {x["id"] for x in B["carriedStudies"]} == {"E-fastToSlow", "E-fastToSlower", "F-quantisation", "H-midpoint"} and {x["id"] for x in B["capacityReferences"]} == {"G1", "G2"}
assert all(x.get("ratioCi") is None for x in B["capacityReferences"])
bad = []                                              # no pooled field anywhere (recursive key check); the Monte Carlo is a reference block, not a row


def walk(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            if any(w in k.lower() for w in ("total", "combined", "pooled", "union")):
                bad.append(path + "/" + k)
            walk(v, path + "/" + k)
    elif isinstance(o, list):
        [walk(v, path) for v in o]


walk(B)
assert not bad, bad
assert "monteCarlo" in B and all(x["id"] != "MC" for x in B["scenarios"])
print("OK test_integration_scenarios")
