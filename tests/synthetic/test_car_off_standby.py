"""M458 known-answer tests of the Car-OFF standby interval (spec analyses/M458_spec.md Rev 1.1, section 7): tools/standby_ci.py.
(1) coverage (pre-declared fixture and criteria): 30 days x 5 gaps, log-normal gap lengths (median 6 h, sigma 0.8, day-shared level with an intra-day variance share of 0.8), draw_pp = 0.02 gap_h + u_day + e, u_day ~ N(0, 1.0^2) shared by the gaps of a day, e ~ N(0, 0.3^2);
R = 200 replications, B = 300 draws; the day-clustered interval covers the true slope in 0.88-1.00 of the replications, the i.i.d. interval in less than 0.85; (2) the point estimate equals the Sen slope of the full data;
(3) one gap per day reproduces the i.i.d. interval within resampling noise; (4) the gap table keeps only positive gaps and counts the dropped pairs, the arrival-day key is the day of the following drive's start;
(5) the disagreement rule (25 % of the primary width, zero containment); (6) leave-one-day-out bounds; (7) non-finite draws are counted, not dropped silently."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import compute_summary_arrays as C
import standby_ci as SB
import soak_tau as ST

CAP = 2100.0


def fixture(rng, ndays=30, per_day=5, slope=0.02, sd_day=1.0, sd_e=0.3, share_x=True):
    day = np.repeat(np.arange(ndays), per_day)
    z_day = rng.standard_normal(ndays)[day]
    z_i = rng.standard_normal(ndays * per_day)
    x = np.exp(np.log(6.0) + 0.8 * (np.sqrt(0.8) * z_day + np.sqrt(0.2) * z_i)) if share_x else np.exp(np.log(6.0) + 0.8 * z_i)       # day-shared gap level (intra-day share 0.8) as in the Director's D2
    y = slope * x + sd_day * rng.standard_normal(ndays)[day] + sd_e * rng.standard_normal(ndays * per_day)
    return x, y, day


# (1) coverage
rng = np.random.default_rng(2026)
R, B, TRUE = 200, 300, 0.02
cov_c = cov_i = 0
for r in range(R):
    x, y, day = fixture(rng)
    for cl, name in ((day, "c"), (None, "i")):
        dr = ST.boot_slopes(x, y, cl, C._sen_slope, b=B, seed=int(rng.integers(1, 2**31 - 1)))
        lo, hi = np.percentile(dr, [2.5, 97.5], method="linear")
        if lo <= TRUE <= hi:
            if name == "c":
                cov_c += 1
            else:
                cov_i += 1
cov_c, cov_i = cov_c / R, cov_i / R
assert 0.88 <= cov_c <= 1.00, ("day-clustered coverage", cov_c)
assert cov_i < 0.85, ("i.i.d. coverage should fall short on clustered noise", cov_i)

# (2) point estimate = Sen slope of the full data (watts conversion exact)
x, y, day = fixture(np.random.default_rng(7))
dm_rows = []
base = pd.Timestamp("2026-03-01 06:00")
t = base
soc = 60.0
for k in range(len(x) + 1):
    start = t.floor('s')
    end = start                                                              # zero-length drive: the gap equals the difference of the start times (whole seconds)
    s0 = 60.0
    dm_rows.append(dict(date=start.strftime("%Y-%m-%d"), time_start=start.strftime("%H:%M:%S"), time_end=end.strftime("%H:%M:%S"), soc_start=s0, soc_end=s0, odo_start=0.0, odo_end=0.0))
    gap = x[k] if k < len(x) else 1.0
    t = start + pd.Timedelta(hours=float(gap))
dm = pd.DataFrame(dm_rows)
# prescribe the SoC drop of each gap: soc_end(N) - soc_start(N+1) = y[N]
for k in range(len(x)):
    dm.loc[k + 1, "soc_start"] = dm.loc[k, "soc_end"] - y[k]
gt = SB.gap_table(dm)
assert gt["nPairsTotal"] == len(x) and gt["nPairsDropped"] == 0 and len(gt["x"]) == len(x)
assert np.allclose(gt["x"], x, atol=1e-3) and np.allclose(gt["y"], y, atol=1e-9)
blk = SB.standby_block(dm, C._sen_slope, n_boot=200)
assert abs(blk["watts"] - round(C._sen_slope(gt["x"], gt["y"]) / 100.0 * CAP, 2)) < 1e-9
assert blk["nClusters"] == len(set(gt["arrival"])) and blk["nPairsDropped"] == 0 and blk["ciMethod"].startswith("whole-cluster percentile bootstrap")
assert blk["ci95WattsIid"] is not None and "not a day-clustered interval" in blk["ciIidNote"]

# (3) one gap per day: the clustered interval reproduces the i.i.d. one within resampling noise
x1, y1, d1 = fixture(np.random.default_rng(11), ndays=120, per_day=1, share_x=False)
dc = ST.boot_slopes(x1, y1, d1, C._sen_slope, b=600, seed=42)
di = ST.boot_slopes(x1, y1, None, C._sen_slope, b=600, seed=42)
wc, wi = np.percentile(dc, [2.5, 97.5]), np.percentile(di, [2.5, 97.5])
assert abs((wc[1] - wc[0]) - (wi[1] - wi[0])) < 0.2 * (wi[1] - wi[0]), (wc, wi)

# (4) gap table: positive gaps only, dropped pairs counted, arrival day = day of the following start
rows = [dict(date="2026-03-01", time_start="08:00:00", time_end="08:30:00", soc_start=70.0, soc_end=68.0, odo_start=0.0, odo_end=5.0),
        dict(date="2026-03-01", time_start="08:20:00", time_end="08:40:00", soc_start=68.0, soc_end=66.0, odo_start=5.0, odo_end=9.0),      # overlaps the previous end: gap <= 0 -> dropped
        dict(date="2026-03-02", time_start="07:00:00", time_end="07:30:00", soc_start=65.0, soc_end=64.0, odo_start=9.0, odo_end=14.0)]
g = SB.gap_table(pd.DataFrame(rows))
assert g["nPairsTotal"] == 2 and g["nPairsDropped"] == 1 and list(g["arrival"]) == ["2026-03-02"] and list(g["departure"]) == ["2026-03-01"]
assert abs(g["x"][0] - (22.0 + 20.0 / 60.0)) < 1e-6 and abs(g["y"][0] - (66.0 - 65.0)) < 1e-9 and abs(g["odoStep"][0] - (9.0 - 9.0)) < 1e-9

# (5) disagreement rule
prim = {"wattsCI": [1.0, 3.0]}
assert SB.disagreement(prim, {"a": {"wattsCI": [1.1, 3.2]}})["flag"] is False                         # shifts of 0.1 and 0.2 are within 25 % of the width 2.0
assert SB.disagreement(prim, {"a": {"wattsCI": [1.6, 3.0]}})["flag"] is True                          # lower bound moves by 0.6 > 0.5
assert SB.disagreement(prim, {"a": {"wattsCI": [-0.2, 3.0]}})["flag"] is True                         # zero containment differs (and the bound moves by 1.2)
assert "contains 0" in " ".join(SB.disagreement(prim, {"a": {"wattsCI": [-0.1, 2.9]}})["reasons"])    # the bound shifts are small, only the containment of 0 differs

# (6) leave-one-day-out
x2 = np.array([1.0, 2.0, 3.0, 4.0]); y2 = np.array([1.0, 2.0, 3.0, 40.0]); c2 = np.array(["a", "b", "c", "d"])
lo = SB.leave_one_day_out(x2, y2, c2, C._sen_slope, CAP)
assert lo["nDays"] == 4 and lo["dayAtMax"] in ("a", "b", "c") and lo["wattsMin"] <= lo["wattsMax"]

# (7) non-finite draws are counted
out = SB._interval(np.array([0.1, 0.2, np.nan, 0.3, np.inf]), CAP)
assert out["nUndefined"] == 2 and out["pPositive"] == 1.0
print("test_car_off_standby: all known-answer tests passed (coverage clustered %.3f, iid %.3f)" % (cov_c, cov_i))
