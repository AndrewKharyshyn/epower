"""M713c known-answer tests for tools/scenario_engine.py (spec analyses/M712_spec.md Rev 1.1): G-S0 replay identity (km, Ah, kWh, starts conserved exactly), per-day conservation of a repeated day, the tilt solver
(G-S1: the expected annual distance hits the target), the parked-temperature limits of the chain (huge tau_p keeps the end-of-drive temperature, tiny tau_p returns to ambient + offset), the cold throughput
multiplier kappa, and the E-exp / E-real interface."""
import os, sys
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import scenario_engine as SE
import scenario_frame as SF

K, NCB = 16, len(SF.CB) - 1
days = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-10-01", "2026-10-02", "2026-10-03"]
rows, keys = [], []
rng = np.random.default_rng(5)
for di, day in enumerate(days):
    for j in range(2):
        key = day.replace("-", "") + "%02d0000" % (8 + 6 * j)
        km = 4.0 + 3.0 * di + 2.0 * j                      # distinct km per drive
        rows.append({"key": key, "day": day, "start": pd.Timestamp(day) + pd.Timedelta(hours=8 + 6 * j), "dur_h": 0.4, "km": km, "ah": 3.0 + 0.5 * di + j, "kwh": 1.1 * (3.0 + 0.5 * di + j),
                     "soc_end": 58.0, "eng_starts": 2 + j, "T_start": 20.0, "T_end": 25.0})
        keys.append(key)
D = pd.DataFrame(rows)
for l in SF.SOCLAB:
    D["ah_S_%s" % l] = 0.0
D["ah_S_55-60"] = D["ah"]
n = len(D)
Z = {"keys": np.array(keys), "K": K, "icov": np.ones(n)}
ahc = np.tile((D["ah"].values * 0.5 / K)[:, None], (1, K)); ahd = ahc.copy()
Z.update({"i2": np.full((n, K), 400.0), "ahc": ahc, "ahd": ahd, "soc": np.full((n, K), 58.0), "Tobs": np.full((n, K), 22.0), "ep10c": np.zeros((n, K)), "ep20c": np.zeros((n, K)),
          "ep10d": np.zeros((n, K)), "ep20d": np.zeros((n, K))})
cb = np.zeros((n, K, NCB)); cb[:, :, 1] = ahc                  # all charge Ah in C-rate bin 1 (2-5 C)
Z["ahc_cb"], Z["ahcC_cb"] = cb, cb * 3.0 / SF.CAP_AH_RATED
AR = pd.DataFrame({"key": keys, "Abar_s": 10.0, "Abar_e": 10.0, "amp": 0.0, "hpk": 15.0, "h0": D["start"].dt.hour.values.astype(float), "h1": D["start"].dt.hour.values + 0.4})
amb = pd.DataFrame({"key": keys, "A0": 10.0, "A1": 10.0})
odo = {"unloggedDays": [], "noOdometerCoverDays": [], "factors": {"f_s_summerWindow": 1.1, "f_a_laterIntervalsWithoutUnlogged": 1.2}}
state = {"params_for_scenarios": {"EaR": 17.58, "park": {"tau": 9.0, "off": 0.5}, "drive": {"alpha": 0.013, "tau_d": 1.0, "c0": 24.0, "c1": 0.22}, "diurnal": {"summer": [0.0, 15.0], "autumn": [0.0, 15.0]},
                                  "pin": {"b0": 34.0, "bT": 1.5, "bS": -1.0}}}
params = SE.default_params(state, odo)
normals = np.full(12, 10.0)
M = SE.Model(D, Z, AR, amb, normals, odo, params, pool_rule="data", odo_km=3000.0)
assert len(M.POOL["summer"]) == 92 and len(M.POOL["autumn"]) == 33 and M.MAXD == 2, "calendar days incl. empty (zero-drive) days are pool days"

# G-S0: replay identity on the observed sequence (no transform, no tilt, no odometer factors)
chk = SE.replay_identity(M)
assert chk["maxAbsRelDiff"] < 1e-9, chk
assert abs(chk["km"][0] - D["km"].sum()) < 1e-9 and abs(chk["eng_starts"][0] - D["eng_starts"].sum()) < 1e-12

