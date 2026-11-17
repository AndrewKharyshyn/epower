"""M713b known-answer tests for tools/exposure_state.py (spec analyses/M712_spec.md Rev 1.1 section 5): the R(T) factor and the drive heating path return their limits, the pulse-resistance fit recovers a
known activation energy, the charge-limit map recovers a known linear law from per-drive normal-equation statistics, and the drive-heating fit recovers known (alpha, tau_d, c0, c1) from simulated slice trajectories."""
import os, sys
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import exposure_state as ES

# fR: 1 at the reference temperature, increasing as it gets colder, exact Arrhenius form
assert abs(float(ES.fR(25.0, 17.58)) - 1.0) < 1e-12
assert float(ES.fR(0.0, 17.58)) > float(ES.fR(25.0, 17.58)) > float(ES.fR(40.0, 17.58))
assert abs(float(ES.fR(0.0, 17.58)) - np.exp(17.58e3 / 8.314462618 * (1 / 273.15 - 1 / 298.15))) < 1e-9

# drive path: no current -> exponential relaxation to Tc with rate 1/tau_d; one slice of length dt
p = {"alpha": 0.013, "tau_d": 1.0, "c0": 24.0, "c1": 0.22, "EaR": 17.58}
T0, A = np.array([10.0]), np.array([15.0])
path, Te = ES.drive_path(T0, np.zeros((1, 4)), np.array([0.25]), A, p)
Tc = 24.0 + 0.22 * 15.0
k = 1 - np.exp(-0.25 / 1.0)
T = 10.0
for j in range(4):
    T = T + (Tc - T) * k
assert abs(Te[0] - T) < 1e-12 and 10.0 < Te[0] < Tc, "relaxation toward Tc"
hot = ES.drive_path(np.array([25.0]), np.full((1, 4), 2500.0), np.array([0.25]), A, p)[1][0]
cold = ES.drive_path(np.array([25.0]), np.zeros((1, 4)), np.array([0.25]), A, p)[1][0]
assert hot > cold, "I^2 heating raises the end temperature"

# pulse-resistance fit: synthetic drives with ln R = ln 110 + (Ea/R)(1/T - 1/298.15) + noise; the fit recovers Ea
rng = np.random.default_rng(3)
n = 300
Tp = rng.uniform(8, 44, n)
Ea_true = 17.6
R = 110 * np.exp(Ea_true * 1000 / ES.RGAS * (1 / (Tp + 273.15) - 1 / 298.15) + rng.normal(0, 0.02, n))
D = pd.DataFrame({"key": ["k%d" % i for i in range(n)], "day": ["d%d" % (i // 2) for i in range(n)], "R_pulse_mohm": R, "T_pulse": Tp, "soc_pulse": 60.0})
reg = pd.DataFrame({"key": D["key"], "regime": "fast"})
o = ES.fit_EaR(D, reg, nboot=100)
assert abs(o["EaR_kJmol"] - Ea_true) < 0.3 and o["EaR_ci"][0] < o["EaR_kJmol"] < o["EaR_ci"][1] and o["n"] == n

# charge-limit map from sufficient statistics: Pin = 34 + 1.5 Tmin - 1.0 (SoC - 60) + noise
rows = []
for d in range(40):
    for v in range(3):
        m = 300
        Tm = rng.uniform(-2, 19, m)
        S = rng.uniform(45, 75, m)
        y = 34.0 + 1.5 * Tm - 1.0 * (S - 60) + rng.normal(0, 0.5, m)
        X = np.column_stack([np.ones(m), Tm, S - 60.0])
        XtX, Xty = X.T @ X, X.T @ y
        r = {"day": "d%d" % d, "pin_n": m}
        for i in range(3):
            r["pin_xty_%d" % i] = Xty[i]
            for j in range(3):
                r["pin_xtx_%d%d" % (i, j)] = XtX[i, j]
        rows.append(r)
lim, b = ES.fit_limit_map(pd.DataFrame(rows), nboot=200)
assert abs(b[0] - 34.0) < 0.1 and abs(b[1] - 1.5) < 0.02 and abs(b[2] + 1.0) < 0.02, b
assert lim["b0_kW_at_0C_soc60"][1] < lim["b0_kW_at_0C_soc60"][0] < lim["b0_kW_at_0C_soc60"][2] and abs(lim["zeroCrossing_C_soc60"] + 34.0 / 1.5) < 0.2

# drive-heating fit recovers known parameters from simulated trajectories (noise 0.1 C)
K = 16
nd = 120
true = {"alpha": 0.0125, "tau_d": 0.9, "c0": 24.0, "c1": 0.22, "EaR": 17.58}
i2 = np.abs(rng.normal(30, 25, (nd, K))) ** 2 / 4
dt_h = rng.uniform(0.05, 0.4, nd) / K
A_dr = rng.uniform(5, 28, nd)
T0 = rng.uniform(12, 40, nd)
path, Te = ES.drive_path(T0, i2, dt_h, A_dr, true)
Tobs = path + rng.normal(0, 0.1, path.shape)
T_end = Te + rng.normal(0, 0.1, nd)
xd = ES.fit_drive(np.arange(nd), T0, i2, dt_h, A_dr, Tobs, T_end, 17.58)
assert abs(xd[0] - true["alpha"]) / true["alpha"] < 0.15 and abs(xd[1] - true["tau_d"]) / true["tau_d"] < 0.25 and abs(xd[3] - true["c1"]) < 0.08, xd
print("test_exposure_state: ok")
