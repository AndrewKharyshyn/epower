#!/usr/bin/env python3
"""M773 (spec analyses/M773_spec.md Rev 2): before/after look at the all-corner tyre top-up (step day, relative day 0) on the battery-side energy while electrically propelled (ev_kwh_per100km: engine-speed proxy at most 400 rpm,
moving samples, signed battery energy per engine-off kilometre, regeneration netted). Auxiliary, report-only, offline. Descriptive: season, route, load and period are confounded; not a pressure effect.

design_mde first (outcome SD, days per side); A1 primary 28-day window unweighted adjusted difference with day-clustered bootstrap (seed 42, 4000 draws), MDE, pre-registered expectation and lower-end reading rule; sensitivities (without
ev_dist_pct, with it, km-weighted, offset covariate, ev_nr, 14 and 42 day windows, puncture-days exclusion, distance floors); guarded placebo centres; pressure dose per week; drift check. Aggregates only: relative days, no dates, names or per-drive rows.
Usage: python tools/topup_before_after.py --run [--out-dir analyses] [--nb 4000]   Exit codes: 0 done, 1 master pin, 3 stop."""
import argparse, json, os, sys, time
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import payload_energy as PE
import tyre_rolling as T
import wiper_episodes as E
import mynissan_coverage as mc

SEED, NB_DEFAULT = 42, 4000
PINNED_MD5 = PE.PINNED_MD5
STEP_DAY = T.STEP_DATE                                   # 2026-07-26 (kept in the tool only; the result carries relative days)
PUNCTURE_DAYS = (T.PUNCTURE_DAY,)
PUNCTURE_SENS = ("2026-07-14", "2026-07-15", "2026-07-16")
EV_FLOOR_KM = 1.0
EXPECT_LOWER_PCT = 0.35                                   # half-MDE threshold: 0.35 % of the corpus-wide mean (the lower expectation is about 0.7 %)
EXPECT_REL_PCT = (-0.7, -5.3)
OFFSETS = (-84, -56, -42, 42, 56, 84)
CLUSTER_FLOOR_FACTOR = 2
COVS_FULL = ["ambient", "ev_speed", "inv_ev_speed", "log_ev_km", "soak3"]
COVS_REDUCED = ["ambient", "ev_speed", "inv_ev_speed"]


# ------------------------------------------------------------------ data
def load(master, seasonal, snapshots, m733_path):
    d = pd.read_csv(master, low_memory=False)
    keep = ["file", "date", "time_start", "duration_s", "drive_type", "distance_km", "ens_outlier_v2", "ev_valid", "ev_dist_km", "ev_moving_time_s", "ev_dist_pct", "ev_kwh_per100km", "ev_nr_kwh", "ev_nr_km", "I_offset_A_applied"]
    d = d[[c for c in keep if c in d.columns]].copy()
    d["day"] = d["date"].astype(str)
    d["cls"] = d["drive_type"].where(d["drive_type"].isin(PE.CLASSES), "unknown")
    sd = pd.read_csv(seasonal, usecols=["file", "thermal_regime", "ambient_time_mean_c"], low_memory=False)
    d = d.merge(sd, on="file", how="left")
    d["thermal"] = d["thermal_regime"].astype(str)
    d["ambient"] = d["ambient_time_mean_c"].astype(float)
    ts = pd.to_datetime(d["date"].astype(str) + " " + d["time_start"].astype(str).str[:8])
    t0 = ts.dt.tz_localize(mc.KYIV, ambiguous="NaT", nonexistent="NaT").map(lambda x: x.timestamp() if pd.notna(x) else np.nan)
    d["t0"] = t0.values
    d["t1"] = d["t0"] + d["duration_s"].astype(float)
    d["t0"] = d["t0"].fillna(ts.astype("int64") / 1e9)
    d["t1"] = d["t1"].fillna(d["t0"] + d["duration_s"].astype(float))
    fl, _gap = E.soak_flags(d["t0"].values, d["t1"].values)
    d["soak3"] = fl[3.0]
    d["ev_speed"] = d["ev_dist_km"].astype(float) / (d["ev_moving_time_s"].astype(float) / 3600.0)
    d["inv_ev_speed"] = 1.0 / d["ev_speed"]
    d["log_ev_km"] = np.log(d["ev_dist_km"].astype(float))
    d["ev_nr_per100"] = d["ev_nr_kwh"].astype(float) / d["ev_nr_km"].astype(float) * 100.0
    sn = pd.read_csv(snapshots)
    m733 = json.load(open(m733_path, encoding="utf-8"))
    d = d.merge(sn[["file", "min_into_drive", "settled_ambient_c", "fl_kpa", "fr_kpa", "rl_kpa", "rr_kpa"]], on="file", how="left")
    d["p_cold"] = T.cold_equivalent(d, m733)
    steps = sorted(set(s["date"] for s in m733["E3_steps"]["list"] if s["date"] != T.PUNCTURE_DAY))
    return d, m733, steps


