#!/usr/bin/env python3
"""M770 (spec analyses/M770_spec.md Rev 2): tyre pressure and rolling resistance. Auxiliary, report-only, offline.

A1 (confirmatory): slope of fuel L/100 km (logged / app-calculated) on the COLD-EQUIVALENT mean four-corner tyre pressure per +10 % of its median, covariate-adjusted, calendar-day cluster bootstrap (seed 42, 4000 draws),
MDE, pre-registered expectation -0.3 % to -2.3 % per +10 % (lower-magnitude reading rule). Sensitivities: raw snapshot, per +10 kPa, epoch fixed effects, distance floors. A2 other outcomes (exploratory). B1: before/after look at the
26 Jul top-up (descriptive; puncture window excluded; guarded placebo windows). The coast-down question is NOT built here (spec 7.6). Pressure scale accepted by the owner from manual gauge control, not re-measured.
Reuses tools/payload_energy.py (day bootstrap, outcome-blind sizing, displaced helpers). Aggregates only.
Usage: python tools/tyre_rolling.py --run [--out-dir analyses] [--nb 4000]   Exit codes: 0 done, 1 master pin, 3 stop."""
import argparse, json, os, sys, time
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import payload_energy as PE

SEED, NB_DEFAULT = 42, 4000
PINNED_MD5 = PE.PINNED_MD5
STEP_DATE = "2026-07-26"
PUNCTURE_DAY = "2026-07-14"
OWNER_DECISION = {"quote": "You may trust the data since it is plausible and according to my manual control. So the pressure is assumed to be correct.", "date": "2026-11-24", "source": "chat", "independentlyVerified": False}
EXPECT_PCT = (-0.3, -2.3)                               # per +10 % pressure, % of the mean fuel rate (lower magnitude first)
COVS = ["ambient", "logdist", "speed_mean_moving", "v2", "dsoc100", "first_of_day", "min_into_drive"]
OUTCOMES_A2 = ("traction_gross_kWh_100", "generator_kWh_100", "batt_to_traction_kWh_100", "regen_to_batt_kWh_100")


class Stop(Exception):
    pass


# ------------------------------------------------------------------ pressure
def cold_equivalent(df, m733):
    """Cold-equivalent corner pressures (kPa): snapshot minus the M733 E2 temperature response times (settled ambient - 15 C) minus the minutes-into-drive coefficient times the minutes; mean of the four corners."""
    f_t, r_t = m733["E2_temperature_response"]["front"]["slope_kpa_per_c"], m733["E2_temperature_response"]["rear"]["slope_kpa_per_c"]
    f_m, r_m = m733["E2_temperature_response"]["front"]["minutes_into_drive_coef_kpa_per_min"], m733["E2_temperature_response"]["rear"]["minutes_into_drive_coef_kpa_per_min"]
    dT = df["settled_ambient_c"].astype(float) - 15.0
    m = df["min_into_drive"].astype(float)
    cols = {}
    for k, (t, mm) in {"fl_kpa": (f_t, f_m), "fr_kpa": (f_t, f_m), "rl_kpa": (r_t, r_m), "rr_kpa": (r_t, r_m)}.items():
        cols[k] = df[k].astype(float) - t * dT - mm * m
    return pd.concat(cols, axis=1).mean(axis=1)


def epochs(dates, step_dates):
    """Epoch id of each date: the number of pressure-step dates on or before it (the puncture day is excluded elsewhere)."""
    sd = sorted(set(step_dates))
    return np.array([sum(1 for s in sd if d >= s) for d in dates])


# ------------------------------------------------------------------ estimation with epoch fixed effects
def design(df, covs, cat=("cls", "thermal"), extra_cat=()):
    cols = [np.ones(len(df)), df["reg"].values.astype(float)]
    for c in tuple(cat) + tuple(extra_cat):
        if c in df.columns:
            for l in sorted(set(df[c].dropna().astype(str)))[1:]:
                cols.append((df[c].astype(str) == l).values.astype(float))
    for c in covs:
        cols.append(df[c].values.astype(float))
    return np.column_stack(cols)


def slope(df, y, covs, extra_cat=()):
    X = design(df, covs, extra_cat=extra_cat)
    yv = df[y].values.astype(float)
    ok = np.isfinite(X).all(1) & np.isfinite(yv)
    beta, *_ = np.linalg.lstsq(X[ok], yv[ok], rcond=None)
    return float(beta[1])


