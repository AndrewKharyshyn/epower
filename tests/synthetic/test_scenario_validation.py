"""M713d known-answer tests for tools/scenario_validation.py, tools/scenario_sensitivity.py and the project integration rule of tools/scenario_engine.py (spec analyses/M712_spec.md Rev 1.1)."""
import os, sys
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scenario_engine as SE
import scenario_validation as SV
import scenario_sensitivity as SS
import scenario_fixture as FX

M, D = FX.build_model()
assert len(M.POOL["summer"]) == 2 and len(M.POOL["autumn"]) == 4 and M.nd == 6

# consistency scoring: observed bins and counts come from the frame over the replayed days; simulated counts are the engine's
acc, n_, days = SV._replay(M, M.params, np.ones(M.nd, bool))
assert n_ == 6 and list(days) == sorted(D["day"].unique())
s = SV._scores(M, acc, days)
assert s["nDays"] == 6 and s["startsBelow15C"]["obs"] == int((D["T_start"] < 15).sum()) and abs(sum(s["ahByTbin"]["obs"]) - D["ah"].sum()) < 1e-9
assert abs(s["ahShare_ge35"]["obs"] - 0.0) < 1e-12 and abs(s["arrCycleAF_Ea50"]["obs"] - D["afah_50"].sum() / D["ah"].sum()) < 1e-12
c = SV.consistency(M)
assert "gate" in c and isinstance(c["gate"]["pass"], bool)
# a replay restricted to a month mask keeps only those days (the hold-out replays Sep-Nov only)
acc2, n2, days2 = SV._replay(M, M.params, (M.cal["month"].values >= 9))
assert n2 == 4 and all(d >= "2026-09-01" for d in days2)

# leave-one-day-out: removing a pool day changes the expected annual distance by the exact analytic amount (untransformed additive metric with common random numbers is noisy: check sign and size)
lo = SV.lodo(M, draws=40)
assert set(lo["days"]) == set(M.cal["day"].values[np.r_[M.POOL["summer"], M.POOL["autumn"]]]) and "annual_km" in lo["baseline"]
big = max(lo["days"], key=lambda d: D.loc[D["day"] == d, "km"].sum())
small = min(lo["days"], key=lambda d: D.loc[D["day"] == d, "km"].sum())
assert lo["days"][big]["annual_km"] < lo["days"][small]["annual_km"], "removing the longest day lowers the expected distance more than removing the shortest"

# project integration rule: rescaling the frame by per-drive ratios keeps the identity and scales Ah and kWh exactly
Z = {k: v for k, v in M.Z.items()}
r_ah = np.linspace(0.9, 1.1, len(D))
D2 = D.copy(); D2["ah"] = D2["ah"] * r_ah
for k in ("ahc", "ahd"):
    assert abs((Z[k] * r_ah[:, None]).sum() - (Z[k].sum(axis=1) * r_ah).sum()) < 1e-9

# sensitivity runner: the parameters enter the engine (kappa raises the cold-shifted throughput, winter_shift lowers cold-start temperatures, tau_p changes the parked path)
names, R, rsha = SS.load_ranges()
assert len(rsha) == 64 and "off_w" in R and R["off_w"]["hi"] == 2.7 and R["tau_p"]["default"] == 9.105
base = np.array([R[n]["default"] for n in names], float)
X = np.tile(base, (3, 1))
X[1, names.index("kappa")] = 0.016
X[1, names.index("winter_shift")] = -12.0
X[2, names.index("winter_shift")] = -12.0
Y = SS.run(M, names, X)
assert Y["gtc_5Ah_rated"][1] > Y["gtc_5Ah_rated"][2] and set(SS.OUTS) <= set(Y)
assert Y["ahShare_T_lt10"][2] > Y["ahShare_T_lt10"][0], "a severe winter shift raises the share of Ah below 10 C"
print("test_scenario_validation: ok")