def eligible(d, ev_floor=EV_FLOOR_KM, need_valid=True):
    ok = (d["ens_outlier_v2"].astype(str).str.lower() != "true") & d["ev_kwh_per100km"].notna() & (d["ev_dist_km"].astype(float) >= ev_floor) & (d["distance_km"].astype(float) >= 2.0) & d["cls"].isin(PE.CLASSES)
    if need_valid:
        ok &= d["ev_valid"].astype(str).str.lower().eq("true")
    ok &= d[["ambient", "ev_speed", "inv_ev_speed", "log_ev_km"]].replace([np.inf, -np.inf], np.nan).notna().all(axis=1)
    return d[ok].copy()


def rel_day(day, center):
    return (pd.Timestamp(day) - pd.Timestamp(center)).days


def window(df, center, half, exclude_days=PUNCTURE_DAYS):
    """Drives within +-half days of the centre (centre day excluded; excluded days dropped); reg = 1 after, 0 before; rel = relative day."""
    d = df[~df["day"].isin(exclude_days) & (df["day"] != center)].copy()
    rel = (pd.to_datetime(d["day"]) - pd.Timestamp(center)).dt.days
    d = d[(rel.abs() <= half) & (rel != 0)].copy()
    d["rel"] = (pd.to_datetime(d["day"]) - pd.Timestamp(center)).dt.days
    d["reg"] = (d["rel"] > 0).astype(float)
    return d


# ------------------------------------------------------------------ estimation
def slope_w(df, y, covs, w=None):
    X = T.design(df, covs)
    yv = df[y].values.astype(float)
    ok = np.isfinite(X).all(1) & np.isfinite(yv)
    if w is None:
        beta, *_ = np.linalg.lstsq(X[ok], yv[ok], rcond=None)
    else:
        sw = np.sqrt(np.asarray(w, float)[ok])
        beta, *_ = np.linalg.lstsq(X[ok] * sw[:, None], yv[ok] * sw, rcond=None)
    return float(beta[1])


def boot(df, y, covs, nb, weight_col=None, seed=SEED):
    df = df.reset_index(drop=True)
    ud, inv = np.unique(df["day"].values, return_inverse=True)
    idx = [np.where(inv == i)[0] for i in range(len(ud))]
    wcol = df[weight_col].values if weight_col else None
    est = slope_w(df, y, covs, wcol)
    rng = np.random.default_rng(seed)
    out, deficient, draws = [], 0, 0
    for _ in range(nb):
        pick = rng.integers(0, len(ud), len(ud))
        sub_idx = np.concatenate([idx[p] for p in pick])
        sub = df.iloc[sub_idx]
        try:
            Xs = T.design(sub, covs)
            draws += 1
            if np.linalg.matrix_rank(Xs) < Xs.shape[1]:
                deficient += 1
            out.append(slope_w(sub, y, covs, None if wcol is None else wcol[sub_idx]))
        except np.linalg.LinAlgError:
            continue
    out = np.array(out)
    return est, [float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))], float(np.std(out, ddof=1)), {"draws": draws, "deficient": deficient}


