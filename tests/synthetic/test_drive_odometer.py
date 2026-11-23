"""M752 known-answer tests (analyses/M752_spec.md Rev 2 and 2.1): conflict and non-numeric rows dropped without a global monotone filter; interpolation at an off-grid time; the 35 s cap,
holes and outside-span reasons; the flat-bracket rule; E_int is a lower and E_br an upper bracket on a planted parked-car drive; E_near and the +16 s shift; a local odometer jump makes a drive
unavailable; planted bias recovered with the right sign, planted null contains zero; support floor; verdict wording at the margins; anchor arithmetic; control V0 stops on a wrong gain; bootstrap
reproducible; optional-stage skip. No cloud store needed."""
import os, sys, tempfile
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import drive_odometer as D

tmp = tempfile.mkdtemp()
assert D.main(["--store", os.path.join(tmp, "nostore"), "--out-dir", tmp]) == 0          # optional stage: skipped, exit 0

# rows: conflicts and non-numeric dropped; no global monotone filter (a 60 km level excursion keeps its rows); excursion and negative step counted
rows = [(0, 100.0), (30, 100.5), (60, None), (90, 101.0), (120, 40.0), (150, 40.4), (180, 40.8), (210, 101.5)]
ts, vs, cnt = D.accepted_odo(rows, conflict_t=[30])
assert list(ts) == [0, 90, 120, 150, 180, 210] and cnt["conflict"] == 1 and cnt["nonnumeric"] == 1 and cnt["accepted"] == 6
assert cnt["negativeSteps"] == 1 and cnt["levelExcursions"] == 1 and abs(cnt["maxExcursionKm"] - 61.0) < 1e-9

# interpolation at an off-grid time; cap, hole, outside span; flat-bracket rule
ts, vs = np.array([100.0, 130.0, 160.0, 400.0, 4000.0, 100000.0]), np.array([10.0, 10.5, 11.0, 12.0, 12.0, 12.0])
v, age, why = D.odo_at(115.0, ts, vs, "int")
assert abs(v - 10.25) < 1e-9 and why == "ok" and age == 15.0
assert D.odo_at(50.0, ts, vs, "int")[2] == "outside_span" and D.odo_at(200000.0, ts, vs, "int")[2] == "outside_span"
assert D.odo_at(300.0, ts, vs, "int")[2] == "no_row_within_cap"                         # rows at 160 and 400 differ by 1 km over 240 s
v, age, why = D.odo_at(2000.0, ts, vs, "int")                                          # rows at 400 and 4000 are flat (parked): exact whatever the gap
assert v == 12.0 and why == "flat"
assert D.odo_at(50000.0, ts, vs, "int")[2] == "flat"                                   # 96,000 s gap but flat
ts2, vs2 = np.array([0.0, 100000.0]), np.array([5.0, 9.0])
assert D.odo_at(50000.0, ts2, vs2, "int")[2] == "hole"                                 # gap of 24 h or more and not flat
# E_near and the clock shift
assert D.odo_at(120.0, ts, vs, "near")[0] == 10.5 and D.odo_at(115.0, ts, vs, "near")[0] in (10.0, 10.5)
assert D.odo_at(500.0, ts, vs, "near")[2] == "no_row_within_cap" and D.odo_at(500.0, ts, vs, "near60")[2] == "no_row_within_cap"
vshift = D.odo_at(146.0, ts, vs, "int", shift=16.0)[0]                                 # OBD time 146 reads cloud time 130
assert abs(vshift - 10.5) < 1e-9

# planted parked-car drive: parked at ODO 100 until t0 = 1010, 36 km/h (0.01 km/s) until t1 = 1110, parked after; cloud rows every 30 s while awake
t_rows = np.arange(940.0, 1161.0, 30.0)
odo = 100.0 + 0.01 * np.clip(t_rows - 1010.0, 0, 100.0)
true_dist = 1.0
ep = D.drive_endpoints(1010.0, 1110.0, t_rows, odo)
d_int, d_br = ep["E_int"]["dist"], ep["E_br"]["dist"]
# interpolation across the stop and the start under-counts (the car is parked at both edges): 0.8667 km; the window-extending bracket is exact here because the bracket rows are parked
assert abs(d_int - 13.0 / 15.0) < 1e-6 and d_int < true_dist and d_br >= true_dist - 1e-9 and d_br > d_int, (d_int, d_br)
# a row INSIDE the moving part extends E_br above the truth: rows at 1020 and 1100 (moving) bracket a start at 1030 and an end at 1090
t2 = np.array([1000.0, 1020.0, 1040.0, 1080.0, 1100.0, 1120.0]); o2 = 100.0 + 0.01 * np.clip(t2 - 1010.0, 0, 100.0)
e2 = D.drive_endpoints(1030.0, 1090.0, t2, o2)
assert e2["E_br"]["dist"] > 0.6 + 1e-9 and e2["E_int"]["dist"] <= 0.6 + 1e-9, (e2["E_br"]["dist"], e2["E_int"]["dist"])
# a local jump inside the window makes every estimator unavailable
odo_j = odo.copy()
odo_j[5:] += 60.0
epj = D.drive_endpoints(1010.0, 1110.0, t_rows, odo_j)
assert all(e["dist"] is None and e["reasonStart"] == "odometer_jump" for e in epj.values())
assert D.jump_in_window(1010.0, 1110.0, t_rows, odo) is False
# an upward step that implies more than 180 km/h counts as a jump too
assert D.jump_in_window(0.0, 60.0, np.array([0.0, 30.0, 60.0]), np.array([10.0, 10.3, 13.0])) is True