# a repeated day: every synthetic day draws the same source day -> totals are exactly 365 x the day (odometer factor 1, kappa 0)
src = np.full((1, 365), 1)
par = dict(M.params, f_s=1.0, f_a=1.0)
acc = SE.simulate(M, src, 0.0, par, np.ones((1, 365), bool), use_transform=True)
dayrows = D[D["day"] == days[1]]
assert abs(acc["km"][0] - 365 * dayrows["km"].sum()) < 1e-6
assert abs(acc["ahc"][0] + acc["ahd"][0] - 365 * dayrows["ah"].sum()) < 1e-6 and abs(acc["kwh"][0] - 365 * dayrows["kwh"].sum()) < 1e-6
o = SE.summarise(acc)
assert abs(o["gtc_5Ah_rated"][0] - 365 * dayrows["ah"].sum() / 5.0) < 1e-6 and abs(o["fce_5Ah_rated"][0] * 2 - o["gtc_5Ah_rated"][0]) < 1e-9
assert abs(sum(o["ah_T_%s" % l][0] for l in SF.TLAB) - o["ah_throughput"][0]) < 1e-6, "Ah by temperature bin conserved"
assert abs(sum(o["ah_SoC_%s" % l][0] for l in SF.SOCLAB) - o["ah_throughput"][0]) < 1e-6, "Ah by SoC bin conserved"
# the odometer factor scales distance and throughput (not the per-km intensity)
acc2 = SE.simulate(M, src, 0.0, dict(M.params, f_s=1.0, f_a=1.2), np.zeros((1, 365), bool), use_transform=True)
assert abs(acc2["km"][0] / acc["km"][0] - 1.2) < 1e-9 and abs((acc2["ahc"][0] + acc2["ahd"][0]) / (acc["ahc"][0] + acc["ahd"][0]) - 1.2) < 1e-9

# G-S1: the tilt solver hits the expected annual distance; tilt 0 = untilted expectation; monotone
fs, fa = 1.1, 1.2
t0 = SE.expected_km(M, SE.W_SUM_BAL, 0.0, fs, fa)
for target in (0.9 * t0, t0, 1.1 * t0):
    tilt = SE.solve_tilt(M, target, SE.W_SUM_BAL, fs, fa)
    assert abs(SE.expected_km(M, SE.W_SUM_BAL, tilt, fs, fa) - target) / target < 1e-6
tl = [SE.solve_tilt(M, x * t0, SE.W_SUM_BAL, fs, fa) for x in (0.9, 1.0, 1.1)]
assert tl[0] < tl[1] < tl[2] and abs(tl[1]) < 1e-6

# parked-temperature limits of the chain with a constant 10 C ambient, no diurnal term, no heating (alpha 0), fast drive relaxation to Tc = c0 + c1 A = 26.2 C
base = dict(M.params, f_s=1.0, f_a=1.0, alpha=0.0, tau_d=1e-3, c0=24.0, c1=0.22, off_s=0.5, off_a=0.5, off_w=0.5)
srcs = np.tile(np.array([0, 1, 2, 3, 4, 5, 0] * 53)[:365], (1, 1))
a_slow = SE.simulate(M, srcs, 0.0, dict(base, tau_p=1e6), np.zeros((1, 365), bool), use_transform=True)
a_fast = SE.simulate(M, srcs, 0.0, dict(base, tau_p=1e-3), np.zeros((1, 365), bool), use_transform=True)
Tc = 24.0 + 0.22 * 10.0
assert abs(a_slow["park_Tsum"][0] / a_slow["park_h"][0] - Tc) < 0.2, (a_slow["park_Tsum"][0] / a_slow["park_h"][0], Tc)
assert abs(a_fast["park_Tsum"][0] / a_fast["park_h"][0] - 10.5) < 0.2, a_fast["park_Tsum"][0] / a_fast["park_h"][0]       # ambient 10 + offset 0.5

# kappa: Ah throughput rises with cooling below 15 C (target month ambient 10 C shifted -10 C), not otherwise
shift = np.full(365, -10.0)
a0 = SE.simulate(M, src, shift, dict(par, kappa=0.0), np.zeros((1, 365), bool), use_transform=True)
a1 = SE.simulate(M, src, shift, dict(par, kappa=0.01), np.zeros((1, 365), bool), use_transform=True)
assert a1["ahc"][0] > a0["ahc"][0] and abs(a0["ahc"][0] - 365 * dayrows["ah"].sum() * 0.5) < 1e-6

# scenario grid interface: E-real draws and E-exp (pool bootstrap of the mean of replayed years); same metrics, E-exp interval narrower than E-real for a day-variable metric
sc = SE.scenarios(3000.0)["S2u_balanced_untilted"]
oreal, tilt = SE.run_scenario(M, sc, 60)
oexp, _ = SE.run_expected(M, sc, n_pool=30, n_inner=4)
assert oreal["annual_km"].shape == (60,) and oexp["annual_km"].shape == (30,) and "coldest_start_T" not in oexp
assert np.std(oexp["annual_km"]) < np.std(oreal["annual_km"]), (np.std(oexp["annual_km"]), np.std(oreal["annual_km"]))
assert abs(np.mean(oreal["annual_km"]) - SE.expected_km(M, SE.W_SUM_BAL, 0.0, M.params["f_s"], M.params["f_a"])) / SE.expected_km(M, SE.W_SUM_BAL, 0.0, M.params["f_s"], M.params["f_a"]) < 0.5
print("test_scenario_engine: ok")