def fit(w, y, covs, nb, weight_col=None):
    """Adjusted after-minus-before difference with the floors: at least 5 days and 20 drives per side and clusters >= 2 x parameters, else counts only."""
    nbd, nad = int(w.loc[w["reg"] == 0, "day"].nunique()), int(w.loc[w["reg"] == 1, "day"].nunique())
    nb_, na_ = int((w["reg"] == 0).sum()), int((w["reg"] == 1).sum())
    out = {"days_before": nbd, "days_after": nad, "drives_before": nb_, "drives_after": na_}
    npar = T.design(w.head(max(len(w), 1)), covs).shape[1] if len(w) else 99
    out["parameters"] = int(npar)
    out["thermal_levels_in_window"] = int(w["thermal"].nunique()) if len(w) else 0
    if min(nbd, nad) < 5 or min(nb_, na_) < 20 or (nbd + nad) < CLUSTER_FLOOR_FACTOR * npar:
        out["counts_only"] = True
        return out
    est, ci, sd, rd = boot(w, y, covs, nb, weight_col)
    mean_before = float(w.loc[w["reg"] == 0, y].mean())
    out.update({"difference_after_minus_before": est, "ci95": ci, "mde": 2.8 * sd, "mean_before": mean_before, "difference_pct_of_before_mean": 100.0 * est / mean_before if mean_before else None, "bootstrap_rank_deficient_resamples": rd})
    return out


def design_mde(w, y):
    """Outcome-blind sizing from the outcome SD and the days per side (the outcome SD is used because the adjusted residual SD cannot be known outcome-blind)."""
    sd = float(w[y].astype(float).std(ddof=1))
    nbd, nad = max(int(w.loc[w["reg"] == 0, "day"].nunique()), 1), max(int(w.loc[w["reg"] == 1, "day"].nunique()), 1)
    se = sd * np.sqrt(1.0 / nbd + 1.0 / nad)
    return {"outcome_sd": sd, "days_before": nbd, "days_after": nad, "expected_se": float(se), "expected_mde": float(2.8 * se), "note": "outcome SD and days per side; the adjusted residual SD cannot be known outcome-blind"}


def reading(mde, half_threshold):
    return "informative" if mde <= half_threshold else "not informative at this support"


def sign_note(est, ci):
    if ci[0] > 0 or ci[1] < 0:
        return "inconsistent with the expected sign, confounding suspected" if est > 0 else "interval excludes zero with the expected sign (association only; season, route, load and period confounded)"
    return "interval includes zero"


def dose_by_week(df_all, center, weeks=4):
    """Median cold-equivalent four-corner pressure per week relative to the step (aggregates only; weeks with fewer than 3 drives suppressed)."""
    d = df_all[df_all["p_cold"].notna() & ~df_all["day"].isin(PUNCTURE_DAYS)].copy()
    d["rel"] = (pd.to_datetime(d["day"]) - pd.Timestamp(center)).dt.days
    out = {}
    for k in list(range(-weeks, 0)) + list(range(1, weeks + 1)):
        lo = (k - 1) * 7 + 1 if k > 0 else k * 7
        hi = k * 7 if k > 0 else k * 7 + 6
        s = d[(d["rel"] >= lo) & (d["rel"] <= hi) & (d["rel"] != 0)]
        out["week_%+d" % k] = {"drives": int(len(s)), "median_kpa": (float(s["p_cold"].median()) if len(s) >= 3 else "suppressed (fewer than 3 drives)")}
    return out


