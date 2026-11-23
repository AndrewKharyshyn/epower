"""M753 known-answer tests (analyses/M753_spec.md Rev 2, 2.1, 2.2): owner seat weights and luggage tables, the load table, allowance scenarios (S2c class-wise zero shift, S1c common base, S2 pooled,
S3 P95), drives without a belt pattern keep the class mass, mass bias with a day-clustered interval, belt patterns from planted cloud rows, cell comparison against the published mass range and day
interval, the association check (sign, minimum detectable slope), the patch of the mass function is restored, optional-stage skip and the pinned-master STOP. No cloud store or cache needed."""
import os, sys, tempfile, types
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import mass_sensitivity as M

tmp = tempfile.mkdtemp()
assert M.main(["--store", os.path.join(tmp, "nostore"), "--out-dir", tmp]) == 0                    # optional stage: skipped, exit 0
store = os.path.join(tmp, "store")
os.makedirs(store)
open(os.path.join(store, "manifest.json"), "w", encoding="utf-8").write("{}")
fake_master = os.path.join(tmp, "master.csv")
open(fake_master, "w", encoding="utf-8").write("file,date\na,2026-01-01\n")
assert M.main(["--store", store, "--master", fake_master, "--out-dir", tmp]) == 3                   # a different master stops the tool

# seat weights and payload brackets
allp = {"P": 1, "L": 1, "C": 1, "R": 1}
assert abs(M.payload_of(allp, 1) - (55.075 + 35 + 27.5 + 17.25)) < 1e-9
assert M.payload_of({"P": 0, "L": 0, "C": 0, "R": 0}, 1) == 0.0
assert [M.payload_of({"P": 0, "L": 0, "C": 0, "R": 1}, i) for i in range(3)] == [8.0, 17.25, 27.0]          # belt-type child seat: 8 kg present when latched, child at 50 % in the central value
assert [M.payload_of({"P": 1, "L": 0, "C": 0, "R": 0}, i) for i in range(3)] == [52.0, 55.075, 90.0]
# luggage by class
assert M.luggage_of("highway", 1) == 52.5 and M.luggage_of("highway", 0) == 40.0 and M.luggage_of("highway", 2) == 65.0
assert [round(M.luggage_of("mixed_highway", i), 3) for i in range(3)] == [20.0, 39.375, 65.0]
assert [M.luggage_of(c, 1) for c in ("urban", "mixed")] == [10.0, 10.0] and M.luggage_of("urban", 0) == 5.0 and M.luggage_of("urban", 2) == 15.0
assert M.luggage_of("unknown", 1) == 0.0 and M.luggage_of("weird", 1) == 0.0 and M.class_group("weird") == "unknown"

# load table and scenarios on a planted corpus: 40 highway drives (class mass 2000), 160 urban drives (1890), 20 urban drives without a belt pattern
rng = np.random.default_rng(4)
rows = []
for i in range(200):
    hw = i < 40
    pat = {"P": int(rng.random() < 0.8), "L": int(rng.random() < 0.5), "C": 0, "R": int(rng.random() < 0.75)}
    rows.append({"file": "d%03d" % i, "date": "2026-07-%02d" % (1 + i % 28), "drive_type": "highway" if hw else "urban", "class_mass": 2000.0 if hw else 1890.0, "pattern": None if i >= 180 else pat})
tab = M.load_table(rows)
assert tab["has_pattern"].sum() == 180 and tab.loc[190, "load_central"] != tab.loc[190, "load_central"]          # NaN without a pattern
assert abs(tab.loc[0, "load_central"] - (M.payload_of(rows[0]["pattern"], 1) + 52.5)) < 1e-9
# S2c: class-wise zero mean shift on drives with a pattern; drives without a pattern keep the class mass
m2c = M.scenario_mass(tab, "S2c", "central")
for g in ("highway", "urban"):
    sel = tab["has_pattern"] & (tab["group"] == g)
    assert abs((m2c[sel] - tab.loc[sel, "class_mass"]).mean()) < 1e-9, g
