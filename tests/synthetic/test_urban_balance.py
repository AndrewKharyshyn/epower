"""M504 (Rev 2) known-answer tests of tools/urban_balance.py: SMD (incl. proportions), common support both ways, same-date restriction, common-support restriction, not-estimable / low-precision rules, D0 fidelity stop."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import urban_balance as UB

# SMD hand-computed: warm 1,2,3 (mean 2, sd 1), shoulder 2,3,4 (mean 3, sd 1) -> 1.0 ; proportions 0.2 vs 0.6 -> 0.4 / sqrt((0.16 + 0.24) / 2) = 0.8944
assert abs(UB.smd(pd.Series([1.0, 2, 3]), pd.Series([2.0, 3, 4])) - 1.0) < 1e-12
w, s = pd.Series([1.0] * 2 + [0.0] * 8), pd.Series([1.0] * 6 + [0.0] * 4)
assert abs(UB.smd(w, s, proportion=True) - 0.4 / np.sqrt((0.16 + 0.24) / 2)) < 1e-12
assert UB.smd(pd.Series([1.0]), pd.Series([2.0, 3])) is None and UB.smd(pd.Series([2.0, 2, 2]), pd.Series([2.0, 2, 2])) is None
# common support in both directions on a hand table: reference 0..100 (P5=5, P95=95)
ref = pd.Series(np.arange(0, 101, dtype=float))
assert UB.inside_share(pd.Series([0.0, 50.0, 100.0, 96.0]), ref) == 0.25 and UB.inside_share(pd.Series([], dtype=float), ref) is None

# synthetic corpus: warm days 0..59, shoulder days 40..99 (20 shared days); intensity 25 everywhere except +5 on shoulder-only days >= 60
rng = np.random.default_rng(5)
rows = []
for day in range(100):
    for cohort in ("warm", "shoulder"):
        if (cohort == "warm" and day > 59) or (cohort == "shoulder" and day < 40):
            continue
        for j in range(3):
            km = float(rng.uniform(2, 9))
            inten = 25.0 + (5.0 if (cohort == "shoulder" and day >= 60) else 0.0)
            tstart = float(rng.uniform(15, 30) - (8 if cohort == "shoulder" else 0))
            rows.append({"day": "2026-%02d-%02d" % (5 + day // 28, 1 + day % 28), "thermal_regime": cohort, "distance_km": km, "gross_throughput_kwh": inten * km / 100.0,
                         "startHour": float(rng.uniform(6, 20) + (3 if cohort == "shoulder" else 0)), "socStart": float(rng.uniform(45, 70)), "tPackStart": tstart, "tPackMean": tstart + 2.0,
                         "speedMoving": 30.0, "dayOfYear": float(day), "distance": km, "weekend": float(day % 7 >= 5)})
g = pd.DataFrame(rows)
b = UB.balance(g)
assert b["tPackStart"]["smd"] < -1.0 and b["dayOfYear"]["smd"] > 0.5 and abs(b["weekend"]["smd"]) < 1.0
assert 0.0 <= b["tPackStart"]["shoulderInsideWarmP5P95"] <= 1.0 and b["tPackStart"]["warmInsideShoulderP5P95"] is not None
# the mean-over-drive temperature is described but never used for the common-support restriction
assert "tPackMean" not in UB.CS_COVS and set(UB.CS_COVS) == {"startHour", "socStart", "tPackStart"}
mk = lambda: {"D0": np.random.default_rng(UB.CUBE_SEED + 2), "D1": np.random.default_rng(43), "D2": np.random.default_rng(44), "D3": np.random.default_rng(45)}
d0 = UB.design_result(g, np.random.default_rng(UB.CUBE_SEED + 2), UB.CUBE_DRAWS)
cube = {"estimate": d0["estimate"], "ci95": d0["ci95"]}
d = UB.designs(g, mk(), cube)
assert d["nSharedDates"] == 20 and d["D0"]["estimate"] > 1.0 and d["D0"]["includesZero"] is False
assert d["D1"]["estimable"] and abs(d["D1"]["estimate"]) < 1e-6 and d["D1"]["includesZero"] is True        # on shared days the true contrast is 0
v = UB.verdict(d)
assert v["verdict"].startswith("reading depends on the design") and v["differing"][0]["design"] == "D1" and v["differing"][0]["flip"] == "excludes zero -> includes zero"
assert d["D3"]["warm"]["nDrives"] <= min(d["D1"]["warm"]["nDrives"], d["D2"]["warm"]["nDrives"])
# D0 fidelity stop: an altered released estimate STOPs
try:
    UB.designs(g, mk(), {"estimate": cube["estimate"] + 0.01, "ci95": cube["ci95"]}); raise AssertionError("D0 mismatch must STOP")
except SystemExit:
    pass
# not estimable: fewer than 10 drives or 5 days in a cohort; low precision with 5-9 days
small = g[g.day.isin(sorted(set(g.day))[:3])]
assert UB.design_result(small, np.random.default_rng(1), 400)["estimable"] is False
few = g[g.day.isin(sorted(set(g[g.thermal_regime.eq("warm") & g.day.isin(sorted(set(g.day))[40:60])].day))[:7]) & g.thermal_regime.eq("warm") | g.day.isin(sorted(set(g.day))[40:47]) & g.thermal_regime.eq("shoulder")]
r = UB.design_result(few, np.random.default_rng(2), 400)
assert r.get("estimable") is True and r["lowPrecision"] is True, r
# verdicts: a non-decisive design counts as not estimable (never a differing reading)
dd = {"D0": {"estimable": True, "includesZero": False}, "D1": {"estimable": True, "includesZero": True, "nonDecisive": True}, "D2": {"estimable": False}, "D3": {"estimable": False}}
assert UB.verdict(dd)["verdict"] == "not assessable"
print("test_urban_balance: OK")
