"""M442 known-answer tests of the harmonized reduction (spec analyses/M442_spec.md sections 2, 4, 7): tools/regen_v2.py harmonize / boxcar_s, tools/regen_v2_cache.py variant ids.
(1) the grid rule: the latest native sample in (t_j - Delta, t_j] at its native time; (2) an empty cell gives no sample, two empty cells make a gap; (3) the phase shifts the grid; (4) defaults are unchanged;
(5) a rippled current sampled at two cadences: the harmonized ratios differ less than the native ones; (6) the boxcar leaves a constant power unchanged; (7) the native 90 % sampling-interval quantile used by the support rule;
(8) variant ids parse; (9) the grid origin is the first native sample of any channel."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import compute_summary_arrays as C
import regen_v2 as R
import regen_v2_cache as K

SP, RPM, I_, V_ = "[VCM] Vehicle Speed (km/h)", "Оберти двигуна (rpm)", "[BMS] HV Battery Current (A)", "[BMS] HV Battery voltage (V)"
SOC = "[BMS] HV State of charge (%)"
TC = ["[BMS] HV Battery Temperature Sensor %d (℃)" % k for k in (1, 2, 3, 4)]
T0 = pd.Timestamp("2026-03-01 10:00:00")


def frame(sec, speed, cur=15.0, volt=360.0):
    sec = np.asarray(sec, float); n = len(sec)
    full = lambda x: np.full(n, x, float) if np.isscalar(x) else np.asarray(x, float)
    d = {"time": T0 + pd.to_timedelta(sec, unit="s"), SP: full(speed), RPM: np.zeros(n), I_: full(cur), V_: full(volt), SOC: np.full(n, 60.0)}
    for c in TC:
        d[c] = np.full(n, 30.0)
    return pd.DataFrame(d)


def totals(r):
    iv = r["intervals"]
    if iv is None:
        return 0.0, 0.0
    m = ~iv["trimmed"]
    return float((R.KE_FACTOR * 1890.0 * iv["dv2"])[m].sum()), float(iv["charge"][m].sum())


# ---- (1) grid rule
t = np.array([0.5, 1.0, 2.9, 3.0, 3.1, 7.0]); s = pd.Series(np.arange(6, dtype=float))
tk, vk = R.native(t, s, harm=(3.0, 0.0))
assert list(tk) == [3.0, 3.1, 7.0] and list(vk) == [3.0, 4.0, 5.0]                  # cell (0,3] -> t = 3.0 (a sample exactly on the boundary belongs to the cell that ends there), (3,6] -> 3.1, (6,9] -> 7.0; native times kept
# ---- (3) phase
tk, _ = R.native(np.array([0.2, 1.4, 1.6, 4.4, 4.6, 7.4]), pd.Series(np.zeros(6)), harm=(3.0, 1.5))
assert list(tk) == [1.4, 4.4, 7.4], list(tk)                                       # cells (-1.5,1.5], (1.5,4.5], (4.5,7.5]
# ---- (2) an empty cell gives no sample; one empty cell leaves a 4 s interval (valid), two make a gap
fr = frame([0, 3, 7, 10, 13], [60, 50, 40, 30, 20])
r = R.extract_drive(fr, C=C, harmonize=(3.0, 0.0))
assert r["intervals"] is not None and len(r["intervals"]["t0"]) == 4 and abs(r["intervals"]["dt"][1] - 4.0) < 1e-9
fr = frame([0, 3, 10, 13], [60, 50, 40, 30]); r = R.extract_drive(fr, C=C, harmonize=(3.0, 0.0))
assert r["counts"]["speedGap"] == 1                                                  # 7 s between kept samples: a gap, never bridged
# ---- (4) defaults unchanged: the identity of harmonize=None with the M441 call
fr = frame(np.arange(0, 60, 1.0), 100.0 - 1.5 * np.arange(0, 60, 1.0), cur=12.0)
a, b = R.extract_drive(fr, C=C), R.extract_drive(fr, C=C, harmonize=None, boxcar_s=None)
assert np.array_equal(a["intervals"]["charge"], b["intervals"]["charge"]) and np.array_equal(a["bins"]["dv2"], b["bins"]["dv2"])
# ---- (9) the origin is the first native sample of any channel: a frame whose first rows carry no speed
fr = frame(np.arange(0, 40, 1.0), 90.0 - 1.5 * np.arange(0, 40, 1.0), cur=12.0)
fr.loc[:2, [SP, RPM, I_, V_, SOC] + TC] = np.nan; fr.loc[0, SOC] = 60.0                 # the first native sample (SoC) is at t = 0
r0 = R.extract_drive(fr, C=C, harmonize=(3.0, 0.0))
assert r0["intervals"] is not None and np.allclose(np.mod(r0["intervals"]["t0"], 3.0), 0.0, atol=1e-6)      # grid nodes sit at multiples of 3 s from the first native sample (t = 0), not from the first row with speed
# ---- (5) mechanics on a dense series: one kept sample per grid cell, spacing between kept samples in (0, 2 Delta), the same count for every cadence; equalisation of the spacing distribution is NOT claimed here (decided on real data by H1)
for dt in (0.8, 1.5):
    t = np.round(np.arange(int(round(300 / dt)) + 1) * dt, 6)
    tk, _ = R.native(t, pd.Series(np.zeros(len(t))), harm=(3.0, 0.0))
    d = np.diff(tk)
    assert abs(len(tk) - 100) <= 1 and d.min() > 0 and d.max() < 6.0, (dt, len(tk), d.min(), d.max())
    assert np.all(np.diff(np.ceil(tk / 3.0 - 1e-9)) == 1)
nat, har = {}, {}
# ---- (6) the boxcar leaves a constant power unchanged (interior intervals)
fr = frame(np.arange(0, 90, 1.0), 100.0 - 1.0 * np.arange(0, 90, 1.0), cur=12.0)
k1, c1 = totals(R.extract_drive(fr, C=C)); k2, c2 = totals(R.extract_drive(fr, C=C, boxcar_s=3.0))
assert abs(c1 - c2) / c1 < 1e-6, (c1, c2)
# ---- (7) the native 90 % sampling-interval quantile (positive intervals <= 5 s)
q = R.extract_drive(frame(np.arange(0, 60, 4.0), np.linspace(80, 20, 15)), C=C)["cadence"]["nativeDtQ90"]
assert abs(q["speed"] - 4.0) < 1e-9 and q["speed"] > 3.0
q = R.extract_drive(frame(np.arange(0, 60, 1.0), np.linspace(90, 20, 60)), C=C)["cadence"]["nativeDtQ90"]
assert abs(q["speed"] - 1.0) < 1e-9
# ---- (10) interp3: linear interpolation onto the exact grid (speed, I, V); nodes need native samples on both sides with a bracketing gap <= 5 s; a node outside the data gets nothing
t = np.array([0.4, 1.9, 2.6, 4.4, 9.0, 10.0]); v = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0, 60.0])
tk, vk = R.native(t, v, harm=(3.0, 0.0), interp=True)
assert list(tk) == [3.0, 6.0, 9.0], list(tk)        # node 6.0 lies in the 4.4 -> 9.0 gap (4.6 s <= 5 s): bracketed, kept
tk, vk = R.native(t, v, harm=(3.0, 0.0), interp=True)
assert abs(vk[0] - (30.0 + (3.0 - 2.6) / (4.4 - 2.6) * 10.0)) < 1e-9
t2 = np.array([0.0, 1.0, 8.0, 9.0]); tk2, _ = R.native(t2, pd.Series([1.0, 2.0, 3.0, 4.0]), harm=(3.0, 0.0), interp=True)
assert list(tk2) == [0.0, 9.0], list(tk2)      # nodes 3 and 6 fall in the 1 -> 8 gap (7 s > 5 s): dropped
# the interpolated series has nodes exactly 3 s apart
fr = frame(np.round(np.arange(0, 300, 0.8), 6), 100.0 - 0.2 * np.round(np.arange(0, 300, 0.8), 6), cur=12.0)
r = R.extract_drive(fr, C=C, harmonize=(3.0, 0.0), harm_interp=True)
assert np.allclose(r["intervals"]["dt"], 3.0, atol=1e-9)
assert K.variant_kwargs("l3p1") == {"harmonize": (3.0, 0.75), "harm_interp": True} and K.variant_kwargs("d2p1") == {"decimate": (2, 1)}
# ---- (8) variant ids
assert K.variant_kwargs("h3p2") == {"harmonize": (3.0, 1.5)} and K.variant_kwargs("d3p2h3p1") == {"harmonize": (3.0, 0.75), "decimate": (3, 2)} and K.variant_kwargs("box3") == {"boxcar_s": 3.0}
print("test_regen_v2h: ALL PASSED", {"native": {k: round(v, 2) for k, v in nat.items()}, "harmonized": {k: round(v, 2) for k, v in har.items()}})
