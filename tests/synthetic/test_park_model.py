"""M709 known-answer tests for tools/park_model.py (spec analyses/M708_spec.md Rev 2): the one-state diurnal park model returns its limits, the fit recovers a known tau and offset, the
diurnal fit recovers a known amplitude and peak hour with day fixed effects, unlogged legs mixed into the fit pull tau down and the offset up (the contamination of the earlier 7.55 h fit)."""
import os, sys
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import park_model as PM

W = PM.W
# limits: g = 0 returns the end temperature; with amp 0 and no trend a long gap returns ambient + offset
assert abs(PM.park_T(30.0, 0.0, 10.0, 5.0, 0.0, 4.0, 15.0, 9.0, 0.5) - 30.0) < 1e-9
assert abs(PM.park_T(30.0, 500.0, 10.0, 5.0, 0.0, 0.0, 15.0, 9.0, 0.5) - 5.5) < 1e-6
# the boundary follows the diurnal term: at peak clock the part-boundary exceeds the mean ambient by G amp (phase lag = arctan(W tau))
tau = 9.0
G = 1 / np.sqrt(1 + (W * tau) ** 2)
t_long = PM.park_T(5.5, 1000.0, 10.0, 5.0, 0.0, 4.0, 15.0, tau, 0.5)
assert abs(t_long - (5.0 + 0.5 + G * 4.0 * np.cos(W * (10.0 + 1000.0 - 15.0) - np.arctan(W * tau)))) < 1e-6

# diurnal fit with day fixed effects: days have arbitrary levels, the sinusoid is recovered
rng = np.random.default_rng(1)
rows = []
for d in range(40):
    lvl = rng.normal(10, 6)
    for h0 in rng.uniform(6, 20, 2):
        h1 = h0 + rng.uniform(0.2, 1.0)
        rows.append({"day": "d%d" % d, "h0": h0, "h1": h1, "A0": lvl + 6.0 * np.cos(W * (h0 - 15.5)), "A1": lvl + 6.0 * np.cos(W * (h1 - 15.5))})
amp, hpk = PM._fit_diurnal(pd.DataFrame(rows))
assert abs(amp - 6.0) < 1e-6 and abs(hpk - 15.5) < 1e-6, (amp, hpk)


def frame(n, tau0, off0, seed, noise=0.1, contaminate=0):
    r = np.random.default_rng(seed)
    g = np.exp(r.uniform(np.log(0.1), np.log(60), n))
    clock0 = r.uniform(0, 24, n)
    Abar = r.uniform(-2, 25, n)
    x0 = Abar + r.uniform(0, 15, n)
    amp = np.full(n, 5.0)
    hpk = np.full(n, 15.5)
    slope = np.zeros(n)
    y = PM.park_T(x0, g, clock0, Abar, slope, amp, hpk, tau0, off0) + r.normal(0, noise, n)
    if contaminate:                                        # an unlogged leg inside the gap: the restart is warmer than any cooling model predicts
        idx = r.choice(np.flatnonzero(g > 6), contaminate, replace=False)
        y[idx] += r.uniform(3, 10, contaminate)
    D = pd.DataFrame({"x0": x0, "y": y, "gap_h": g, "clock0": clock0, "p_Abar_e": Abar, "slope": slope, "p_amp": amp, "p_hpk": hpk, "day": ["d%d" % (i // 2) for i in range(n)]})
    D["gc"] = pd.cut(D["gap_h"], PM.RC.GAP_EDGES, labels=PM.GC, right=False).astype(str)
    return D


D = frame(600, 9.0, 0.5, 7)
th = PM.fit(D)
assert abs(th[0] - 9.0) < 0.3 and abs(th[1] - 0.5) < 0.1, th
Dc = frame(600, 9.0, 0.5, 7, contaminate=45)
thc = PM.fit(Dc)
assert thc[0] < th[0] - 0.2 and thc[1] > th[1] + 0.2, ("contamination direction", th, thc)

# persistence versus model: MAE by class, model far better at long gaps
m = PM.mae_by_class(D, PM.predict(D, *th))
p = PM.mae_by_class(D, D["x0"].values)
assert m[">=12 h"] < 0.5 * p[">=12 h"] and m["<1 h"] is not None
# paired MAE difference: model minus persistence is negative with an interval below zero at long gaps
sub = D[D["gc"] == ">=12 h"]
dd = PM.paired_mae_diff(sub, PM.predict(sub, *th), sub["x0"].values, nboot=200)
assert dd["est"] < 0 and dd["hi"] < 0
# day-clustered bootstrap of the parameters is deterministic and brackets the truth
b1 = PM.boot_params(D, nboot=40)
b2 = PM.boot_params(D, nboot=40)
assert np.allclose(b1, b2) and b1[:, 0].min() < 9.0 + 0.5 and b1[:, 0].max() > 9.0 - 0.5
print("test_park_model: ok")
