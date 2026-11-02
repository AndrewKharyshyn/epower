"""M560 (analyses/M560_spec.md Rev 2): known-answer tests for the window finder and the variant kernels of tools/csr_sensitivity.py."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import m560_window_keys as W
import csr_sensitivity as S


def series(n_load=20, n_rest=15, k=0.0, base=10.0, drop=None, noise=0.0):
    """1 s grid: n_load seconds at I = 50 A, then n_rest seconds at 0 A; spread (mV) = base + k * I (a pure ohmic step when k > 0). Returns a grid frame and a fresh frame."""
    n = 10 + n_load + n_rest + 10
    idx = pd.date_range("2026-01-01 12:00:00", periods=n, freq="1s")
    I = np.zeros(n); I[10:10 + n_load] = 50.0
    spread = base + k * np.abs(I)
    rng = np.random.default_rng(1)
    spread = spread + (rng.integers(-1, 2, n) * noise)
    g = pd.DataFrame({"maxv": 3.6 + spread / 2000.0, "minv": 3.6 - spread / 2000.0, "I": I}, index=idx)
    fresh = pd.DataFrame(True, index=idx, columns=["maxv", "minv", "I"])
    if drop is not None:
        g.loc[idx[drop], ["maxv", "minv"]] = np.nan
    return g, fresh


# KA2 pure ohmic step: spread = base + k * |I|: V0 onset averages the last loaded row and the first rest row, so the magnitude is k * 50 / 2; the native pair level (last pair before load-off) gives k * 50
g, f = series(k=0.1)
g2, wins = W.find_windows(g, f)
assert len(wins) == 1 and abs(wins[0]["mag"] - 0.1 * 50 / 2) < 1e-9, wins
# a constant spread gives magnitude 0; a placebo on a constant spread plus 1 mV noise has median about 0
g, f = series(k=0.0)
_, wins = W.find_windows(g, f)
assert len(wins) == 1 and abs(wins[0]["mag"]) < 1e-9
n = 120
idx = pd.date_range("2026-01-01 12:00:00", periods=n, freq="1s")
rng = np.random.default_rng(3)
sp = 10.0 + rng.integers(-1, 2, n)
Ip = np.zeros(n); Ip[:40] = 10.0       # 40 s of light current (below the 20 A load level), then a 80 s rest
gp = pd.DataFrame({"maxv": 3.6 + sp / 2000.0, "minv": 3.6 - sp / 2000.0, "I": Ip}, index=idx)
pm = S.placebo_magnitudes(gp)
assert len(pm) == 1 and abs(np.median(pm)) <= 1.0
# a placebo needs a quiet lead: a rest run that follows a load is not used
gq, _ = series()
assert S.placebo_magnitudes(gq.iloc[:60]) == []
# KA3 gap inside the window: a removed second inside the rest collapses on the dropna grid; V7 flags it, V0 keeps the window
g, f = series(k=0.1, drop=[10 + 20 + 5])
g2, wins = W.find_windows(g, f)
assert len(wins) == 1 and wins[0]["gapInside"] is True
g, f = series(k=0.1)
_, wins = W.find_windows(g, f)
assert wins[0]["gapInside"] is False and wins[0]["freshAll"] is True
# freshness: a filled second at the onset is flagged and removes freshAll
g, f = series(k=0.1)
f.iloc[10 + 20 - 1, f.columns.get_loc("maxv")] = False
_, wins = W.find_windows(g, f)
assert wins[0]["onsetFilled"] is True and wins[0]["freshAll"] is False
# fill limits: build_grid with limit 0 leaves a one-second hole where the published limit 3 fills it
fr = pd.DataFrame({"time": ["12:00:%02d.000" % s for s in (0, 1, 2, 4, 5)], W.MAXV: [3.6] * 5, W.MINV: [3.59] * 5, W.CUR: [0.0] * 5})
g3, _ = W.build_grid(fr, 3, 3); g0, _ = W.build_grid(fr, 0, 3)
assert g3["maxv"].notna().all() and g0["maxv"].isna().sum() == 1
# pairing kernels: polling-cycle pairing takes the first Min after each Max within tau; nearest pairing can reuse a Min; spreads in mV
tmax = np.array([0.0, 10.0, 20.0]); vmax = np.array([3.601, 3.602, 3.603])
tmin = np.array([0.4, 10.6, 25.0]); vmin = np.array([3.590, 3.590, 3.590])
pt, ps, lo, hi = S.pair_series(tmax, vmax, tmin, vmin, "poll")
assert list(np.round(ps, 6)) == [11.0, 12.0] and list(pt) == [0.4, 10.6]
pt2, ps2, _, _ = S.pair_series(tmax, vmax, tmin, vmin, "near")
assert len(ps2) == 2
# V8 native magnitude: onset = last pair before load-off, asymptote = median of the pairs at or after load-off in the last 5 s of the rest
pt = np.array([1.0, 5.0, 9.0, 11.0, 13.0, 14.0, 16.0]); ps = np.array([20.0, 20.0, 20.0, 12.0, 10.0, 10.0, 10.0])
lo = pt - 0.3; hi = pt
mag, on, asym, strad, on2 = S.native_magnitude(pt, ps, lo, hi, t0=10.0, t1=17.0)
assert on == 20.0 and asym == 10.0 and mag == 10.0 and on2 == 12.0
# a pair straddling load-off is excluded and counted
pt = np.array([5.0, 10.2, 14.0]); ps = np.array([20.0, 15.0, 10.0]); lo = np.array([4.7, 9.8, 13.7]); hi = pt
mag, on, asym, strad, on2 = S.native_magnitude(pt, ps, lo, hi, t0=10.0, t1=15.0)
assert on == 20.0 and strad == 1
# half-time categories are counts of rows after load-off; none when the magnitude is not above 1 mV
assert S.half_category(0, 3.0) == "0" and S.half_category(2, 3.0) == "2" and S.half_category(5, 3.0) == "3plus" and S.half_category(1, 0.5) == "none"
# the stored block, when present: V0 reproduces the published window count and the pooled interval (KA1)
import json
A = json.load(open("summary_arrays.json", encoding="utf-8"))
if "cellSpreadRelaxationSensitivity" in A:
    B = A["cellSpreadRelaxationSensitivity"]
    assert B["knownAnswer"]["reproducesStored"] and B["knownAnswer"]["pooledIntervalMatchesStored"]
    assert B["knownAnswer"]["nWindows"] == A["cellSpreadRelaxation"]["nRestWindows"]
print("test_csr_sensitivity OK")
