"""M754 known-answer tests (analyses/M754_spec.md Rev 2): snapshot window and age, OBD coolant ends, day-clustered statistics with the support floor, the K1 wording at the thresholds, the age slope,
the pair filters and exclusion counts, the decay rate recovered on a planted exponential for all three anchor types, the joint day-clustered bootstrap (sign, null, reproducibility), the difference wording,
the local-to-UTC check constants, optional-stage skip and the pinned-input STOP. No cloud store or raw files needed."""
import os, sys, tempfile
from datetime import datetime
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import coolant_snapshots as K
import mynissan_coverage as mc

# optional stage and pinned-input STOP
tmp = tempfile.mkdtemp()
assert K.main(["--store", os.path.join(tmp, "nostore"), "--out-dir", tmp]) == 0
store = os.path.join(tmp, "store")
os.makedirs(store)
open(os.path.join(store, "manifest.json"), "w", encoding="utf-8").write("{}")
rawd = os.path.join(tmp, "raw")
os.makedirs(rawd)
fake_gaps = os.path.join(tmp, "gaps.csv")
open(fake_gaps, "w", encoding="utf-8").write("prev,next,gap_h,class\na,b,1.0,stationary_consistent\n")
assert K.main(["--store", store, "--raw-dir", rawd, "--gaps", fake_gaps, "--out-dir", tmp]) == 3          # the gap table differs from its pin

# local-to-UTC constants of the control: summer +3 h, winter +2 h
for d_, off in K.KYIV_CHECK.items():
    assert datetime.strptime(d_ + " 12:00:00", "%Y-%m-%d %H:%M:%S").replace(tzinfo=mc.KYIV).utcoffset().total_seconds() == off

# snapshot window and age
ts, vs = np.array([100.0, 150.0, 400.0, 900.0]), np.array([80.0, 75.0, 60.0, 40.0])
v, t, age = K.snapshot_near(ts, vs, 140.0)
assert (v, t, age) == (75.0, 150.0, 10.0)
assert K.snapshot_near(ts, vs, 700.0) is None and K.snapshot_near(ts, vs, 700.0, 120.0, 600.0)[0] == 40.0
assert K.snapshot_near(ts, vs, 280.0)[0] == 60.0 and K.snapshot_near(ts, vs, -100.0) is None
# the nearest of two rows inside the window
assert K.snapshot_near(np.array([100.0, 130.0]), np.array([1.0, 2.0]), 128.0)[0] == 2.0
# OBD ends
assert K.obd_ends([]) is None and K.obd_ends([(10.0, 40.0), (20.0, 70.0), (35.0, 90.0)]) == (40.0, 10.0, 90.0, 35.0)

# day-clustered statistics, support floor and the K1 wording
rng = np.random.default_rng(2)
n = 200
days = np.array(["2026-08-%02d" % (1 + i % 28) for i in range(n)])
d_ok = rng.normal(0.2, 0.8, n)
s = K.summarise(d_ok, days, 200)
assert s["nDrives"] == n and s["median"]["ci95"][0] <= 0.2 <= s["median"]["ci95"][1] and K.k1_wording(s).startswith("consistent at key-off"), K.k1_wording(s)
d_off = rng.normal(-3.0, 1.0, n)
s2 = K.summarise(d_off, days, 200)
assert K.k1_wording(s2).startswith("offset of -3") and "mean" in K.k1_wording(s2)
small = K.summarise(d_ok[:15], days[:15], 50)
assert small["status"].startswith("not estimable") and K.k1_wording(small) == "not estimable at this support"
assert K.summarise(d_ok[:60], np.array(["d%d" % (i % 4) for i in range(60)]), 50)["status"].startswith("not estimable")           # fewer than 10 days
b1, b2 = K.cluster_stats(d_ok, days, 50, 42), K.cluster_stats(d_ok, days, 50, 42)
assert b1 == b2
# age slope recovered
age_s = rng.uniform(-60, 120, n)
y = -0.5 * (age_s / 60.0) + rng.normal(0, 0.3, n)
sl = K.age_slope(y, age_s, days)
assert abs(sl["slopeCPerMin"] + 0.5) < 0.1 and sl["ci95"][0] < -0.5 < sl["ci95"][1]
assert K.age_slope([1.0, 2.0], [0.0, 0.0], ["a", "b"]) is None

