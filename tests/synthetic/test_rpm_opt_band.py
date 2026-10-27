"""M525 known-answer tests for tools/rpm_opt_band.py (analyses/M525_spec.md Rev 2): closed band edges, the 300 rpm engine-on threshold, ffill 15 vs 16 s, fine-bin collapse, ratio-of-sums day bootstrap."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import compute_summary_arrays as cs
import rpm_opt_band as R

E = R.fine_edges(list(cs.RPM_HIST_EDGES), 1850.0, 2150.0)
assert all(x in E for x in (1750, 1800, 1850, 1900, 2100, 2150, 2200, 2250, 300, 1400)) and E == sorted(set(E))

# 1 Hz drive: hand-counted. 10 s at 0 rpm, 10 s at 299.9, 10 s at 300.0, 20 s at 1850.0, 10 s at 2000, 20 s at 2150.0, 10 s at 2150.1, 10 s at 6000
t = pd.date_range("2026-01-01 00:00:00", periods=100, freq="1s")
vals = [0.0] * 10 + [299.9] * 10 + [300.0] * 10 + [1850.0] * 20 + [2000.0] * 10 + [2150.0] * 20 + [2150.1] * 10 + [6000.0] * 10
df = pd.DataFrame({"time": t.strftime("%Y-%m-%d %H:%M:%S.%f"), "Оберти двигуна (rpm)": vals})
rr, nback = R.grid_rpm(df, cs)
assert len(rr) == 100 and nback == 0
h, eq, n = R.drive_counts(rr, E, 2150.0)
assert n == 100 and eq == 20
on = R.between(h, E, 300.0, 1e9)
assert int(on) == 80                                   # 300.0 counts as engine-on, 299.9 does not
band_half_open = int(R.between(h, E, 1850.0, 2150.0))  # [1850, 2150): 20 + 10
assert band_half_open == 30
assert band_half_open + eq == 50                        # closed band adds the 20 samples exactly at 2150.0; 2150.1 and 6000 are outside
# coarse collapse reproduces direct np.histogram on the stored edges
coarse = [int(R.between(h, E, cs.RPM_HIST_EDGES[i], cs.RPM_HIST_EDGES[i + 1])) for i in range(len(cs.RPM_HIST_EDGES) - 1)]
assert coarse == list(np.histogram(rr, bins=cs.RPM_HIST_EDGES)[0])

# ffill limit 15 s: a gap of 15 s is filled, a gap of 16 s leaves the 16th second missing
def with_gap(k):
    tt = pd.date_range("2026-01-01 00:00:00", periods=60, freq="1s")
    v = [2000.0] * 60
    d = pd.DataFrame({"time": tt.strftime("%Y-%m-%d %H:%M:%S.%f"), "Оберти двигуна (rpm)": v})
    d = d.drop(d.index[10:10 + k]).reset_index(drop=True)
    return len(R.grid_rpm(d, cs)[0])
assert with_gap(15) == 60 - 0 and with_gap(16) == 59   # 15 filled; the 16th second of a 16 s gap stays NaN and is dropped

# a midnight wrap (clock goes backwards) is counted
dw = df.copy(); dw.loc[50:, "time"] = pd.date_range("2026-01-01 00:00:00", periods=50, freq="1s").strftime("%Y-%m-%d %H:%M:%S.%f")
assert R.grid_rpm(dw, cs)[1] >= 1

# ratio-of-sums day bootstrap: known point estimate, interval brackets it, deterministic, a day with one drive works
num = np.array([5.0, 3.0, 2.0, 0.0]); den = np.array([10.0, 10.0, 10.0, 10.0]); days = np.array(["d1", "d1", "d2", "d3"])
pt, ci, nd, bad = R.ratio_ci(num, den, days, nb=2000)
assert abs(pt - 10.0 / 40.0) < 1e-12 and nd == 3 and ci[0] <= pt <= ci[1] and bad == 0
assert R.ratio_ci(num, den, days, nb=2000) == (pt, ci, nd, bad)
print("OK test_rpm_opt_band: closed band, 300 rpm threshold, ffill 15/16 s, collapse, day bootstrap")