assert (m2c[~tab["has_pattern"]] == tab.loc[~tab["has_pattern"], "class_mass"]).all()
# S1c: common base 1890 + load
m1c = M.scenario_mass(tab, "S1c", "central")
assert abs(m1c[0] - (1890.0 + tab.loc[0, "load_central"])) < 1e-9 and m1c[190] == 1890.0
# S2 pooled and S3 P95
m2 = M.scenario_mass(tab, "S2", "central")
ok = tab["has_pattern"]
a2 = (tab.loc[ok, "class_mass"] + tab.loc[ok, "load_central"] - m2[ok])                                        # the pooled allowance: one constant
assert a2.std() < 1e-9 and abs(a2.iloc[0] - tab.loc[ok, "load_central"].mean()) < 1e-9
m3 = M.scenario_mass(tab, "S3", "central")
a3 = (tab.loc[ok, "class_mass"] + tab.loc[ok, "load_central"] - m3[ok]).iloc[0]
assert abs(a3 - np.percentile(tab.loc[ok, "load_central"], 95)) < 1e-9
# brackets: the high load gives a larger S1c mass than the low load
assert (M.scenario_mass(tab, "S1c", "high")[ok] > M.scenario_mass(tab, "S1c", "low")[ok]).all()

# mass bias with a day-clustered interval: +19 kg on every drive of 1900 kg is +1 %
t2 = pd.DataFrame({"class_mass": np.full(120, 1900.0)})
days = np.array(["2026-08-%02d" % (1 + i % 28) for i in range(120)])
b = M.mass_bias(t2, pd.Series(np.full(120, 1919.0)), days, 200)
assert abs(b["est"] - 0.01) < 1e-9 and b["ci95"][0] <= 0.01 <= b["ci95"][1]
assert M.mass_bias(t2, pd.Series(np.full(120, 1900.0)), days, 50)["est"] == 0.0

# belt patterns from planted cloud rows: three moving rows with passenger and rear-right latched (code 2), rear-left and centre unlatched (code 1)
def rowd(sp, p, l, c, r):
    return {"SpeedDisplayedValueinkmh": str(sp), "SeatBeltFirstRowPassenger": str(p), "SeatBeltSecondRowLeft": str(l), "SeatBeltSecondRowCenter": str(c), "SeatBeltSecondRowRight": str(r)}
trip = [(1000.0 + 30 * k, rowd(50, 2, 1, 1, 2)) for k in range(5)] + [(5000.0 + 30 * k, rowd(50, 2, 1, 1, 2)) for k in range(2)] + [(9000.0 + 30 * k, {**rowd(50, 2, 1, 1, 2), "SeatBeltSecondRowRight": ""}) for k in range(5)]
pt = M.belt_patterns(trip, [("a", 1000.0, 1100.0), ("short", 5000.0, 5020.0), ("missing", 9000.0, 9100.0)])
assert pt["a"] == {"P": 1, "L": 0, "C": 0, "R": 1} and pt["short"] is None and pt["missing"] is None

# cell comparison: published mass range, day interval and the unsupported cells
pub = {"cohorts": {"all": {"strata": {"fast": [{"eff": 60.0, "massRange": [58.0, 62.0], "ci95": [57.0, 63.0], "status": "supported"}, {"eff": 50.0, "massRange": [49.0, 51.0], "ci95": [48.0, 52.0], "status": "thin"}]}}}}
new_in = {"cohorts": {"all": {"strata": {"fast": [{"eff": 61.0, "massRange": [58.0, 62.0], "ci95": [57.0, 63.0], "status": "supported"}, {"eff": 40.0, "massRange": [49.0, 51.0], "ci95": [48.0, 52.0], "status": "thin"}]}}}}
r1 = M.compare_cells(pub, new_in)
assert len(r1) == 1 and r1[0]["inRange"] and abs(r1[0]["relChange"] - 1.0 / 60.0) < 1e-12 and abs(r1[0]["shiftOverCiHalf"] - 1.0 / 3.0) < 1e-12
new_out = {"cohorts": {"all": {"strata": {"fast": [{"eff": 64.0, "massRange": [58.0, 62.0], "ci95": [57.0, 63.0], "status": "supported"}, {"eff": 50.0}]}}}}
r2 = M.compare_cells(pub, new_out)
assert len(r2) == 1 and not r2[0]["inRange"] and not r2[0]["inCi"]
s = M.summarise_cells(r1 + r2)
assert s["cells"] == 2 and s["cellsOutsidePublishedMassRange"] == 1 and M.summarise_cells([]) == {"cells": 0}