def analyse(d, steps, nb):
    res = {}
    e = eligible(d)
    corpus_mean = float(e["ev_kwh_per100km"].mean())
    exp_low_kwh = EXPECT_LOWER_PCT / 100.0 * corpus_mean
    res["expectation"] = {"relative_pct": list(EXPECT_REL_PCT), "corpus_wide_mean_kwh_per100km": corpus_mean, "corpus_mean_note": "mean over the eligible drives of the whole master (445 drives); the spec text quoted 14.2 for all 645 drives with the channel", "half_mde_threshold_kwh_per100km": exp_low_kwh,
                          "assumed": "Crr 0.010, mass 1900 kg, eta 0.75; pressure exponent -0.2 to -0.5; pressure rise 10 to 16 %; rolling share of the outcome 0.35 to 0.55; pass-through 1.0 to 1.2",
                          "expected_sign": "negative", "near_certain": "not informative at this support"}
    prot = T.protected_dates(steps)
    center = STEP_DAY
    w28 = window(e, center, 28)
    res["design_mde"] = design_mde(w28, "ev_kwh_per100km")
    # primary and sensitivities
    prim = fit(w28, "ev_kwh_per100km", COVS_FULL, nb)
    if not prim.get("counts_only"):
        prim["reading"] = reading(prim["mde"], exp_low_kwh)
        prim["sign_note"] = sign_note(prim["difference_after_minus_before"], prim["ci95"])
    res["A1_primary_28d_unweighted"] = prim
    sens = {}
    sens["with_ev_dist_pct"] = fit(w28.dropna(subset=["ev_dist_pct"]), "ev_kwh_per100km", COVS_FULL + ["ev_dist_pct"], max(nb // 2, 500))
    w28["w_km"] = w28["ev_dist_km"].astype(float)
    sens["km_weighted"] = fit(w28, "ev_kwh_per100km", COVS_FULL, max(nb // 2, 500), weight_col="w_km")
    if "I_offset_A_applied" in w28.columns:
        sens["offset_covariate"] = fit(w28.dropna(subset=["I_offset_A_applied"]).assign(off=lambda x: x["I_offset_A_applied"].astype(float)), "ev_kwh_per100km", COVS_FULL + ["off"], max(nb // 2, 500))
    wn = w28[w28["ev_nr_per100"].notna() & np.isfinite(w28["ev_nr_per100"])]
    sens["ev_nr_regen_poor_subset"] = fit(wn, "ev_nr_per100", COVS_FULL, max(nb // 2, 500))
    ww = w28.copy()
    lo_, hi_ = np.percentile(ww["ev_kwh_per100km"].astype(float), [2.5, 97.5])
    ww["ev_kwh_per100km"] = ww["ev_kwh_per100km"].astype(float).clip(lo_, hi_)
    sens["winsorised_outcome_2p5_97p5_within_window"] = fit(ww, "ev_kwh_per100km", COVS_FULL, max(nb // 2, 500))
    sens["exclude_puncture_days_14_to_16"] = fit(window(e, center, 28, exclude_days=PUNCTURE_SENS), "ev_kwh_per100km", COVS_FULL, max(nb // 2, 500))
    for fl in (0.5, 2.0):
        sens["ev_distance_floor_%g_km" % fl] = fit(window(eligible(d, ev_floor=fl), center, 28), "ev_kwh_per100km", COVS_FULL, max(nb // 2, 500))
    sens["window_14d_reduced_covariates"] = fit(window(e, center, 14), "ev_kwh_per100km", COVS_REDUCED, max(nb // 2, 500))
    sens["window_42d"] = fit(window(e, center, 42), "ev_kwh_per100km", COVS_FULL, max(nb // 2, 500))
    res["A1_sensitivities_nothing_picked"] = sens
    # A2 exploratory dose-response
    ws = w28[w28["p_cold"].notna()].copy()
    if len(ws) >= 40 and ws["day"].nunique() >= 15:
        med = float(ws["p_cold"].median())
        ws["reg"] = (ws["p_cold"] - med) / (0.1 * med)
        est, ci, sd_, rd = boot(ws, "ev_kwh_per100km", COVS_FULL, max(nb // 2, 500))
        res["A2_exploratory_pressure_slope"] = {"drives": int(len(ws)), "days": int(ws["day"].nunique()), "slope_kwh_per100km_per10pct": est, "ci95": ci, "mde": 2.8 * sd_, "label": "exploratory: the within-window pressure is almost collinear with the step; bootstrap rank-deficient resamples %s" % json.dumps(rd)}
    else:
        res["A2_exploratory_pressure_slope"] = {"counts_only": True, "drives": int(len(ws)), "days": int(ws["day"].nunique())}
    res["pressure_dose_per_week"] = dose_by_week(d, center)
    # A3 what else moved
    a3 = {}
    for y in ("ev_dist_pct", "ev_speed"):
        wy = w28.dropna(subset=[y])
        a3[y] = {"mean_before": float(wy.loc[wy["reg"] == 0, y].mean()), "mean_after": float(wy.loc[wy["reg"] == 1, y].mean()), "drives_before": int((wy["reg"] == 0).sum()), "drives_after": int((wy["reg"] == 1).sum())}
    res["A3_what_else_moved"] = a3
    # placebo windows, guarded
    pl = {}
    for half in (28, 14):
        for off in OFFSETS:
            c = (pd.Timestamp(center) + pd.Timedelta(days=off)).strftime("%Y-%m-%d")
            key = "half%d_offset%+d" % (half, off)
            if not T.window_ok(c, half, prot):
                pl[key] = {"skipped": "window contains a protected date"}
                continue
            wp = window(e, c, half, exclude_days=PUNCTURE_DAYS)
            r = fit(wp, "ev_kwh_per100km", COVS_FULL if half == 28 else COVS_REDUCED, max(nb // 4, 300))
            pl[key] = {k: v for k, v in r.items() if k in ("counts_only", "difference_after_minus_before", "ci95", "mde", "days_before", "days_after", "drives_before", "drives_after")}
    res["placebo_windows_guarded"] = {"note": "the placebo differences are a scale of confounding (season, route, load, period), not a calibration", "windows": pl}
    # B drift check
    wb = w28[w28["reg"] == 0]
    if wb["day"].nunique() >= 5 and len(wb) >= 20:
        res["B_before_window_drift_per_day"] = float(np.polyfit(wb["rel"].astype(float).values, wb["ev_kwh_per100km"].astype(float).values, 1)[0])
    res["C_integrity"] = {"eligible_drives": int(len(e)), "channel_drives_in_master": int(d["ev_kwh_per100km"].notna().sum()), "ens_outlier_v2_missing_treated_as_clean": int(d["ens_outlier_v2"].isna().sum()),
                          "window_28d_drives": int(len(w28)), "window_28d_days": int(w28["day"].nunique()), "long_soak_first_drive_unknown_dropped": int(d["soak3"].isna().sum())}
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--out-dir", default=os.path.join(HERE, "..", "analyses"))
    ap.add_argument("--master", default=os.path.join(HERE, "..", "drive_master.csv"))
    ap.add_argument("--seasonal", default=os.path.join(HERE, "..", "seasonal_drive_master.csv"))
    ap.add_argument("--snapshots", default=os.path.join(HERE, "..", "analyses", "M733_tyre_snapshots.csv"))
    ap.add_argument("--m733", default=os.path.join(HERE, "..", "analyses", "M733_tyre_pressure.json"))
    ap.add_argument("--nb", type=int, default=NB_DEFAULT)
    a = ap.parse_args(argv)
    if not a.run:
        print(__doc__)
        return 0
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = time.time()
    try:
        if PE.md5(a.master) != PINNED_MD5:
            print("topup_before_after: master pin failed")
            return 1
        import odometer_jump_audit as J
        d, m733, steps = load(a.master, a.seasonal, a.snapshots, a.m733)
        res = {"milestone": "M773", "spec": "analyses/M773_spec.md Rev 2", "masterMd5": PINNED_MD5, "toolSha256": PE.sha256(os.path.abspath(__file__)), "seed": SEED, "nBoot": a.nb,
               "inputs": {"m733_snapshots_sha256": PE.sha256(a.snapshots), "m733_result_sha256": PE.sha256(a.m733)}, "scaleDecision": T.OWNER_DECISION,
               "step": "the all-corner top-up (relative day 0); windows are given in days around it"}
        res.update(analyse(d, steps, a.nb))
        res["limits"] = ["a before/after look at one top-up: season, route, load, HVAC and period are confounded; not a pressure effect; not rolling resistance measured",
                         "ev_kwh_per100km is the battery-side energy while electrically propelled (engine-speed proxy at most 400 rpm, moving samples, regeneration netted, raw current basis); time-proportional terms scale as 1 / v_ev; air conditioning at EV speeds dwarfs the expected change; EV runs are selected by the SoC controller (biases toward the null)",
                         "pressure scale accepted by the owner from manual gauge control (24 Nov 2026), not independently re-measured",
                         "a null is not 'no pressure effect' (no equivalence test); the placebo windows are a scale of confounding, not a calibration; nothing is picked among the sensitivities",
                         "not an article figure"]
        res["seconds"] = round(time.time() - t0, 1)
        bad = J.scan_privacy(res)
        if bad:
            raise T.Stop("privacy scan failed: %s" % bad[:3])
        if PE.md5(a.master) != PINNED_MD5:
            raise T.Stop("drive_master.csv changed during the run")
        os.makedirs(a.out_dir, exist_ok=True)
        with open(os.path.join(a.out_dir, "M773_topup_before_after.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(res, f, indent=1, default=lambda o: None if o != o else str(o))
        p = res["A1_primary_28d_unweighted"]
        print("topup_before_after: A1 28d %s" % (("difference %.3f kWh/100km [%.3f, %.3f], MDE %.3f, %s" % (p["difference_after_minus_before"], p["ci95"][0], p["ci95"][1], p["mde"], p["reading"])) if not p.get("counts_only") else "counts only"))
        return 0
    except T.Stop as e:
        print("topup_before_after: STOP (%s)" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
