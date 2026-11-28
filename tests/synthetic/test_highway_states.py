"""M792 known-answer tests (analyses/M792_spec.md Rev 2, D4) for tools/highway_states.py."""
import os, sys
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import highway_states as H


def close(a, b, tol=1e-9):
    assert abs(a - b) < tol, (a, b)


# 1. planted seconds: zone 80-100 (index 4): 10 s S1 (rpm 1500, Id +10), 6 s S2 (rpm 1500, Id -10), 4 s S3 (rpm 0, Id +10 must not count as S1)
speed = np.full(20, 90.0)
rpm = np.r_[np.full(16, 1500.0), np.zeros(4)]
Id = np.r_[np.full(10, 10.0), np.full(6, -10.0), np.full(4, 10.0)]
z = H.zone_seconds(speed, rpm, Id, np.ones(20))
assert (z["z4_B"], z["z4_S1"], z["z4_S2"], z["z4_S3"]) == (20.0, 10.0, 6.0, 4.0), z
assert z["z3_B"] == 0.0 and z["z5_B"] == 0.0

# 2. an exact zone edge belongs to the upper zone; exactly 120.0 is in 120+ but inside the inclusive 80-120 band
z = H.zone_seconds([80.0, 100.0, 120.0, 119.99], [1000] * 4, [5] * 4, [1] * 4)
assert z["z4_B"] == 1.0 and z["z5_B"] == 2.0 and z["z6_B"] == 1.0, z      # 80 -> 80-100; 100 and 119.99 -> 100-120; 120 -> 120+
assert z["B_i"] == 4.0 and z["T120"] == 1.0 and z["T120E"] == 1.0 and z["T120D"] == 1.0
close(z["z4_B"] + z["z5_B"] + z["T120"], z["B_i"])                     # the reconciliation identity of D1

# 3. NaN rpm counts as S3 and is counted as missing; NaN Id with the engine on falls in S2 and is counted; rpm exactly 400 is not turning; NaN speed is in no zone
z = H.zone_seconds([50, 50, 50, np.nan], [np.nan, 1000, 400.0, 1000], [5, np.nan, 5, 5], [1, 1, 1, 1])
assert (z["z2_B"], z["z2_S1"], z["z2_S2"], z["z2_S3"], z["z2_Nrpm"], z["z2_Nid"]) == (3.0, 0.0, 1.0, 2.0, 1.0, 1.0), z
assert sum(z["z%d_B" % k] for k in range(7)) == 3.0

# 4. partition identity per zone, non-uniform dt
rng = np.random.default_rng(1)
sp, rp, ii, dt = rng.uniform(0, 160, 500), rng.choice([0, 350, 450, 2000.0, np.nan], 500), rng.normal(0, 20, 500), rng.uniform(0.1, 3, 500)
z = H.zone_seconds(sp, rp, ii, dt)
for k in range(7):
    close(z["z%d_S1" % k] + z["z%d_S2" % k] + z["z%d_S3" % k], z["z%d_B" % k], 1e-9)
close(sum(z["z%d_B" % k] for k in range(7)), dt.sum(), 1e-9)

# 5. sensitivities: rpm 300 admits rpm 350; dead band 5 A drops Id 3 from S1 and keeps it in S2 at the engine-on level
z = H.zone_seconds([50, 50], [350.0, 1000.0], [3.0, 3.0], [1, 1])
assert z["z2_S1"] == 1.0 and z["z2_S1_300"] == 2.0 and z["z2_S1_5"] == 0.0 and z["z2_S1_2"] == 1.0

# 6. bootstrap known answer: three days, constant per-day share -> the point estimate is exact, interval is inside the data range, states share one draw set
day = np.array(["d1", "d1", "d2", "d3"]); B = np.array([100.0, 100.0, 100.0, 100.0])
S1 = np.array([20.0, 20.0, 60.0, 40.0]); S2 = B - S1
e = H.estimates(day, B, {"S1": S1, "S2": S2}, 120.0)
assert e is None                                                       # nothing reaches the 120 s floor
e = H.estimates(day, B, {"S1": S1, "S2": S2}, 50.0, draws=500)
close(e["S1"]["perDriveMean"]["est"], 35.0); close(e["S1"]["pooled"]["est"], 35.0)
assert 20.0 - 1e-9 <= e["S1"]["perDriveMean"]["lo"] <= 35.0 <= e["S1"]["perDriveMean"]["hi"] <= 60.0 + 1e-9
for q in ("perDriveMean", "pooled"):                                   # shared draws: the S1 and S2 intervals are mirror images (S1 + S2 = 100 in every draw)
    close(e["S1"][q]["lo"] + e["S2"][q]["hi"], 100.0, 1e-9); close(e["S1"][q]["hi"] + e["S2"][q]["lo"], 100.0, 1e-9)
# per-drive mean differs from pooled when drive seconds differ
e2 = H.estimates(np.array(["d1", "d2"]), np.array([100.0, 300.0]), {"S1": np.array([100.0, 0.0])}, 50.0, draws=50)
close(e2["S1"]["perDriveMean"]["est"], 50.0); close(e2["S1"]["pooled"]["est"], 25.0)
# a drive below the floor is excluded from the per-drive mean
e3 = H.estimates(np.array(["d1", "d2", "d3"]), np.array([200.0, 200.0, 10.0]), {"S1": np.array([100.0, 100.0, 10.0])}, 120.0, draws=50)
assert e3["nDrives"] == 2 and abs(e3["S1"]["perDriveMean"]["est"] - 50.0) < 1e-9

# 7. claim verdict: both inside -> aboutHalf; one fully outside -> falsified; straddling -> inconclusive
mk = lambda a, b, c, d: {"S1": {"perDriveMean": {"lo": a, "hi": b}, "pooled": {"lo": c, "hi": d}}}
assert H.claim_verdict(mk(45, 55, 44, 58)) == "aboutHalf"
assert H.claim_verdict(mk(45, 55, 61, 70)) == "falsified"
assert H.claim_verdict(mk(38, 55, 45, 55)) == "inconclusive"
print("ok test_highway_states")