# planted bias recovered with the right sign; planted null contains zero; support floor; reproducible bootstrap
rng = np.random.default_rng(5)
n = 120
days = np.array(["2026-07-%02d" % (1 + i % 28) for i in range(n)])
logged = rng.uniform(2.5, 30.0, n)
bias = pd.DataFrame({"delta": 0.11 + rng.normal(0, 0.05, n), "logged": logged, "day": days})
s = D.summarise(bias, 300)
assert s["nDrives"] == n and s["median"]["ci95"][0] > 0.09 and s["relative"]["ci95"][0] > 0 and s["relative"]["est"] > 0
# a 0.11 km difference on drives of 2.5 to 30 km is about 0.7 %: inside both margins; a 0.20 km difference is about 1.3 %: beyond +-1 % but inside +-3 %
assert D.verdict(s, 0.01) == "consistent within +-1 %" and D.verdict(s, 0.03) == "consistent within +-3 %"
big_bias = pd.DataFrame({"delta": 0.20 + rng.normal(0, 0.03, n), "logged": logged, "day": days})
sb = D.summarise(big_bias, 300)
assert D.verdict(sb, 0.01).startswith("aggregate relative difference") and D.verdict(sb, 0.03).startswith("consistent within +-3"), (D.verdict(sb, 0.01), D.verdict(sb, 0.03))
noise = rng.normal(0, 0.05, n)
null = pd.DataFrame({"delta": noise - noise.mean(), "logged": logged, "day": days})                # exactly zero aggregate difference
sn = D.summarise(null, 300)
assert abs(sn["relative"]["est"]) < 1e-9 and sn["relative"]["ci95"][0] < 0 < sn["relative"]["ci95"][1] and D.verdict(sn, 0.01) == "consistent within +-1 %"
small = D.summarise(bias.iloc[:15], 100)
assert "relative" not in small and small["status"].startswith("not estimable") and D.verdict(small) == "not estimable at this support"
few_days = D.summarise(pd.DataFrame({"delta": np.zeros(40), "logged": np.ones(40) * 5, "day": ["d%d" % (i % 4) for i in range(40)]}), 100)
assert few_days["status"].startswith("not estimable")
b1 = D.boot_stats(bias["delta"], bias["logged"], bias["day"], 50, 42)
b2 = D.boot_stats(bias["delta"], bias["logged"], bias["day"], 50, 42)
assert b1 == b2
big = pd.DataFrame({"delta": np.full(60, 0.4), "logged": np.full(60, 3.0), "day": ["2026-08-%02d" % (1 + i % 28) for i in range(60)]})
assert "median |difference|" in D.verdict(D.summarise(big, 100), 0.5)
assert D.stratum_of(1.99) == "below2km" and D.stratum_of(2.0) == "2to10km" and D.stratum_of(10.0) == "10kmplus"

# anchor: cloud last ODO plus the logged part of drives after the last row (a drive that straddles it counts proportionally)
a = D.anchor(48110.0, 48104.8, 1000.0, [(900.0, 1100.0, 2.0), (1200.0, 1300.0, 3.6), (500.0, 600.0, 9.0)])
assert abs(a["loggedKmAfterLastRow"] - (1.0 + 3.6)) < 1e-9 and abs(a["differenceKm"] - (48110.0 - 48104.8 - 4.6)) < 1e-6 and a["withinTolerance"] and a["n"] == 1
assert D.anchor(48110.0, 48100.0, 1000.0, [])["withinTolerance"] is False

# control V0
try:
    D.check_gain(np.array([0.0, 1.0]), np.array([100.0, 13000.0]))
    raise SystemExit("a wrong gain must stop")
except D.Stop:
    pass
assert abs(D.check_gain(np.array([0.0, 1.0]), np.array([34819.76953125, 34819.76953125 + 13285.0390625])) - 13285.0390625) < 1e-9
print("test_drive_odometer: OK")
