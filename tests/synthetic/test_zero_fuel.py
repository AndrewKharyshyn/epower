"""M460 known-answer tests of the zero-logged-fuel share evaluator (spec analyses/M460_spec.md Rev 1.1, section 8): tools/zero_fuel.py.
(1) the four states A-D of a synthetic 1 Hz drive reproduce their hand-calculated distances (36 km/h = 0.01 km/s); (2) seconds with an unknown fuel rate are in no state, their distance is reported apart, and A + C + RPM-off-unknown equals the
RPM-off distance (the parity of gate G1); (3) a logged rate above the plausibility range (154.75 L/h) is unknown; (4) the debounce suppresses a 1 s fuel blip inside a zero-fuel run (primary) while the raw state keeps it (sensitivity);
(5) the eps threshold moves a small positive rate into the zero-fuel state; (6) the construct-validity counts (classifier motored seconds with the zero-fuel state); (7) a ratio of sums differs from the mean of ratios;
(8) day resampling is reproducible and the interval brackets the point."""
import io
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import zero_fuel as ZF

RPM, SPD, FUEL, BOOST, LOAD = "Оберти двигуна (rpm)", "[VCM] Vehicle Speed (km/h)", "Витрати палива (L/h)", "Розрахунковий наддув (bar)", "Розрахункове значення навантаження на двигун (%)"


def drive_csv(segments, speed=36.0):
    """segments = [(seconds, rpm, fuel, boost, load)] -> csv bytes with one row per second."""
    rows = []
    t0 = pd.Timestamp("2026-03-01 10:00:00")
    s = 0
    for sec, rpm, fuel, boost, load in segments:
        for _ in range(sec):
            rows.append({"time": (t0 + pd.Timedelta(seconds=s)).strftime("%H:%M:%S.%f")[:-3], RPM: rpm, SPD: speed, FUEL: fuel, BOOST: boost, LOAD: load})
            s += 1
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


KM = 0.01          # km per second at 36 km/h

# (1) four states, 20 s each (A engine off no fuel, C engine off fuel, B turning no fuel, D fuelled)
seg = [(20, 0.0, 0.0, 0.0, 0.0), (20, 0.0, 1.0, 0.0, 0.0), (20, 1500.0, 0.0, 0.0, 0.0), (20, 1500.0, 1.0, 0.0, 0.0)]
r = ZF.eval_drive(drive_csv(seg))
p = r["primary"]
assert abs(p["A"] - 20 * KM) < 0.011 and abs(p["C"] - 20 * KM) < 0.011 and abs(p["B"] - 20 * KM) < 0.011 and abs(p["D"] - 20 * KM) < 0.011, p     # state boundaries move by at most a second or two (alignment, debounce)
assert abs(p["A"] + p["B"] + p["C"] + p["D"] - 80 * KM) < 0.03 and p["offUnknownFuel"] == 0 and p["unknownRpm"] == 0
assert abs(r["evDistKm"] - (p["A"] + p["C"] + p["offUnknownFuel"])) < 1e-9                                      # G1 parity by construction on a known-fuel drive

# (2) unknown fuel seconds are in no state; the RPM-off distance is still A + C + off-unknown
seg2 = [(20, 0.0, 0.0, 0.0, 0.0), (20, 0.0, np.nan, 0.0, 0.0), (20, 1500.0, np.nan, 0.0, 0.0), (20, 1500.0, 1.0, 0.0, 0.0)]
r2 = ZF.eval_drive(drive_csv(seg2))
p2 = r2["primary"]
assert p2["offUnknownFuel"] > 15 * KM and p2["onUnknownFuel"] > 15 * KM, p2
assert abs(r2["evDistKm"] - (p2["A"] + p2["C"] + p2["offUnknownFuel"])) < 1e-9

# (3) a rate above the plausibility range is unknown
seg3 = [(30, 0.0, 154.75, 0.0, 0.0), (30, 0.0, 0.0, 0.0, 0.0)]
r3 = ZF.eval_drive(drive_csv(seg3))
assert r3["primary"]["offUnknownFuel"] > 25 * KM and r3["primary"]["A"] > 25 * KM, r3["primary"]

# (4) debounce: a 1 s fuel blip inside a zero-fuel engine-off run is suppressed (primary), kept by the raw state
seg4 = [(20, 0.0, 0.0, 0.0, 0.0), (1, 0.0, 2.0, 0.0, 0.0), (20, 0.0, 0.0, 0.0, 0.0)]
r4 = ZF.eval_drive(drive_csv(seg4))
assert r4["primary"]["C"] < 0.5 * KM < r4["raw"]["C"] + 1e-9 and r4["raw"]["C"] >= 0.5 * KM, (r4["primary"]["C"], r4["raw"]["C"])

# (5) eps: a rate of 0.2 L/h is fuelled at eps = 0 and zero-fuel at eps = 0.35
seg5 = [(30, 0.0, 0.2, 0.0, 0.0), (30, 0.0, 0.0, 0.0, 0.0)]
r5 = ZF.eval_drive(drive_csv(seg5))
assert r5["primary"]["C"] > 25 * KM and r5["eps0.35"]["C"] < 2 * KM and r5["eps0.35"]["A"] > 55 * KM, (r5["primary"], r5["eps0.35"])

# (6) construct-validity counts: classifier motored seconds (rpm > 2000, boost <= -0.7, load <= 8) with and without the zero-fuel state
seg6 = [(15, 3000.0, 0.0, -0.9, 3.0), (15, 3000.0, 1.0, -0.9, 3.0), (10, 1500.0, 1.0, 0.1, 40.0)]
r6 = ZF.eval_drive(drive_csv(seg6))
m = r6["motored"]
assert 12 <= m["sec"] <= 31 and 12 <= m["secZF"] <= 16 and m["secZF"] < m["sec"], m

# (7)+(8) ratio of sums and the day-clustered interval
rows = [{"date": "2026-03-0%d" % (1 + i % 5), "dist": d, "x": {"A": a}} for i, (d, a) in enumerate([(10.0, 5.0), (1.0, 0.9), (20.0, 2.0), (2.0, 1.9), (5.0, 2.5), (8.0, 4.0), (3.0, 1.0), (6.0, 3.0), (4.0, 2.0), (7.0, 3.5)])]
q = ZF.quantity(rows, "x", lambda s: s["A"])
pooled = 100 * sum(r["x"]["A"] for r in rows) / sum(r["dist"] for r in rows)
mean_of_ratios = 100 * np.mean([r["x"]["A"] / r["dist"] for r in rows])
assert abs(q["pct"] - pooled) < 1e-3 and abs(pooled - mean_of_ratios) > 1.0                                    # unequal distances: the mean of ratios would be wrong
assert q["nDays"] == 5 and q["ci95"] is not None and q["ci95"][0] <= q["pct"] <= q["ci95"][1]
q2 = ZF.quantity(rows, "x", lambda s: s["A"])
assert q == q2                                                                                                  # fixed seed -> reproducible
print("test_zero_fuel: all known-answer tests passed")
