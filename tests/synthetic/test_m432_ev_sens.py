"""M432 known-answer tests (spec analyses/M432_spec.md Rev 2 + 2.1; criteria declared there before any result), tools/m432_ev_sens.py.
(i) exact 1 s series, runs >= 3 s: S0 recovers the planted share and every variant agrees; (ii) 2 s engine-ON bursts inside an off run: debounce 3 raises the share by exactly their distance;
(iii) 2 s OFF flickers inside an on run: debounce 3 LOWERS it by exactly their distance (the debounce can push the share either way: the F04 point); (iv) fixed-phase polling 0.2 + 1.5 k s with tolerance 0.5 s covers
2 of every 3 grid seconds -> invalid, unknown never off, and the inclusive tolerance boundary on its own; (v) backward / forward versus nearest on a planted step move the boundary by exactly one second (hand-computed);
(vi) real-data parity of the evaluator at S0 against v6._ev_metrics on 10 drives chosen by a declared rule; (vii) unknown RPM gaps shorter than 3 s: the debounce input treats unknown as ON, the first run is exempt, & known afterwards;
plus: the debounce is identical to v6._ev_debounce, and the three-piece support split adds up (support lost + detector + support gained = own-support share - S0) with the 90 % comparability rule."""
import hashlib, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import m432_ev_sens as E
import compute_drive_summary_v6 as v6

T0 = pd.Timestamp("2026-01-01 00:00:00")
N = 100
GRID = pd.date_range(T0, periods=N, freq="1s")
DKM = np.full(N, 0.01)                                           # 36 km/h everywhere: 0.01 km per grid second


def eng_series(times_s, values):
    return pd.DataFrame({"t": T0 + pd.to_timedelta(np.asarray(times_s, float), unit="s"), "v": np.asarray(values, float)})


def share_km(rpm, thr=400, deb=3):
    return E.ev_from_arrays(np.asarray(rpm, float), DKM, 1.0, thr, deb)


# ---- the debounce is identical to the released one
rng = np.random.default_rng(0)
for _ in range(200):
    s = pd.Series(rng.random(rng.integers(1, 60)) < 0.5)
    for n in range(0, 11):
        assert np.array_equal(E.debounce(s.values, n), v6._ev_debounce(s, n).values if n > 0 else s.values), (n, s.values)

# ---- (i) exact 1 s series, runs >= 3 s
sched = np.r_[np.zeros(30), np.full(20, 1500.0), np.zeros(50)]                        # off 30 s, on 20 s, off 50 s -> 80 off seconds = 0.8 km
eng = eng_series(np.arange(N), sched)
for aid, (d, tol) in E.ALIGN.items():
    if aid == "n0.5":
        continue
    rpm = E.align_rpm(GRID, eng, d, tol)
    for thr in E.THRESHOLDS:
        for deb in (0, 2, 3, 5):
            km, ts = share_km(rpm, thr, deb)
            assert abs(km - 0.8) < 1e-9 and ts == 80, (aid, thr, deb, km, ts)
# (ii) 2 s ENGINE-ON burst inside an off run
s2 = np.zeros(N); s2[40:42] = 1500.0
rpm = E.align_rpm(GRID, eng_series(np.arange(N), s2), "nearest", 3.0)
assert abs(share_km(rpm, 400, 3)[0] - 1.00) < 1e-9 and abs(share_km(rpm, 400, 0)[0] - 0.98) < 1e-9      # B=3 absorbs the burst: +0.02 km exactly; B=0 keeps it
assert abs(share_km(rpm, 400, 2)[0] - 0.98) < 1e-9                                                      # a run of 2 is not shorter than 2
# (iii) 2 s OFF flicker inside an on run: the debounce LOWERS the share
s3 = np.full(N, 1500.0); s3[40:42] = 0.0
rpm = E.align_rpm(GRID, eng_series(np.arange(N), s3), "nearest", 3.0)
assert abs(share_km(rpm, 400, 3)[0] - 0.00) < 1e-9 and abs(share_km(rpm, 400, 0)[0] - 0.02) < 1e-9