# pair filters and exclusion counts: parked range, excess of the anchor over ambient above 10 C, excess on arrival above 1 C
rows = [{"anchorT": 80.0, "arrivalT": 40.0, "ambient": 10.0, "parkedH": 1.0, "day": "2026-09-01"},            # kept: ea 70, eb 30
        {"anchorT": 80.0, "arrivalT": 40.0, "ambient": 10.0, "parkedH": 0.1, "day": "2026-09-02"},            # parked below 0.25 h
        {"anchorT": 80.0, "arrivalT": 40.0, "ambient": 10.0, "parkedH": 8.0, "day": "2026-09-03"},            # parked above 6 h (kept in the 24 h range)
        {"anchorT": 15.0, "arrivalT": 12.0, "ambient": 10.0, "parkedH": 1.0, "day": "2026-09-04"},            # anchor excess 5 C
        {"anchorT": 80.0, "arrivalT": 10.5, "ambient": 10.0, "parkedH": 2.0, "day": "2026-09-05"}]            # arrival excess 0.5 C
tab, ex = K.pair_table(rows)
assert len(tab) == 1 and ex == {"input": 5, "outsideParkedRange": 2, "eaNotAbove10": 1, "ebNotAbove1": 1, "kept": 1}, ex
assert abs(tab["y"].iloc[0] - np.log(30.0 / 70.0)) < 1e-12
assert len(K.pair_table(rows, park_max=24.0)[0]) == 2 and len(K.pair_table(rows, eb_min=3.0)[0]) == 1 and K.pair_table([])[1] == {"input": 0}

# the decay rate is recovered on a planted exponential for each anchor type; both estimators agree on clean data
def planted(k, n_, seed):
    r = np.random.default_rng(seed)
    t_h = r.uniform(0.3, 5.8, n_)
    amb = r.uniform(5, 20, n_)
    ea = r.uniform(40, 70, n_)
    eb = ea * np.exp(-k * t_h + r.normal(0, 0.03, n_))
    return [{"anchorT": amb[i] + ea[i], "arrivalT": amb[i] + eb[i], "ambient": amb[i], "parkedH": t_h[i], "day": "2026-10-%02d" % (1 + i % 28)} for i in range(n_)]
tab_s, _ = K.pair_table(planted(0.5, 150, 1))
f1 = K.fit_k(tab_s)
assert abs(f1["kSen"] - 0.5) < 0.05 and abs(f1["kThroughOriginLS"] - 0.5) < 0.05 and abs(f1["interceptSen"]) < 0.05 and abs(f1["tauSenH"] - 2.0) < 0.3
assert K.fit_k(tab_s.iloc[:5])["status"].startswith("not estimable") and K.supported(tab_s) and not K.supported(tab_s.iloc[:10])

# joint day-clustered bootstrap: a planted difference (k 0.5 vs 0.8) has the right sign and an interval that excludes zero; equal rates contain zero; reproducible
tab_a, _ = K.pair_table(planted(0.5, 150, 3))
tab_b, _ = K.pair_table(planted(0.8, 150, 4))
tab_c, _ = K.pair_table(planted(0.5, 150, 5))
dr = K.joint_boot({"A": tab_a, "B": tab_b, "C": tab_c}, 150)
dd = dr["B"] - dr["A"]
lo, hi = np.nanpercentile(dd, [2.5, 97.5])
assert lo > 0 and abs(np.nanmedian(dd) - 0.3) < 0.06, (lo, hi)
d0 = dr["C"] - dr["A"]
lo0, hi0 = np.nanpercentile(d0, [2.5, 97.5])
assert lo0 < 0 < hi0
assert np.array_equal(np.nan_to_num(K.joint_boot({"A": tab_a, "B": tab_b}, 40)["A"]), np.nan_to_num(K.joint_boot({"A": tab_a, "B": tab_b}, 40)["A"]))
# median difference of two independent sets with a joint day bootstrap: a planted 5 C offset has an interval that excludes zero, equal sets contain zero
r2 = np.random.default_rng(6)
da = np.array(["2026-11-%02d" % (1 + i % 20) for i in range(120)])
x1, x2 = r2.normal(70, 6, 120), r2.normal(65, 6, 120)
md = K.median_diff_ci(x1, da, x2, da, 200)
assert md["ci95"][0] > 0 and abs(md["difference"] - 5.0) < 2.5
md0 = K.median_diff_ci(x2, da, r2.normal(65, 6, 120), da, 200)
assert md0["ci95"][0] < 0 < md0["ci95"][1]
# difference wording per the decision rule
assert K.diff_wording(0.5, 0.8, 0.1, 0.5, True) == "material" and K.diff_wording(0.5, 0.52, 0.001, 0.04, True) == "small"
assert K.diff_wording(0.5, 0.8, -0.1, 0.5, True) == "not distinguishable" and K.diff_wording(0.5, 0.8, 0.1, 0.5, False).startswith("not estimable") and K.diff_wording(None, 0.8, 0, 1, True).startswith("not estimable")
# sen slope on exact data
assert abs(K.sen_slope([0, 1, 2, 3], [1, 3, 5, 7]) - 2.0) < 1e-12 and abs(K.ls_origin_slope([1, 2, 3], [2, 4, 6]) - 2.0) < 1e-12
print("test_coolant_snapshots: OK")
