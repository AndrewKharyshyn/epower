"""M768 known-answer tests (analyses/M768_spec.md Rev 3): tools/grade_energy_flows.py: step windows equal the M757 build_steps (same selection and values), the master's zero-crossing-aware directional charge integral,
step charge integrals and the per-drive reconciliation, the three-class estimators (class means, contrasts, speed standardisation, minimum detectable difference), a planted slope, misclassification attenuation and the
consensus-class partial restoration, the reading rule with its numeric placebo condition, the support floors and the privacy scan. No real data is needed."""
import os, sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import dem_step_grade as dsg
import dem_crosscheck as X
import grade_energy_flows as E
import odometer_jump_audit as J


class FlatDem:
    """A planted DEM: height = 100 + 3 * latitude offset (a plane), for step-window equality tests."""
    def height(self, lat, lon):
        lat = np.atleast_1d(np.asarray(lat, float))
        return 100.0 + 3000.0 * (lat - 50.0)


# build_steps_win equals dsg.build_steps on every shared key (same selection, same values)
rng = np.random.default_rng(1)
t = np.arange(0.0, 900.0, 1.0)
v = 15.0 + 3.0 * np.sin(t / 40.0)
obd = {"t": t, "v": v, "dt": np.ones_like(t), "P": 20.0 * np.sin(t / 25.0)}
ft = np.arange(10.0, 880.0, 40.0)
flat = 50.0 + np.cumsum(np.full(len(ft), 0.0004))
flon = np.full(len(ft), 30.0)
rows_a, drop_a = dsg.build_steps(obd, ft, flat, flon, FlatDem())
rows_b, drop_b = E.build_steps_win(obd, ft, flat, flon, FlatDem())
assert len(rows_a) == len(rows_b) > 5 and drop_a == drop_b
for ra, rb in zip(rows_a, rows_b):
    for k in (k for k in ra if k in rb):
        assert (np.isnan(ra[k]) and np.isnan(rb[k])) or ra[k] == rb[k], k
    assert rb["b"] - rb["a"] == rb["T_s"] and rb["a"] >= 10.0 + dsg.PRIMARY_SHIFT

# the master's directional integration: a +10 kW to -10 kW second has 0.00138889 kWh of gross activity (M229); non-crossing intervals are the trapezoid
disc, chg, dth = E.directional_integrals([0.0, 1.0], [10.0, -10.0])
assert abs(disc[1] + chg[1] - 0.00138889) < 1e-8 and abs(disc[1] - chg[1]) < 1e-12
disc2, chg2, _ = E.directional_integrals([0.0, 1.0, 2.0], [-20.0, -20.0, -10.0])
assert abs(chg2.sum() - ((20 + 20) / 2 + (20 + 10) / 2) / 3600.0) < 1e-12 and disc2.sum() == 0.0
# capped integration step across a logging gap
d3, c3, _ = E.directional_integrals([0.0, 100.0], [-36.0, -36.0], dt_cap=5.0)
assert abs(c3.sum() - 36.0 * 5.0 / 3600.0) < 1e-12

