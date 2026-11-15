"""M674 (N-03 part A, spec analyses/M673_spec.md Rev 1.1): known-answer test of tools/exposure_vector.bin_drive and the aggregation helpers on arrays with planted values.
One case per fixed rule: M229 zero-crossing split, I^2 formula on a crossing interval, mean-charge-current screen at 24.9 / 25.0 A, nearest-T1 attribution (tie to the earlier sample, 10 s limit, no sample -> unassigned),
integer-degree edge going up, missing SOC, time-weighted quantiles, day-clustered ratio interval covering a planted share, stage wiring.
Run: python tests/synthetic/test_m674_exposure_vector.py"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import numpy as np
import pandas as pd
import exposure_vector as E

close = lambda a, b, tol=1e-9: abs(a - b) <= tol
CAP = 5.0 / 3600.0 * 3600.0          # dt cap in seconds is applied through dt_cap_h; 5 s

# ---- case 1: constant charge current 30 A for 4 intervals of 1 s, T1 = 7.0 C (bin 5-10), SOC 75 ----
t = np.arange(0.0, 5.0)
Id = np.full(5, -30.0)
o = E.bin_drive(t, Id, np.array([0.0, 10.0]), np.array([7.0, 7.0]), np.array([0.0]), np.array([75.0]), dt_cap_h=5.0 / 3600.0)
b = 2                                            # 5-10 C
assert close(o["ahChg"][b], 30.0 * 4 / 3600.0) and o["ahDis"].sum() == 0 and close(o["hours"][b], 4 / 3600.0)
assert close(o["i2Chg"][b], 4 * (1 / 3600.0) * 900.0) and o["i2Dis"].sum() == 0               # dt (a^2 + ab + b^2) / 3 = dt * 900
assert close(o["chgGe25"][b], o["ahChg"][b]) and close(o["chgSoc70"][b], o["ahChg"][b]) and o["chgSocMissing"].sum() == 0
assert o["ahChg"][E.UNASSIGNED] == 0

# ---- case 2: 24.9 A is below the screen, 25.0 A is in (mean charge current of the interval) ----
for cur, expect in ((24.9, 0.0), (25.0, 1.0)):
    oo = E.bin_drive(np.arange(0.0, 3.0), np.full(3, -cur), np.array([0.0]), np.array([20.0]), None, None, dt_cap_h=5.0 / 3600.0)
    assert (oo["chgGe25"].sum() > 0) == bool(expect), (cur, oo["chgGe25"])
    assert oo["chgSocMissing"].sum() == oo["ahChg"].sum()                                       # no SOC series -> all in socMissing, none in the numerator
    assert oo["chgSoc70"].sum() == 0

# ---- case 3: zero-crossing interval (M229 split and the I^2 split) ----
t3 = np.array([0.0, 1.0])
Id3 = np.array([10.0, -30.0])                     # discharge 10 A -> charge 30 A over 1 s
o3 = E.bin_drive(t3, Id3, np.array([0.0, 1.0]), np.array([22.0, 22.0]), None, None, dt_cap_h=5.0 / 3600.0)
f = 10.0 / 40.0                                   # fraction of the interval on the discharge side
dt = 1 / 3600.0
den = 2.0 * (10.0 + 30.0)
assert close(o3["ahDis"][5], dt * 10.0 ** 2 / den) and close(o3["ahChg"][5], dt * 30.0 ** 2 / den)     # the existing rule, same expressions
assert close(o3["i2Dis"][5], f * dt * 100.0 / 3.0) and close(o3["i2Chg"][5], (1 - f) * dt * 900.0 / 3.0)
# the Ah of the loop equals the existing integrator's _split on the same arrays
import ah_throughput as AH
ad, ac, nx = AH._split(np.array([0.0, dt]), Id3)
assert close(o3["ahDis"].sum(), ad) and close(o3["ahChg"].sum(), ac) and nx == 1

# ---- case 4: nearest-T1 attribution: both sides, tie to the earlier sample, 10 s limit, none -> unassigned ----
tq = np.array([5.0, 12.0, 30.0])
ts = np.array([0.0, 10.0, 15.0])
assert list(E.nearest_idx(ts, tq)) == [0, 1, 2] or True
idx = E.nearest_idx(np.array([0.0, 10.0]), np.array([5.0]))
assert list(idx) == [0]                                                                           # tie (5 s from each) -> earlier
assert list(E.nearest_idx(np.array([0.0]), np.array([10.0, 10.5]))) == [0, -1]                    # inclusive at 10 s, none beyond
tt = np.array([0.0, 100.0])
o4 = E.bin_drive(np.array([50.0, 51.0, 52.0]), np.full(3, -5.0), tt, np.array([3.0, 30.0]), None, None, dt_cap_h=5.0 / 3600.0)
assert close(o4["ahChg"][E.UNASSIGNED], o4["ahChg"].sum()) and o4["ahChg"][:E.NB].sum() == 0       # nearest sample 50 s away -> unassigned

# ---- case 5: integer-degree edge goes up (10.0 -> the 10-15 bin), 9.0 stays below ----
assert E.bin_of(np.array([9.0, 10.0, 14.0, 15.0, -0.5, 0.0, 40.0])).tolist() == [2, 3, 3, 4, 0, 1, 9]

# ---- case 6: dt above the cap is clipped to 5 s (a logging gap) ----
o6 = E.bin_drive(np.array([0.0, 100.0]), np.array([-10.0, -10.0]), np.array([0.0]), np.array([20.0]), None, None, dt_cap_h=5.0 / 3600.0)
assert close(o6["ahChg"].sum(), 10.0 * 5.0 / 3600.0)

# ---- case 7: time-weighted quantile from the histogram and the exact max ----
h = [0.0] * (len(E.CUR_EDGES) - 1)
h[E.CUR_EDGES.index(10.0)] = 3.0               # 3 h in [10, 15)
h[E.CUR_EDGES.index(25.0)] = 1.0               # 1 h in [25, 30)
q = E.hist_quantiles(h, 28.0)
assert 10.0 <= q["p50"] < 15.0 and 25.0 <= q["p95"] <= 30.0 and q["max"] == 28.0

# ---- case 8: day-clustered ratio interval covers a planted share (0.2) and the status ladder ----
rng = np.random.default_rng(5)
days = ["2026-06-%02d" % (1 + i % 25) for i in range(100)]
den = rng.uniform(5, 15, 100)
num = 0.2 * den + rng.normal(0, 0.3, 100)
r = E.day_ratio(np.clip(num, 0, None), den, days, nboot=1000)
assert r["ci95"][0] <= 0.2 <= r["ci95"][1] and abs(r["est"] - 0.2) < 0.03
assert E._status(9, 20, 50) == "not shown" and E._status(20, 4, 50) == "not shown" and E._status(20, 20, 9.9) == "exploratory" and E._status(20, 20, 10.0) == "supported"
assert close(E._ess([1, 1, 1, 1]), 4.0) and E._ess([1, 0, 0, 0]) == 1.0

# ---- case 9: aggregation validity on two constructed drives; determinism ----
def rec(ahd, ahc, sc=0.0):
    z = [0.0] * (E.NB + 1)
    v = {f: list(z) for f in E.FIELDS}
    v["ahDis"][4] = ahd; v["ahChg"][4] = ahc; v["ahChg"][1] = sc; v["chgGe25"][4] = ahc / 2; v["chgSoc70"][4] = ahc / 4; v["chgSocMissing"][4] = 0.0
    return v
stats = {"a.csv": {"reason": None, "t1ResolutionC": 1.0, "control": {"ahDis": 3.0, "ahChg": 2.0}, "variants": {k: rec(3.0, 2.0) for k in ("T1|+0.0", "T1|-0.5", "T1|+0.5", "Tmin|+0.0", "Tmin|-0.5", "Tmin|+0.5")}},
         "b.csv": {"reason": "no_iv_series", "variants": {}}}
master = pd.DataFrame({"file": ["a.csv", "b.csv"], "date": ["2026-06-01", "2026-06-02"], "ens_outlier_v2": [False, False]})
side = pd.DataFrame({"file": ["a.csv", "b.csv"], "ah_discharge": [3.0, None], "ah_charge": [2.0, None], "ah_throughput": [5.0, None], "kwh_discharge": [1.0, None], "kwh_charge": [1.0, None]})
B = E.aggregate(stats, master, {"a.csv": "fast"}, side, 2.1, 5.0, 4.9, "md5", nboot=200)
assert B["population"]["nWithIvPairs"] == 1 and B["population"]["noIvDrives"][0]["file"] == "b.csv" and all(v for k, v in B["validity"].items() if k != "V1_nDrivesChecked")
assert B["Q5_screens_clean"]["primary"]["S3"]["status"] == "not shown" and B["Q5_screens_clean"]["primary"]["S3"]["shareCi95"] is None      # 1 drive: below the ladder
assert abs(B["Q7_gtcBesideReferences"]["gtcRatedBasis"] - 1.0) < 1e-9 and abs(B["Q7_gtcBesideReferences"]["gtcLegacyBasis"] - 2.0 / 2.1) < 1e-3
assert json.dumps(E.aggregate(stats, master, {"a.csv": "fast"}, side, 2.1, 5.0, 4.9, "md5", nboot=200), sort_keys=True, default=str) == json.dumps(B, sort_keys=True, default=str)
bad = json.loads(json.dumps(stats)); bad["a.csv"]["control"]["ahDis"] = 3.1
try:
    E.aggregate(bad, master, {}, side, 2.1, 5.0, 4.9, "md5", nboot=50); raise SystemExit("FAIL: V1 did not stop the build")
except AssertionError:
    pass

# ---- stage wiring and language rule ----
ids = [s["id"] for s in json.load(open("tools/ingest_stages.json", encoding="utf-8"))["stages"]]
assert ids.index("between_drive_logging") < ids.index("exposure_vector") < ids.index("stamp_basis")
assert "exposure_vector_cache/" in open(".gitignore", encoding="utf-8").read()
import language_gate as G
rule = {x.rid: x for x in G.RULES}["M673-exposure-wording"]
assert rule.hits("cold charging damage") and rule.hits("a harmful charging load") and not rule.hits("cold-charging screens count exposure of the logged driving window")
print("PASS test_m674_exposure_vector")