# ---- (iv) fixed-phase polling: samples at 0.2 + 1.5 k s, nearest tolerance 0.5 s -> coverage 2/3
eng4 = eng_series(0.2 + 1.5 * np.arange(0, 70), np.zeros(70))                          # an engine that is off the whole time
rpm = E.align_rpm(GRID, eng4, "nearest", 0.5)
cov = float((~np.isnan(rpm)).mean())
assert 0.66 <= cov <= 0.68, cov
assert not E.gate_ok({"covSpeed": 1.0, "pollS": 1.5, "distOdo": 10.0, "k": 1.0}, round(cov, 4), 0.95)
km, ts = share_km(rpm, 400, 3)
assert ts == int((~np.isnan(rpm)).sum()), "unknown seconds must never be counted as off"                # only the known seconds are off
# inclusive tolerance boundary on its own
for dist_s, expect_known in ((0.5, True), (0.6, False)):
    e = eng_series([dist_s], [0.0])
    r_ = E.align_rpm(GRID[:3], e, "nearest", 0.5)
    assert (not np.isnan(r_[0])) == expect_known, (dist_s, r_)

# ---- (v) planted step: samples every 2 s at -1.7 + 2k (polling starts before the grid so that backward alignment has a sample at the grid start), off while the SAMPLE time < 50, on from 50.3
ts_ = -1.7 + 2.0 * np.arange(0, 62)
vals = np.where(ts_ < 50.0, 0.0, 1500.0)
eng5 = eng_series(ts_, vals)
res = {}
for aid in ("n3.0", "b6.0", "f6.0"):
    d, tol = E.ALIGN[aid]
    res[aid] = share_km(E.align_rpm(GRID, eng5, d, tol), 400, 0)
assert res["n3.0"][1] == 50 and res["b6.0"][1] == 51 and res["f6.0"][1] == 49, res                      # nearest: g<=49 off; backward: g<=50; forward: g<=48
assert abs(res["b6.0"][0] - res["n3.0"][0] - 0.01) < 1e-9 and abs(res["n3.0"][0] - res["f6.0"][0] - 0.01) < 1e-9

# ---- (vii) unknown gaps: debounce input = known & (rpm <= T), unknown counts as ON, first run exempt, & known afterwards
nan = np.nan
cases = [
    ([0] * 10 + [nan] * 2 + [0] * 10, 3, 20), ([0] * 10 + [nan] * 2 + [0] * 10, 0, 20),                      # unknown inside an off run: never counted as off
    ([nan] * 2 + [0] * 10, 3, 10),                                                                          # first run exempt
    ([1500] * 10 + [nan] * 2 + [0] * 10, 3, 10), ([0] * 10 + [nan] * 2 + [1500] * 10, 3, 10),
    ([nan] * 5 + [0] * 2 + [1500] * 10, 3, 0), ([nan] * 5 + [0] * 2 + [1500] * 10, 0, 2),                    # a 2 s off island after an unknown gap: absorbed by B=3, kept by B=0
    ([1500] * 5 + [0] * 2 + [nan] + [0] * 2 + [1500] * 5, 3, 0), ([1500] * 5 + [0] * 2 + [nan] + [0] * 2 + [1500] * 5, 0, 4),   # unknown counts as ON inside the debounce: the islands are NOT merged
]
for arr, deb, expect in cases:
    a = np.asarray(arr, float)
    off = E.off_state(a, 400, deb)
    assert int(off.sum()) == expect, (arr, deb, int(off.sum()), expect)
    assert not off[np.isnan(a)].any(), "an unknown second was counted as off"