# step charge integrals from planted arrays: engine off below 300 rpm, on above 400; the master engine-off (400) and the generator share
ts = np.arange(0.0, 101.0, 1.0)
ca = {"ts": ts, "disc": np.zeros_like(ts), "chg": np.full_like(ts, 0.001), "rpm": np.where(ts < 50, 0.0, 800.0), "pure": None, "soc_t": ts, "soc_v": 60.0 - 0.01 * ts}
ca["chg"][0] = 0.0
sc = E.step_charge(ca, 20.0, 80.0)
assert abs(sc["q1a"] - 0.060) < 1e-9 and abs(sc["q1b"] - 0.029) < 1e-6 and abs(sc["q1a_on400"] - 0.031) < 1e-6 and abs(sc["q1b_400"] - 0.029) < 1e-6 and abs(sc["dsoc"] + 0.6) < 1e-9
# reconciliation against master columns: within the tolerances, and outside when 2 % off
mrow = {"gross_charge_kwh": float(ca["chg"].sum()), "charge_eng_off_kwh": float(ca["chg"][ca["rpm"] <= 400].sum()), "charge_pure_regen_kwh": np.nan}
r = E.drive_reconciliation(ca, mrow)
assert r["gross"] is True and r["eng_off"] is True and r["pure_regen"] is None
big = dict(ca, chg=ca["chg"] * 100.0)                                                                                   # 10 kWh: the relative tolerance (0.5 %) governs
mb = {"gross_charge_kwh": float(big["chg"].sum()), "charge_eng_off_kwh": float(big["chg"][big["rpm"] <= 400].sum()), "charge_pure_regen_kwh": np.nan}
assert E.drive_reconciliation(big, mb)["gross"] is True
assert E.drive_reconciliation(big, dict(mb, gross_charge_kwh=mb["gross_charge_kwh"] * 1.05))["gross"] is False
assert E.drive_reconciliation(big, dict(mb, gross_charge_kwh=mb["gross_charge_kwh"] * 1.004))["gross"] is True
assert E.drive_reconciliation(ca, dict(mrow, gross_charge_kwh=float(ca["chg"].sum()) + 0.004))["gross"] is True          # small drive: inside the 0.01 kWh absolute tolerance
summ = E.reconciliation_summary([{"gross": True, "eng_off": True, "pure_regen": None}] * 98 + [{"gross": False, "eng_off": True, "pure_regen": None}] * 3)
assert summ["gross"]["outside_tolerance"] == 3 and summ["stop"] is True
assert E.reconciliation_summary([{"gross": True, "eng_off": True, "pure_regen": True}] * 100)["stop"] is False

# classes, bands, support floors
g = np.array([-5.0, -1.01, -0.99, 0.0, 1.0, 1.01, 7.0, np.nan])
assert list(E.class3(g)) == [0, 0, 1, 1, 2, 2, 2, -1]
assert list(E.band3([10.0, 49.9, 50.0, 89.9, 90.0, 130.0])) == [0, 0, 1, 1, 2, 2]
cls = np.array([0] * 1000 + [1] * 10)
f = E.support(cls, np.arange(1010) % 40, np.full(1010, 0.2), 0)
assert f["floors_met"] is True and f["steps"] == 1000 and E.support(cls, np.arange(1010) % 40, np.full(1010, 0.2), 1)["floors_met"] is False

# planted class means and contrasts: flat 10 per km, downhill 14, uphill 7 (kWh per 100 km), noise by day; speed bands with different levels
r = np.random.default_rng(5)
n, nd = 6000, 120
days = np.array(["d%03d" % (i % nd) for i in range(n)])
trueg = r.choice([-3.0, 0.0, 3.0], n, p=[0.2, 0.6, 0.2])
band = r.integers(0, 3, n)
km = r.uniform(0.3, 0.9, n)
base = np.array([8.0, 10.0, 12.0])[band] / 100.0
eff = np.where(trueg < -1, 4.0, np.where(trueg > 1, -3.0, 0.0)) / 100.0
num = km * (base + eff) + r.normal(0, 0.002, n) * km
ud, di = X.day_index(days)
Wb = X.boot_weights(len(ud), 400)
cl = E.class3(trueg)
Nn, Dd = E.day_arrays(num, km, cl, band, days, di)
rp, sp, rb, sb = E.class_means(Nn, Dd, Wb)
cb = E.contrast_block(rp, rb, 100.0)
assert abs(cb["means"]["flat"]["est"] - 10.0) < 0.3 and abs(cb["downhill_minus_flat"]["est"] - 4.0) < 0.4 and abs(cb["uphill_minus_flat"]["est"] + 3.0) < 0.4
assert cb["downhill_minus_flat"]["ci95"][0] > 0 > cb["uphill_minus_flat"]["ci95"][1] and abs(cb["downhill_minus_flat"]["mdd"] - 2.8 * cb["downhill_minus_flat"]["se"]) < 1e-12
cs = E.contrast_block(sp, sb, 100.0)
assert abs(cs["downhill_minus_flat"]["est"] - 4.0) < 0.4
# speed standardisation removes a speed-mix confound: downhill steps concentrated in the high-band (12 per km) inflate the raw contrast only
band2 = np.where(trueg < -1, r.choice([0, 1, 2], n, p=[0.1, 0.2, 0.7]), band)
base2 = np.array([8.0, 10.0, 12.0])[band2] / 100.0
num2 = km * (base2 + 0.0) + r.normal(0, 0.002, n) * km                        # NO class effect at all
N2, D2 = E.day_arrays(num2, km, cl, band2, days, di)
rp2, sp2, rb2, sb2 = E.class_means(N2, D2, Wb)
assert E.contrast_block(rp2, rb2, 100.0)["downhill_minus_flat"]["est"] > 0.8 and abs(E.contrast_block(sp2, sb2, 100.0)["downhill_minus_flat"]["est"]) < 0.4

