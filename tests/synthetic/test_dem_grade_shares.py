"""M767 known-answer tests (analyses/M767_spec.md Rev 2): tools/dem_grade_shares.py classes the step grade with the five frozen edges, computes step and km shares with day-clustered intervals (planted shares recovered, shares sum to one),
suppresses intervals below the cell floors, brackets the four products and flags 'source-dependent' only when another product lies outside the FABDEM interval, computes coverage of the logged kilometres by month, length and cohort with the
suppression of small cells and the drive-level speed mix, and keeps drive names, dates and absolute odometer values out of the result. No real data is needed."""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import dem_grade_shares as S
import dem_crosscheck as X
import odometer_jump_audit as J

# five classes with the frozen edges -3, -1, 1, 3 (a value on an edge falls in the class above it, as in M762 C6)
g = np.array([-9.0, -3.0, -2.99, -1.0, 0.0, 0.99, 1.0, 2.99, 3.0, 8.0])
assert list(S.classes5(g)) == [0, 1, 1, 2, 2, 2, 3, 3, 4, 4]

# planted shares: 4 % / 12 % / 70 % / 11 % / 3 % over 134 days; step shares and km shares are recovered and sum to one; the interval covers the truth
r = np.random.default_rng(11)
n, nd = 11000, 134
days = np.array(["d%03d" % (i % nd) for i in range(n)])
cls = r.choice(5, n, p=[0.04, 0.12, 0.70, 0.11, 0.03])
grade = np.array([-5.0, -2.0, 0.0, 2.0, 5.0])[cls] + r.normal(0, 0.2, n)
km = r.uniform(0.3, 0.9, n)
df = pd.DataFrame({"day": days, "drive": ["f%04d" % (i % 700) for i in range(n)], "d_m": km * 1000.0, "gF": grade})
W_cache = {}
tab = S.shares_table(df, "gF", 400, W_cache)
est = np.array([row["step_share_pct"]["est"] for row in tab["rows"]])
assert abs(est.sum() - 100.0) < 1e-9 and np.allclose(est, [4, 12, 70, 11, 3], atol=1.0)
for row, truth in zip(tab["rows"], [4, 12, 70, 11, 3]):
    lo, hi = row["step_share_pct"]["ci95"]
    assert lo < truth < hi and row["support"]["interval_shown"] and row["support"]["steps"] > 0
kmest = np.array([row["km_share_pct"]["est"] for row in tab["rows"]])
assert abs(kmest.sum() - 100.0) < 1e-9 and np.allclose(kmest, est, atol=1.2)           # the same classes, km-weighted (equal step lengths on average)
assert tab["n_steps"] == n and tab["n_days"] == nd and abs(tab["km"] - km.sum()) < 1e-6
# a km-weighted share differs from the step share when the class has longer steps
df2 = df.copy()
df2.loc[cls == 4, "d_m"] = 900.0
df2.loc[cls != 4, "d_m"] = 300.0
t2 = S.shares_table(df2, "gF", 200, {})
assert t2["rows"][4]["km_share_pct"]["est"] > 2.5 * t2["rows"][4]["step_share_pct"]["est"] - 1.0

# cells below the floors keep their counts and carry no interval
small = df[(cls == 0) | (np.arange(n) < 3000)].copy()
small = small[(small["gF"] > -3.5) | (small["gF"] < -6)]
tiny = pd.concat([df[cls != 4], df[cls == 4].head(8)])
tt = S.shares_table(tiny, "gF", 200, {})
assert tt["rows"][4]["support"]["steps"] == 8 and not tt["rows"][4]["support"]["interval_shown"] and tt["rows"][4]["step_share_pct"]["ci95"] == [None, None]

# four products: bracket (min and max) and the 'source-dependent' flag only when another product is outside the FABDEM interval
d4 = df.copy()
d4["gN"] = d4["gF"] + r.normal(0, 0.15, n)
d4["gA"] = d4["gF"] + r.normal(0, 0.15, n)
d4["gG"] = d4["gF"] + r.normal(0, 0.15, n)
d4["gN"] = np.where(cls == 2, d4["gN"] + 0.0, d4["gN"])
rows = S.bracket_and_flags(d4, 200, {}, S.shares_table(d4, "gF", 200, {})["rows"])
for row in rows:
    v = row["by_product_step_share_pct"]
    assert row["bracket_min"] == min(v.values()) and row["bracket_max"] == max(v.values()) and set(v) == {"F", "N", "A", "G"}
assert all(row["source_dependent"] is False for row in rows)                       # products that agree up to small noise stay inside the FABDEM interval
d5 = d4.copy()
d5["gN"] = np.where(cls == 2, d5["gN"] + 1.6, d5["gN"])                           # NASADEM pushes a fifth of the flat steps into the +1 to 3 class
rows5 = S.bracket_and_flags(d5, 200, {}, S.shares_table(d5, "gF", 200, {})["rows"])
assert rows5[2]["source_dependent"] is True and rows5[3]["source_dependent"] is True

# coverage of the logged kilometres: by month, by length stratum and cohort; small cells suppressed; drive-level speed mix
files = ["f%03d" % i for i in range(40)]
dm = pd.DataFrame({"file": files, "distance_km": [1.0] * 5 + [5.0] * 20 + [15.0] * 15, "date": ["2026-05-%02d" % (1 + i % 28) for i in range(5)] + ["2026-06-%02d" % (1 + i % 28) for i in range(35)],
                   "pct_urban": [80.0] * 20 + [20.0] * 20, "pct_highway": [5.0] * 20 + [60.0] * 20})