def boot(df, y, covs, nb, extra_cat=(), seed=SEED):
    df = df.reset_index(drop=True)
    ud, inv = np.unique(df["day"].values, return_inverse=True)
    idx = [np.where(inv == i)[0] for i in range(len(ud))]
    est = slope(df, y, covs, extra_cat)
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(nb):
        pick = rng.integers(0, len(ud), len(ud))
        try:
            out.append(slope(df.iloc[np.concatenate([idx[p] for p in pick])], y, covs, extra_cat))
        except np.linalg.LinAlgError:
            continue
    out = np.array(out)
    return est, [float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))], float(np.std(out, ddof=1))


def residual_regressor_sd(df, covs):
    """SD of the regressor after the covariates and the class and thermal indicators (the design sizing uses this, not the raw SD)."""
    d = df.copy()
    d["_y"] = d["reg"]
    d["reg"] = 0.0
    X = design(d, covs)[:, [0] + list(range(2, design(d, covs).shape[1]))]
    y = d["_y"].values.astype(float)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return float(np.std(y - X @ beta, ddof=X.shape[1]))


def design_sizing(df, y, covs):
    """Outcome-blind sizing from the residual regressor SD, the intraclass correlation by day, the effective days and the between-epoch variance share."""
    x = df["reg"].values.astype(float)
    ud, inv = np.unique(df["day"].values, return_inverse=True)
    k, n = len(ud), len(x)
    means = np.array([x[inv == i].mean() for i in range(k)])
    sizes = np.array([(inv == i).sum() for i in range(k)])
    msb = float(np.sum(sizes * (means - x.mean()) ** 2) / max(k - 1, 1))
    msw = float(np.sum([((x[inv == i] - means[i]) ** 2).sum() for i in range(k)]) / max(n - k, 1))
    n0 = (n - float(np.sum(sizes ** 2)) / n) / max(k - 1, 1)
    den = msb + (n0 - 1) * msw
    icc = max(0.0, (msb - msw) / den) if den > 0 else 0.0
    deff = 1 + (n / k - 1) * icc
    n_eff = n / deff
    sd_res = residual_regressor_sd(df, covs)
    sd_y = float(np.nanstd(df[y].values.astype(float), ddof=1))
    se = sd_y / (sd_res * np.sqrt(max(n_eff, 1.0)))
    ep = df["epoch"].values
    tot = float(np.var(x, ddof=1))
    between = float(np.var([x[ep == e].mean() for e in np.unique(ep)], ddof=1) * 1.0) if len(np.unique(ep)) > 1 else 0.0
    return {"drives": int(n), "days": int(k), "regressor_sd_raw_per10pct": float(np.std(x, ddof=1)), "regressor_sd_residual_per10pct": sd_res, "regressor_icc_by_day": float(icc), "design_effect": float(deff), "n_eff": float(n_eff),
            "between_epoch_variance_share": float(between / tot) if tot > 0 else None, "outcome_sd": sd_y, "expected_se_per10pct": float(se), "expected_mde_per10pct": float(2.8 * se),
            "note": "residual regressor SD after the covariates; the outcome SD (not the adjusted residual SD) because the latter cannot be known outcome-blind"}


def reading(mde, lower_mag):
    """Informative only if the MDE is at most half of the LOWER magnitude of the pre-registered expectation."""
    return "informative" if mde <= 0.5 * lower_mag else "not informative at this support"


def sign_note(est, ci, expected_negative=True):
    if ci[0] > 0 or ci[1] < 0:
        wrong = (est > 0) if expected_negative else (est < 0)
        return "inconsistent with the expected sign, confounding suspected" if wrong else "interval excludes zero with the expected sign (association only; confounding by season, route and HVAC not excluded)"
    return "interval includes zero"


# ------------------------------------------------------------------ B1 before / after look
def protected_dates(step_dates):
    return sorted(set(list(step_dates) + [PUNCTURE_DAY]))


def window_ok(center, half, protected):
    """A placebo window [center-half, center+half] must not contain any protected date."""
    c = pd.Timestamp(center)
    lo, hi = c - pd.Timedelta(days=half), c + pd.Timedelta(days=half)
    return all(not (lo <= pd.Timestamp(p) <= hi) for p in protected)