# misclassification attenuates the contrast by the predicted factor; the consensus class (agreement of two noisy labels) partly restores it
noisy1 = trueg + r.normal(0, 1.6, n)
noisy2 = trueg + r.normal(0, 1.6, n)
cl1 = E.class3(noisy1)
N3, D3 = E.day_arrays(num, km, cl1, band, days, di)
rp3, _, rb3, _ = E.class_means(N3, D3, Wb)
c_noisy = E.contrast_block(rp3, rb3, 100.0)["downhill_minus_flat"]["est"]
assert 0.5 < c_noisy < 3.4, c_noisy
agree = (cl1 == E.class3(noisy2))
N4, D4 = E.day_arrays(num[agree], km[agree], cl1[agree], band[agree], days[agree], di[agree])
rp4, _, rb4, _ = E.class_means(N4, D4, Wb)
c_cons = E.contrast_block(rp4, rb4, 100.0)["downhill_minus_flat"]["est"]
assert c_cons > c_noisy and c_cons < 4.2, (c_noisy, c_cons)

# planted slope per percentage point with speed-band and cohort fixed effects, and a placebo grade without a slope
cohort = np.array(["warm", "cold", "shoulder"])[r.integers(0, 3, n)]
grade = r.normal(0, 2.0, n)
y = (10.0 + 1.5 * grade + np.array([-2.0, 0.0, 2.0])[band] + np.array([0.0, 1.0, 0.5])[np.argsort(["warm", "cold", "shoulder"])[0] * 0 + np.searchsorted(["cold", "shoulder", "warm"], cohort)]) + r.normal(0, 0.5, n)
sl = E.slope_fit(y, km, grade, band, cohort, days, Wb, 400)
assert abs(sl["slope_per_pp"] - 1.5) < 0.1 and sl["ci95"][0] < 1.5 < sl["ci95"][1] and abs(sl["mdd"] - 2.8 * sl["se"]) < 1e-12
slp = E.slope_fit(y, km, r.normal(0, 2.0, n), band, cohort, days, Wb, 400)
assert abs(slp["slope_per_pp"]) < 0.15 and slp["ci95"][0] < 0 < slp["ci95"][1]

# the reading rule (spec R3 with the numeric placebo condition)
prim = {"est": 4.0, "ci95": [2.0, 6.0]}
assert E.reading(prim, {"est": 0.1, "ci95": [-0.5, 0.7]}, True) == "differs from flat"
assert E.reading(prim, {"est": 2.5, "ci95": [1.0, 4.0]}, True).startswith("inconclusive (placebo")            # same sign, interval excludes zero, at least 0.5 x primary
assert E.reading(prim, {"est": 1.5, "ci95": [0.4, 2.6]}, True) == "differs from flat"                         # same sign and excluding zero but below 0.5 x primary
assert E.reading(prim, {"est": -2.5, "ci95": [-4.0, -1.0]}, True) == "differs from flat"                      # opposite sign
assert E.reading(prim, {"est": 0.1, "ci95": [-0.5, 0.7]}, False).startswith("inconclusive (consensus")
assert E.reading({"est": 0.4, "ci95": [-1.0, 1.8]}, {"est": 0.0, "ci95": [-1.0, 1.0]}, True) == "not distinguishable"
assert E.reading({"est": None, "ci95": [None, None]}, {"est": 0.0, "ci95": [-1, 1]}, True) == "not testable"

# privacy: the result must not carry drive names, dates or absolute odometer values
assert J.scan_privacy({"G0": {"all_steps": {"downhill": {"steps": 1647, "days": 100, "km": 987.6}}}}) == []
assert J.scan_privacy({"x": "2026-10-17_23-13-01.csv"}) and J.scan_privacy({"v": 48104.8})
assert E.A_MIN_KJ == 100.0 and E.FLOORS == {"days": 30, "km": 100.0, "steps": 1000} and E.TOL_GROSS == (0.005, 0.01) and E.MAX_DRIVE_FAIL_SHARE == 0.02
print("test_grade_energy_flows: OK")