prim = pd.DataFrame({"drive": [f for f in files[5:25] for _ in range(4)], "d_m": 500.0})                                # 20 drives of 5 km, 2 km covered each
cohort_of = {f: ("cold" if i < 10 else "warm") for i, f in enumerate(files)}
cov = S.coverage_tables(prim, dm, files, cohort_of)
assert abs(cov["logged_km"] - (5 + 100 + 225)) < 1e-9 and abs(cov["covered_km"] - 40.0) < 1e-9 and abs(cov["covered_share_of_logged_km_pct"] - 100 * 40 / 330) < 1e-9
assert cov["drives"] == 40 and cov["drives_with_a_covered_step"] == 20
assert cov["by_month"]["2026-05"] == "suppressed (fewer than 3 drives)" or cov["by_month"]["2026-05"]["drives"] >= 3
assert cov["by_stratum"]["2 to 10 km"]["covered_share_pct"] == 40.0 and cov["by_stratum"]["10 km and longer"]["covered_share_pct"] == 0.0
mix = cov["drive_level_speed_class_mix_km_weighted"]
assert abs(mix["covered"]["urban_pct"] - (15 * 80.0 + 5 * 20.0) / 20.0) < 1e-9 and mix["covered"]["urban_pct"] == 65.0
assert abs(mix["all_logged"]["urban_pct"] + mix["all_logged"]["highway_pct"] + mix["all_logged"]["mixed_pct"] - 100.0) < 1e-9

# privacy: no drive names, dates or absolute odometer values in a result; months are allowed
assert J.scan_privacy({"by_month": {"2026-05": {"drives": 38}}, "E1": {"rows": [{"class": "-1 to 1 pp", "steps": 7837}]}}) == []
assert J.scan_privacy({"f": "2026-10-17_23-13-01.csv"}) and J.scan_privacy({"v": 48104.8}) and J.scan_privacy({"2026-10-17": 3})
assert S.CELL_FLOORS == {"steps": 20, "days": 5} and S.FLOORS == {"days": 30, "km": 100.0, "steps": 1000} and S.CLASS_NAMES[2] == "-1 to 1 pp"

# M746 retest mode (audit): the registered set must be the first 717 canonical drives; control R1 fails (Stop) on a different step table; the retest result path never equals analyses/
import hashlib
try:
    S.registered_files(["f%d" % i for i in range(700)])
    raise SystemExit("a short or foreign file list must stop")
except S.Stop:
    pass
planted = pd.DataFrame({"first": [False] * 4, "last": [False] * 4, "vmin_kmh": [30.0] * 4, "gF": [0.0, 0.5, 2.0, -2.0], "gN": [0.0] * 4, "gA": [0.0] * 4, "gG": [0.0] * 4, "dh_num": [1.0] * 4, "dh_glo": [1.0] * 4})
m762_fake = {"C1_step_stages": {"all_steps_before_exclusions": 99}, "C6_class_shares": {"F": {"step_share": [0.0] * 5}}, "C6_misclassification_vs_fabdem": {"N": 0.0, "A": 0.0}}
try:
    S.control_r1(planted, m762_fake)
    raise SystemExit("a different step table must fail control R1")
except S.Stop:
    pass
st4 = S.step_sets(planted)[0]
assert st4["after_fabdem_grade_8pp_exclusion"] == 4 and S.RETEST_RESULT == "grade_shares_retest.json" and S.REGISTERED_N == 717
src = open(os.path.join(ROOT, "tools", "dem_grade_shares.py"), encoding="utf-8").read()
assert src.index("master pin failed") < src.index("json.dump(res") and src.count("json.dump(res") == 1        # registered mode: a pin stop returns before the only write
assert "never writes into analyses" in src

# 8.1 behavioural: registered mode with a foreign master stops (non-zero) and writes nothing into the out-dir
import tempfile, shutil
td = tempfile.mkdtemp()
try:
    for sub in ("fabdem", "nasadem", "aw3d30", "glo30"):
        os.makedirs(os.path.join(td, "dem", sub))
    os.makedirs(os.path.join(td, "store"))
    open(os.path.join(td, "store", "manifest.json"), "w", encoding="utf-8").write("{}")
    os.makedirs(os.path.join(td, "raw"))
    open(os.path.join(td, "master.csv"), "w", encoding="utf-8").write("file\nx.csv\n")
    outd = os.path.join(td, "out")
    rc = S.main(["--run", "--dem-dir", os.path.join(td, "dem"), "--store", os.path.join(td, "store"), "--raw-dir", os.path.join(td, "raw"), "--master", os.path.join(td, "master.csv"), "--out-dir", outd])
    assert rc != 0 and not os.path.exists(outd)
    rc = S.main(["--run", "--retest", "--dem-dir", os.path.join(td, "dem"), "--store", os.path.join(td, "store"), "--raw-dir", os.path.join(td, "raw"), "--master", os.path.join(td, "master.csv"), "--out-dir", os.path.join(ROOT, "analyses")])
    assert rc != 0
finally:
    shutil.rmtree(td, ignore_errors=True)
print("test_dem_grade_shares: OK")
