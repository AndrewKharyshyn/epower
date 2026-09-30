#!/usr/bin/env python3
"""M317 calibration simulation (spec analyses/M317_spec.md rev 2 + Amendment 1, Validation 1). For the PRIMARY (conditional, day-clustered) and S1 (two-stage) intervals:
datasets of about 100 calendar days with the REAL drives-per-day distribution (resampled from the master's kept rows), pack temperature and peak current that
co-trend with time with a strength set by --scale (1.0 = design 1: T +0.18 C/day, I +0.30 A/day; design 2 = weak co-trend), day-level random effects and heavy-tailed noise.
The estimand is the pipeline's own population quantity theta = second-stage Huber slope of the adjusted series when the first stage is fitted on a very large sample from
the same design (part of the planted time trend is absorbed by the co-trending T and I, exactly as in the real pipeline).
Checks: bias of the point estimate (spec: within 2 bootstrap SE per dataset; stricter script check: mean error within 2 Monte-Carlo SE, both reported) and coverage of the nominal
95% interval in [0.92, 0.98] over N_SIM datasets.
--pilot: measures ONLY the conditional:S1 half-width ratio (no coverage) for several co-trend scales, to pick design 2 so that the ratio is about 0.9-1.0 as on the real data (0.94).
Usage: python tools/m317_calibration.py [--sims 500] [--draws 1000] [--jobs 12] [--scale 1.0] [--tag design1] | --pilot"""
import argparse, json, os, sys, time
import numpy as np
import pandas as pd
from joblib import Parallel, delayed

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import huber_slope_ci as H

N_DAYS = 100
B_T, B_I, SLOPE_TIME, B0 = 0.05, 0.045, 0.30, 12.0          # planted first-stage coefficients and a planted residual time trend (mV per month)
T_TREND1, I_TREND1 = 0.18, 0.30                              # design-1 co-trend per day (C, A); design 2 scales these


def real_counts():
    dm = pd.read_csv("drive_master.csv", usecols=["date", "ens_outlier_v2"], low_memory=False)
    dm = dm[~dm["ens_outlier_v2"].fillna(False).astype(bool)]
    return dm.groupby("date").size().values


def simulate(rng, counts, scale, n_days=N_DAYS, reps=1):
    rows = []
    for d in range(n_days):
        for _ in range(reps):
            n = int(rng.choice(counts))
            u = rng.normal(0, 1.0)                                             # day random effect on the spread level
            tday = 14 + scale * T_TREND1 * d + rng.normal(0, 2.0)              # temperature co-trends with time
            iday = 85 + scale * I_TREND1 * d + rng.normal(0, 8.0)              # current co-trends with time
            Tv = tday + rng.normal(0, 3.0, n)
            Iv = np.clip(iday + rng.normal(0, 30.0, n), 20, None)
            mo = d / 30.4375
            y = B0 + B_T * Tv + B_I * Iv + SLOPE_TIME * mo + u + 0.8 * rng.standard_t(3, n)
            rows.append(pd.DataFrame({"day": d, "month": mo, "T": Tv, "I": Iv, "y": y}))
    return pd.concat(rows, ignore_index=True)


def estimand(counts, scale, seed=7, reps=60):
    big = simulate(np.random.default_rng(seed), counts, scale, reps=reps)
    adj, _ = H.first_stage_adjust(big["T"].values, big["I"].values, big["y"].values)
    return H.second_stage_slope(big["month"].values, np.round(adj, 1))


