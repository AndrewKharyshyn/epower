#!/usr/bin/env python3
"""M317 calibration simulation (spec analyses/M317_spec.md rev 2, Validation 1). For the PRIMARY (conditional, day-clustered) and S1 (two-stage) intervals:
datasets of about 100 calendar days with the REAL drives-per-day distribution (resampled from the master's kept rows), pack temperature and peak current that
CO-TREND with time (so the first stage is not separable from the trend), day-level random effects and heavy-tailed noise. The estimand is the pipeline's own
population quantity theta = second-stage Huber slope of the adjusted series when the first stage is fitted on a very large sample from the same design (so it is
not simply the planted time slope: part of the trend is absorbed by the co-trending T and I, exactly as in the real pipeline).
Checks: bias of the point estimate relative to theta (mean error within 2 Monte-Carlo SE), and coverage of the nominal 95% interval in [0.92, 0.98] over N_SIM datasets.
Writes analyses/M317_calibration.json. Usage: python tools/m317_calibration.py [--sims 500] [--draws 1000] [--jobs 12]"""
import argparse, json, os, sys, time
import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from sklearn.linear_model import HuberRegressor

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import huber_slope_ci as H

N_DAYS = 100
B_T, B_I, SLOPE_TIME, B0 = 0.05, 0.045, 0.30, 12.0          # planted first-stage coefficients and a planted residual time trend (mV per month)


def real_counts():
    dm = pd.read_csv("drive_master.csv", usecols=["date", "ens_outlier_v2"], low_memory=False)
    dm = dm[~dm["ens_outlier_v2"].fillna(False).astype(bool)]
    return dm.groupby("date").size().values


def simulate(rng, counts, n_days=N_DAYS, reps=1):
    """One dataset: each of n_days consecutive days gets a drive count resampled from the real distribution; `reps` independent copies of every day index (population limit)."""
    rows = []
    for d in range(n_days):
        for _ in range(reps):
            n = int(rng.choice(counts))
            u = rng.normal(0, 1.0)                                             # day random effect on the spread level
            tday = 14 + 0.18 * d + rng.normal(0, 2.0)                          # warming trend: temperature co-trends with time
            iday = 85 + 0.30 * d + rng.normal(0, 8.0)                          # current co-trends with time
            Tv = tday + rng.normal(0, 3.0, n)
            Iv = np.clip(iday + rng.normal(0, 30.0, n), 20, None)
            mo = d / 30.4375
            y = B0 + B_T * Tv + B_I * Iv + SLOPE_TIME * mo + u + 0.8 * rng.standard_t(3, n)
            rows.append(pd.DataFrame({"day": d, "month": mo, "T": Tv, "I": Iv, "y": y}))
    return pd.concat(rows, ignore_index=True)


def estimand(counts, seed=7, reps=60):
    rng = np.random.default_rng(seed)
    big = simulate(rng, counts, reps=reps)
    adj, _ = H.first_stage_adjust(big["T"].values, big["I"].values, big["y"].values)
    adj = np.round(adj, 1)
    return H.second_stage_slope(big["month"].values, adj)


def one(sim, counts, draws):
    rng = np.random.default_rng(1000 + sim)
    d = simulate(rng, counts)
    adj0, _ = H.first_stage_adjust(d["T"].values, d["I"].values, d["y"].values)
    stored = np.round(adj0, 1)
    m = d["month"].values
    labels = d["day"].values
    prim = H.primary_ci(m, stored, labels, n_boot=draws, seed=42)
    s1 = H.two_stage_ci(m, d["T"].values, d["I"].values, d["y"].values, labels, n_boot=draws, seed=42)
    return {"sim": sim, "est": H.second_stage_slope(m, stored), "primary": prim.get("ci95"), "primary_bad": prim["inconclusive"],
            "S1": s1.get("ci95"), "S1_bad": s1["inconclusive"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=500)
    ap.add_argument("--draws", type=int, default=1000)
    ap.add_argument("--jobs", type=int, default=12)
    a = ap.parse_args()
    counts = real_counts()
    t0 = time.time()
    theta = estimand(counts)
    res = Parallel(n_jobs=a.jobs)(delayed(one)(s, counts, a.draws) for s in range(a.sims))
    est = np.array([r["est"] for r in res])
    out = {"spec": "analyses/M317_spec.md rev 2", "n_sims": a.sims, "draws_per_interval": a.draws, "n_days": N_DAYS,
           "drives_per_day_distribution": {"n_days_real": int(len(counts)), "mean": float(counts.mean()), "max": int(counts.max())},
           "design": {"b_T": B_T, "b_I": B_I, "planted_time_slope_mv_per_month": SLOPE_TIME, "T_trend_per_day": 0.18, "I_trend_per_day": 0.30, "day_effect_sd": 1.0, "noise": "0.8 x Student t(3)"},
           "estimand_theta_mv_per_month": theta, "point_estimate": {"mean": float(est.mean()), "sd": float(est.std(ddof=1)),
                                                                    "bias": float(est.mean() - theta), "mc_se_of_mean": float(est.std(ddof=1) / np.sqrt(len(est)))}}
    for k in ("primary", "S1"):
        ok = [r for r in res if r[k] is not None and not r[k + "_bad"]]
        cov = float(np.mean([r[k][0] <= theta <= r[k][1] for r in ok])) if ok else None
        mc = float(np.sqrt(cov * (1 - cov) / len(ok))) if ok else None
        out[k] = {"n_valid": len(ok), "coverage": cov, "mc_se": mc, "pass_band_0.92_0.98": bool(cov is not None and 0.92 <= cov <= 0.98),
                  "mean_half_width": float(np.mean([(r[k][1] - r[k][0]) / 2 for r in ok])) if ok else None}
    out["bias_within_2_mc_se"] = bool(abs(out["point_estimate"]["bias"]) <= 2 * out["point_estimate"]["mc_se_of_mean"])
    out["seconds"] = round(time.time() - t0)
    json.dump(out, open("analyses/M317_calibration.json", "w", encoding="utf-8"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