# gate split: internal gates hold under any mass, the comparison gates with the published blocks are expected to fail in a scenario
g_ok = {"tolerance": 1e-9, "strataReconcile": {"all": {"_ke": 0.0, "_ch": 1e-12, "n": 0}}, "socSumReconcile": {"all": {"p": {"nSoc": 0, "nAll": 0, "keKwh": 0.0, "chargeKwh": 0.0, "keAll": 0.0}}},
        "pooledMatchesM441": {"all": True}, "observedMatchesM444": {"all": True}}
assert M.gate_detail(g_ok) == {"strataReconcileOk": True, "socSumReconcileOk": True, "pooledMatchesM441": True, "observedMatchesM444": True}
g_sc = dict(g_ok, pooledMatchesM441={"all": False}, observedMatchesM444={"all": False})
gd = M.gate_detail(g_sc)
assert gd["strataReconcileOk"] and gd["socSumReconcileOk"] and not gd["pooledMatchesM441"] and not gd["observedMatchesM444"]
assert M.gate_detail(dict(g_ok, strataReconcile={"all": {"_ke": 1e-3, "_ch": 0.0, "n": 0}}))["strataReconcileOk"] is False

# association: planted slope equal to the prediction with low noise is consistent; huge noise is not informative; the sign is positive
rng = np.random.default_rng(8)
n = 300
groups = np.array(["urban"] * 240 + ["highway"] * 60)
load = np.where(groups == "urban", 78.0, 162.0) + rng.normal(0, 40, n)
days = np.array(["2026-09-%02d" % (1 + i % 28) for i in range(n)])
pred_slope = 60.0 * 100.0 / 1900.0
y = 60.0 + (load - pd.Series(load).groupby(pd.Series(groups)).transform("mean").to_numpy()) / 100.0 * pred_slope + rng.normal(0, 0.5, n)
out = M.association(y, load, groups, days, 1900.0)
assert out["slopePctPerPer100kg"] > 0 and out["ci95"][0] <= pred_slope <= out["ci95"][1] and out["verdict"].startswith("slope consistent with"), out
noisy = M.association(60.0 + rng.normal(0, 25, n), load, groups, days, 1900.0)
assert noisy["verdict"].startswith("not informative") and noisy["mdeSlope"] > abs(noisy["predictedSlope"])
beta, se, G = M.cluster_ols(1.0 + 2.0 * np.arange(10.0), np.column_stack([np.ones(10), np.arange(10.0)]), np.arange(10) % 5)
assert abs(beta[0] - 1.0) < 1e-9 and abs(beta[1] - 2.0) < 1e-9 and G == 5

# the mass-function patch is restored, also after an exception
fake = types.SimpleNamespace(_mass_for_drive=lambda dt, f: 1890.0)
with M.MassPatch(fake, {"x": 2100.0}):
    assert fake._mass_for_drive("urban", "x") == 2100.0 and fake._mass_for_drive("urban", "y") == 1890.0
assert fake._mass_for_drive("urban", "x") == 1890.0
try:
    with M.MassPatch(fake, {"x": 2100.0}):
        raise RuntimeError("boom")
except RuntimeError:
    pass
assert fake._mass_for_drive("urban", "x") == 1890.0
print("test_mass_sensitivity: OK")