def one(sim, counts, draws, scale):
    d = simulate(np.random.default_rng(1000 + sim), counts, scale)
    adj0, _ = H.first_stage_adjust(d["T"].values, d["I"].values, d["y"].values)
    stored = np.round(adj0, 1)
    m, labels = d["month"].values, d["day"].values
    prim = H.primary_ci(m, stored, labels, n_boot=draws, seed=42)
    s1 = H.two_stage_ci(m, d["T"].values, d["I"].values, d["y"].values, labels, n_boot=draws, seed=42)
    return {"sim": sim, "est": H.second_stage_slope(m, stored), "primary": prim.get("ci95"), "primary_bad": prim["inconclusive"], "primary_hw": prim.get("half_width"),
            "S1": s1.get("ci95"), "S1_bad": s1["inconclusive"], "S1_hw": s1.get("half_width")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=500)
    ap.add_argument("--draws", type=int, default=1000)
    ap.add_argument("--jobs", type=int, default=12)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--tag", default="design1")
    ap.add_argument("--pilot", action="store_true")
    a = ap.parse_args()
    counts = real_counts()
    t0 = time.time()
    if a.pilot:
        out = {"purpose": "pilot for design 2: conditional:S1 half-width ratio only (NO coverage looked at); real-data ratio is 0.94", "n_sims": 24, "draws": 300, "scales": {}}
        for sc in (0.0, 0.1, 0.25, 0.5, 1.0):
            res = Parallel(n_jobs=a.jobs)(delayed(one)(s, counts, 300, sc) for s in range(24))
            r = [x["primary_hw"] / x["S1_hw"] for x in res if x["primary_hw"] and x["S1_hw"]]
            out["scales"][str(sc)] = {"mean_ratio_conditional_to_S1": float(np.mean(r)), "sd": float(np.std(r, ddof=1))}
            print(sc, out["scales"][str(sc)], flush=True)
        json.dump(out, open("analyses/M317_calibration_pilot.json", "w", encoding="utf-8"), indent=1)
        return
    theta = estimand(counts, a.scale)
    res = Parallel(n_jobs=a.jobs)(delayed(one)(s, counts, a.draws, a.scale) for s in range(a.sims))
    est = np.array([r["est"] for r in res])
    out = {"spec": "analyses/M317_spec.md rev 2 + Amendment 1", "design": a.tag, "n_sims": a.sims, "draws_per_interval": a.draws, "n_days": N_DAYS,
           "drives_per_day_distribution": {"n_days_real": int(len(counts)), "mean": float(counts.mean()), "max": int(counts.max())},
           "design_parameters": {"b_T": B_T, "b_I": B_I, "planted_time_slope_mv_per_month": SLOPE_TIME, "co_trend_scale": a.scale, "T_trend_per_day": a.scale * T_TREND1,
                                 "I_trend_per_day": a.scale * I_TREND1, "day_effect_sd": 1.0, "noise": "0.8 x Student t(3)"},
           "estimand_theta_mv_per_month": theta,
           "point_estimate": {"mean": float(est.mean()), "sd": float(est.std(ddof=1)), "bias": float(est.mean() - theta), "mc_se_of_mean": float(est.std(ddof=1) / np.sqrt(len(est)))}}
    for k in ("primary", "S1"):
        ok = [r for r in res if r[k] is not None and not r[k + "_bad"]]
        cov = float(np.mean([r[k][0] <= theta <= r[k][1] for r in ok])) if ok else None
        mc = float(np.sqrt(cov * (1 - cov) / len(ok))) if ok else None
        hw = [(r[k][1] - r[k][0]) / 2 for r in ok]
        out[k] = {"n_valid": len(ok), "coverage": cov, "mc_se": mc, "pass_band_0.92_0.98": bool(cov is not None and 0.92 <= cov <= 0.98), "mean_half_width": float(np.mean(hw)) if ok else None}
    out["conditional_to_S1_half_width_ratio"] = float(out["primary"]["mean_half_width"] / out["S1"]["mean_half_width"])
    sd_boot = out["S1"]["mean_half_width"] / 1.96
    out["bias_spec_criterion_within_2_bootstrap_SE"] = bool(abs(out["point_estimate"]["bias"]) <= 2 * sd_boot)
    out["bias_script_check_within_2_mc_se"] = bool(abs(out["point_estimate"]["bias"]) <= 2 * out["point_estimate"]["mc_se_of_mean"])
    out["seconds"] = round(time.time() - t0)
    json.dump(out, open("analyses/M317_calibration_%s.json" % a.tag if a.tag != "design1" else "analyses/M317_calibration.json", "w", encoding="utf-8"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
