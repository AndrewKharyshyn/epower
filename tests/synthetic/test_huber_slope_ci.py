"""Fast known-answer / determinism tests for tools/huber_slope_ci.py (M317). The full calibration (500 simulated datasets) is tools/m317_calibration.py.
Run: python tests/synthetic/test_huber_slope_ci.py"""
import os, sys
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import numpy as np, pandas as pd
import huber_slope_ci as H
import compute_drive_summary_v6 as v6

assert H.SPREAD_T_REF == v6.SPREAD_T_REF, "T_ref must match the pipeline"

# planted linear trend with day random effects: the point estimate and interval behave sensibly
rng = np.random.default_rng(3)
days = np.repeat(np.arange(40), 4)
m = days / 30.4375
adj = np.round(5.0 + 0.40 * m + rng.normal(0, 0.3, 40)[days] + rng.normal(0, 0.2, len(days)), 1)
lab = days.astype(str)
r1 = H.primary_ci(m, adj, lab, n_boot=300, seed=42)
r2 = H.primary_ci(m, adj, lab, n_boot=300, seed=42)
assert r1 == r2, "same seed must give an identical interval"
assert r1["ci95"][0] < H.second_stage_slope(m, adj) < r1["ci95"][1] and r1["failed_draws"] == 0 and not r1["inconclusive"]
assert r1["n_groups"] == 40
r3 = H.primary_ci(m, adj, lab, n_boot=300, seed=43)
assert r3["ci95"] != r1["ci95"], "a different seed must change the draws"

# week blocks: 7 consecutive days share a label
wl = H.week_labels(pd.date_range("2026-05-01", periods=15).astype(str))
assert list(wl[:7]) == [0] * 7 and list(wl[7:14]) == [1] * 7 and wl[14] == 2

# two-stage: first stage + second stage, unrounded; runs and returns an interval
n = 160
d = pd.DataFrame({"date": pd.date_range("2026-05-01", periods=40).repeat(4).astype(str)})
T = 15 + 0.2 * np.repeat(np.arange(40), 4) + rng.normal(0, 2, n)
I = 90 + 0.3 * np.repeat(np.arange(40), 4) + rng.normal(0, 25, n)
y = 10 + 0.05 * T + 0.045 * I + rng.normal(0, 0.5, n)
d[H.T_COL], d[H.I_COL], d[H.Y_COL] = T, I, y
adj0, coef = H.first_stage_adjust(T, I, y)
assert abs(coef["bT"] - 0.05) < 0.05 and abs(coef["bI"] - 0.045) < 0.02 and abs(coef["I_ref"] - np.median(I)) < 1e-9
b = H.bundle(d, np.round(adj0, 1), n_boot=120, seed=42)
assert set(b) >= {"S1", "conditional", "S2", "S2_S1", "point_slope_mv_per_month"} and b["headline"] == "S1" and all("ci95" in b[k] for k in ("S1", "conditional", "S2", "S2_S1"))
assert all(isinstance(b[k]["materially_wider_than_S1"], bool) for k in ("conditional", "S2", "S2_S1"))

# inconclusive rule: > 1% failed draws
assert H._summarise([0.1] * 90, failed=10, nonconv=0, n_groups=5, n_boot=100, label="x")["inconclusive"] is True
assert H._summarise([0.1] * 100, failed=0, nonconv=1, n_groups=5, n_boot=100, label="x")["inconclusive"] is False
print("OK huber_slope_ci: determinism, seed sensitivity, week blocks, two-stage bundle, inconclusive rule, T_ref sync")