# ---- the three-piece split and the comparability rule on a small synthetic study
files = ["d1", "d2", "d3", "d4"]
dm = pd.DataFrame({"file": files, "distance_km": [10.0] * 4, "date": ["2026-05-01", "2026-05-01", "2026-05-02", "2026-05-02"], "ev_valid": [True, True, True, False], "ens_outlier_v2": [False] * 4})
s0km = [4.0, 3.0, 2.0, 1.0]
per = {}
for i, f in enumerate(files):
    ev = {"%s|%d|%d" % (a, t, b): (s0km[i], 100) for a in E.ALIGN for t in E.THRESHOLDS for b in E.DEBOUNCES}
    per[f] = {"nGrid": 1000, "covSpeed": 1.0, "pollS": 1.0, "distOdo": 10.0, "k": 1.0, "cov": {a: 1.0 for a in E.ALIGN}, "ev": ev, "valid95": {}}
for i, f in enumerate(files):                                                                             # backward 6.0 s at (400, 3): +0.5 km on each drive
    per[f]["ev"]["b6.0|400|3"] = (s0km[i] + 0.5, 100)
per["d2"]["cov"]["n1.0"] = 0.5                                                                            # d2 loses validity under nearest 1.0 s
S = E.Study(dm, per)
p, C, Pv = S.pieces("b6.0", 400, 3, 0.95)
assert abs(p["detectorPp"] - 5.0) < 1e-9 and abs(p["supportLostPp"]) < 1e-9, p                            # (+0.5 km x 3 drives) / 30 km
assert abs(p["supportGainedPp"] - (30.0 - 35.0)) < 1e-9 and p["nValidOwn"] == 4 and p["nCommon"] == 3, p     # d4 enters (own share 12/40 = 30 %), common 10.5/30 = 35 %
assert abs(p["supportLostPp"] + p["detectorPp"] + p["supportGainedPp"] - p["totalPp"]) < 1e-9
assert p["comparable"] is True
p2, _, _ = S.pieces("n1.0", 400, 3, 0.95)
assert p2["nCommon"] == 2 and p2["comparable"] is False and abs(p2["nCommonPct"] - 66.7) < 0.05, p2         # < 90 % of the released drives
assert abs(p2["supportLostPp"] + p2["detectorPp"] + p2["supportGainedPp"] - p2["totalPp"]) < 1e-9

# ---- (vi) real-data parity at S0 on 10 drives chosen by the declared rule (5 fast-era, 5 slow-era valid drives with the smallest sha256("432|" + file))
import replay_master as R
dmr = pd.read_csv("drive_master.csv", low_memory=False)
val = dmr[dmr["ev_valid"].astype(str) == "True"]
pick = []
for fast in (True, False):
    sub = val[(val["ev_rpm_dt_med_s"] < 1.0) == fast].copy()
    sub["_h"] = sub["file"].map(lambda f: hashlib.sha256(("432|" + f).encode()).hexdigest())
    pick += list(sub.sort_values("_h")["file"].head(5))
assert len(pick) == 10 and len(set(pick)) == 10
raw_dir = R.raw_dir_default()
for f in pick:
    b = open(R.resolve(raw_dir, f), "rb").read()
    rel = v6._ev_metrics(b)
    var = E.drive_variants(b, {"n3.0": E.ALIGN["n3.0"]})
    km, ts = var["ev"]["n3.0|400|3"]
    assert round(km, 3) == rel["ev_dist_km"] and ts == rel["ev_time_s"] and var["cov"]["n3.0"] == rel["ev_cov_rpm"] and var["covSpeed"] == rel["ev_cov_speed"], (f, km, rel["ev_dist_km"], ts, rel["ev_time_s"])
    inp = {"covSpeed": var["covSpeed"], "pollS": var["pollS"], "distOdo": var["distOdo"], "k": var["k"]}
    assert E.gate_ok(inp, var["cov"]["n3.0"], 0.95) == rel["ev_valid"], f
print("OK test_m432_ev_sens")