def before_after(df, center, half, y, covs, nb, exclude_days=(PUNCTURE_DAY,)):
    """Adjusted difference of y (after minus before) in the window around center; counts only below 5 days per side. The regressor column is replaced by the after indicator."""
    c = pd.Timestamp(center)
    d = df[~df["day"].isin(exclude_days)].copy()
    dt = pd.to_datetime(d["day"])
    inw = d[(dt >= c - pd.Timedelta(days=half)) & (dt <= c + pd.Timedelta(days=half))].copy()
    inw["reg"] = (pd.to_datetime(inw["day"]) >= c).astype(float)
    nb_, na_ = int(inw.loc[inw["reg"] == 0, "day"].nunique()), int(inw.loc[inw["reg"] == 1, "day"].nunique())
    out = {"half_window_days": half, "days_before": nb_, "days_after": na_, "drives_before": int((inw["reg"] == 0).sum()), "drives_after": int((inw["reg"] == 1).sum())}
    if min(nb_, na_) < 5 or len(inw) < 20:
        out["counts_only"] = True
        return out
    covs2 = [c_ for c_ in covs if c_ in inw.columns]
    est, ci, sd = boot(inw, y, covs2, max(nb // 2, 500))
    out.update({"difference_after_minus_before": est, "ci95": ci, "mde": 2.8 * sd, "label": "before/after look, season, route and period confounded, not a pressure effect",
                "mean_cold_equivalent_pressure_kpa": {"before": float(inw.loc[inw["reg"] == 0, "p_cold"].mean()), "after": float(inw.loc[inw["reg"] == 1, "p_cold"].mean())}})
    return out


# ------------------------------------------------------------------ data
def load(master, fuel, payload, seasonal, snapshots, m733_path):
    d = PE.load_frame(master, fuel, payload, seasonal)
    sn = pd.read_csv(snapshots)
    m733 = json.load(open(m733_path, encoding="utf-8"))
    d = d.merge(sn[["file", "min_into_drive", "settled_ambient_c", "fl_kpa", "fr_kpa", "rl_kpa", "rr_kpa"]], on="file", how="left")
    d["p_cold"] = cold_equivalent(d, m733)
    d["p_snap"] = d[["fl_kpa", "fr_kpa", "rl_kpa", "rr_kpa"]].astype(float).mean(axis=1)
    steps = sorted(set(s["date"] for s in m733["E3_steps"]["list"] if s["date"] != PUNCTURE_DAY))
    d["epoch"] = epochs(d["day"].values, steps)
    return d, m733, steps


def eligible(d, dist_min=PE.DIST_MIN):
    ok = (d["ens_outlier_v2"].astype(str).str.lower() != "true") & d["fuel_L_per_100km"].notna() & d["p_cold"].notna() & (d["distance_km"].astype(float) >= dist_min) & (d["day"] != PUNCTURE_DAY) & d["cls"].isin(PE.CLASSES)
    ok &= d[["ambient", "v2", "dsoc100", "logdist", "min_into_drive"]].notna().all(axis=1)
    return d[ok].copy()


def set_regressor(e, kind="cold_pct"):
    e = e.copy()
    if kind == "cold_pct":
        med = float(e["p_cold"].median())
        e["reg"] = (e["p_cold"] - med) / (0.1 * med)
    elif kind == "snap_pct":
        med = float(e["p_snap"].median())
        e["reg"] = (e["p_snap"] - med) / (0.1 * med)
    elif kind == "cold_kpa":
        e["reg"] = (e["p_cold"] - float(e["p_cold"].median())) / 10.0
    return e


def analyse(d, m733, steps, nb):
    res = {"scaleDecision": OWNER_DECISION, "scale_wording": "scale accepted by the owner from manual gauge control (2026-11-24), not independently re-measured here"}
    e = set_regressor(eligible(d), "cold_pct")
    mean_fuel = float(e["fuel_L_per_100km"].mean())
    exp_low, exp_high = abs(EXPECT_PCT[0]) / 100.0 * mean_fuel, abs(EXPECT_PCT[1]) / 100.0 * mean_fuel
    res["expectation_fuel_per10pct"] = {"relative_pct": list(EXPECT_PCT), "mean_fuel_L_per_100km_eligible": mean_fuel, "lower_magnitude_L_per_100km": exp_low, "upper_magnitude_L_per_100km": exp_high,
                                       "expected_sign": {"fuel": "negative", "traction_gross": "negative", "regen_to_batt": "zero or slightly positive"}, "assumed": "exponent -0.2 to -0.5, rolling share of fuel-equivalent wheel energy 0.25 to 0.45, hybrid pass-through 0.6 to 1.0"}
    res["design_mde"] = design_sizing(e, "fuel_L_per_100km", COVS)
    res["observed_pressure"] = {"median_cold_equivalent_kpa": float(e["p_cold"].median()), "iqr_pct_of_median": [float(np.percentile(e["reg"], 25) * 10), float(np.percentile(e["reg"], 75) * 10)],
                                "note": "the per +10 % scale extrapolates beyond the observed interquartile range except across the 26 Jul step"}
    est, ci, sd = boot(e, "fuel_L_per_100km", COVS, nb)
    mde = 2.8 * sd
    a1 = {"outcome": "fuel_L_per_100km (logged / app-calculated)", "regressor": "cold-equivalent mean four-corner pressure per +10 % of its median", "drives": int(len(e)), "days": int(e["day"].nunique()),
          "slope_L_per_100km_per10pct": est, "ci95": ci, "bootstrap_sd": sd, "mde": mde, "reading": reading(mde, exp_low), "sign_note": sign_note(est, ci),
          "covariates": ["drive class", "thermal class"] + COVS}
    ep_est = slope(e, "fuel_L_per_100km", COVS, extra_cat=("epoch",)) if e["epoch"].nunique() > 1 else None
    a1["epoch_fixed_effect_slope"] = ep_est
    sn = set_regressor(e, "snap_pct")
    a1["sensitivity_raw_snapshot_per10pct"] = slope(sn, "fuel_L_per_100km", COVS)
    kp = set_regressor(e, "cold_kpa")
    a1["sensitivity_per10kpa"] = slope(kp, "fuel_L_per_100km", COVS)
    a1["sensitivities_distance_floor"] = {}
    for dm_ in (2.0, 10.0):
        es = set_regressor(eligible(d, dm_), "cold_pct")
        a1["sensitivities_distance_floor"]["%g_km" % dm_] = {"drives": int(len(es)), "days": int(es["day"].nunique()), "slope_L_per_100km_per10pct": slope(es, "fuel_L_per_100km", COVS)}
    res["A1"] = a1
    a2 = {}
    for y in OUTCOMES_A2:
        ey = e[e[y].notna()]
        if len(ey) < 60 or ey["day"].nunique() < 20:
            a2[y] = {"counts_only": True, "drives": int(len(ey)), "days": int(ey["day"].nunique())}
            continue
        est2, ci2, sd2 = boot(ey, y, COVS, max(nb // 2, 500))
        a2[y] = {"drives": int(len(ey)), "days": int(ey["day"].nunique()), "mean": float(ey[y].mean()), "slope_per10pct": est2, "ci95": ci2, "mde": 2.8 * sd2,
                 "label": "from logged current" if y == "regen_to_batt_kWh_100" else "model-derived (fuel flow x BSFC plus battery power minus auxiliaries)", "sign_note": sign_note(est2, ci2, expected_negative=(y != "regen_to_batt_kWh_100"))}
    res["A2_exploratory"] = a2
    # B1
    allf = eligible(d)
    protected = protected_dates(steps)
    b1 = {"step": "26 Jul 2026 all-corner top-up (relative day 0)", "puncture_window_excluded": True, "windows": {}, "placebo": {}}
    # outcome-blind sizing of the difference
    sd_y = float(allf["fuel_L_per_100km"].std(ddof=1))
    for half in (14, 28):
        b1["windows"]["%d" % half] = before_after(allf.assign(reg=0.0), STEP_DATE, half, "fuel_L_per_100km", [c for c in COVS if c != "min_into_drive"] + ["min_into_drive"], nb)
        w = b1["windows"]["%d" % half]
        if not w.get("counts_only"):
            w["design_mde_difference"] = float(2.8 * sd_y * np.sqrt(1.0 / max(w["drives_before"], 1) + 1.0 / max(w["drives_after"], 1)))
        pl = {}
        for off in (-84, -56, -42, 42, 56, 84):
            c = (pd.Timestamp(STEP_DATE) + pd.Timedelta(days=off)).strftime("%Y-%m-%d")
            if not window_ok(c, half, protected):
                pl["%+d" % off] = {"skipped": "window contains a protected date"}
                continue
            o = before_after(allf.assign(reg=0.0), c, half, "fuel_L_per_100km", COVS, nb)
            pl["%+d" % off] = {k: v for k, v in o.items() if k not in ("mean_cold_equivalent_pressure_kpa",)}
        b1["placebo"]["%d" % half] = pl
    pre = allf[(pd.to_datetime(allf["day"]) < pd.Timestamp(STEP_DATE)) & (pd.to_datetime(allf["day"]) >= pd.Timestamp(STEP_DATE) - pd.Timedelta(days=28))]
    if pre["day"].nunique() >= 5 and len(pre) >= 20:
        t = (pd.to_datetime(pre["day"]) - pd.Timestamp(STEP_DATE)).dt.days.astype(float)
        b1["before_window_stability_slope_per_day"] = float(np.polyfit(t.values, pre["fuel_L_per_100km"].astype(float).values, 1)[0])
    res["B1_before_after_look"] = b1
    # C
    res["C_integrity"] = {"snapshot_drives": int(d["p_cold"].notna().sum()), "eligible_fuel_basis": int(len(e)), "steps_in_epochs": len(steps), "epochs": int(e["epoch"].nunique()),
                          "min_into_drive_quartiles": [float(x) for x in np.percentile(e["min_into_drive"].astype(float), [25, 50, 75])], "q_c_coastdown": "not built (spec 7.6)"}
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--out-dir", default=os.path.join(HERE, "..", "analyses"))
    ap.add_argument("--master", default=os.path.join(HERE, "..", "drive_master.csv"))
    ap.add_argument("--fuel", default=os.path.join(HERE, "..", "fuel_recon_master.csv"))
    ap.add_argument("--payload", default=os.path.join(HERE, "..", "analyses", "M753_drive_payload.csv"))
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
            print("tyre_rolling: master pin failed")
            return 1
        import odometer_jump_audit as J
        d, m733, steps = load(a.master, a.fuel, a.payload, a.seasonal, a.snapshots, a.m733)
        res = {"milestone": "M770", "spec": "analyses/M770_spec.md Rev 2", "masterMd5": PINNED_MD5, "toolSha256": PE.sha256(os.path.abspath(__file__)), "seed": SEED, "nBoot": a.nb,
               "inputs": {"fuel_recon_master_sha256": PE.sha256(a.fuel), "m733_result_sha256": PE.sha256(a.m733), "m733_snapshots_sha256": PE.sha256(a.snapshots)}}
        res.update(analyse(d, m733, steps, a.nb))
        res["limits"] = ["pressure is the cloud tyre-pressure channel, scale accepted by the owner from manual gauge control (2026-11-24), not independently re-measured; the cold-equivalent level uses the M733 E2 temperature response estimated on the same snapshots",
                         "association, not an effect of pressure: season, route, HVAC and period move with pressure; a settled snapshot is not the pressure during every drive; proxy error attenuates the slope",
                         "a null is not 'no pressure effect' (no equivalence test); the reading rule uses the lower magnitude of the pre-registered bracket",
                         "gross traction, generator and battery-to-traction energy are model-derived; regeneration-to-battery energy is from logged current; fuel is logged / app-calculated",
                         "B1 is a before/after look at one top-up: season, route and period confounded; not a pressure effect; the coast-down question is not built here",
                         "not an article figure"]
        res["seconds"] = round(time.time() - t0, 1)
        bad = J.scan_privacy(res)
        if bad:
            raise Stop("privacy scan failed: %s" % bad[:3])
        if PE.md5(a.master) != PINNED_MD5:
            raise Stop("drive_master.csv changed during the run")
        os.makedirs(a.out_dir, exist_ok=True)
        with open(os.path.join(a.out_dir, "M770_tyre_rolling.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(res, f, indent=1, default=lambda o: None if o != o else str(o))
        print("tyre_rolling: A1 slope %.4f L/100km per +10 %% [%.4f, %.4f], MDE %.4f, %s" % (res["A1"]["slope_L_per_100km_per10pct"], res["A1"]["ci95"][0], res["A1"]["ci95"][1], res["A1"]["mde"], res["A1"]["reading"]))
        return 0
    except Stop as e:
        print("tyre_rolling: STOP (%s)" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
