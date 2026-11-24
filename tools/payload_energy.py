#!/usr/bin/env python3
"""M769 (spec analyses/M769_spec.md Rev 2): occupant payload (latched seatbelts, owner-estimated seat weights) and the fuel, battery-charge and traction-energy figures. Auxiliary, report-only, offline.

A1 (confirmatory): slope of fuel L/100 km (logged / app-calculated) on estimated occupant payload per 100 kg, covariate-adjusted, calendar-day cluster bootstrap (seed 42, 4000 draws), minimum detectable effect, pre-registered
elasticity bracket 0.2 to 0.6 (reading rule on the LOWER end), displaced-day placebo. A2 other outcomes and shares (exploratory), A3 within class (exploratory). B1: kinematic reference (kinetic-energy throughput and assumed rolling work
per kg), never a reconstruction rescale. C integrity. design_mde is written BEFORE any estimate. Aggregates only: no per-drive rows, dates or coordinates.
Usage: python tools/payload_energy.py --run [--raw-dir DIR] [--out-dir analyses] [--nb 4000]   Exit codes: 0 done, 1 master pin, 3 stop."""
import argparse, hashlib, json, os, sys, time
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
SEED, NB_DEFAULT = 42, 4000
PINNED_MD5 = "d514d6009d6d9a0a168ad4fb09b9bb98"
MEAN_MASS = 1900.0
ELASTICITY = (0.2, 0.6)                                 # pre-registered bracket (Director, M769 review of Rev 1)
C_RR = (0.008, 0.010, 0.012)                            # ASSUMED rolling coefficients (no road-load data exist)
DIST_MIN = 5.0
G_ACC = 9.80665
CLASSES = ("urban", "mixed", "mixed_highway", "highway")
OUTCOMES_A2 = ("generator_kWh_100", "traction_gross_kWh_100", "batt_to_traction_kWh_100", "regen_to_batt_kWh_100", "gen_to_batt_kWh_100", "gen_to_traction_kWh_100")


class Stop(Exception):
    pass


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def md5(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


# ------------------------------------------------------------------ statistics
def design_matrix(df, covs, cat=("cls", "thermal")):
    cols = [np.ones(len(df)), df["payload100"].values.astype(float)]
    names = ["const", "payload100"]
    for c in cat:
        if c in df.columns:
            lv = sorted(set(df[c].dropna().astype(str)))[1:]
            for l in lv:
                cols.append((df[c].astype(str) == l).values.astype(float))
                names.append("%s=%s" % (c, l))
    for c in covs:
        cols.append(df[c].values.astype(float))
        names.append(c)
    return np.column_stack(cols), names


def ols_slope(df, y, covs):
    X, _ = design_matrix(df, covs)
    yv = df[y].values.astype(float)
    ok = np.isfinite(X).all(1) & np.isfinite(yv)
    beta, *_ = np.linalg.lstsq(X[ok], yv[ok], rcond=None)
    return float(beta[1])


def day_boot(df, y, covs, nb, seed=SEED):
    """Calendar-day cluster bootstrap of the adjusted slope: (estimate, ci95, sd)."""
    df = df.reset_index(drop=True)
    days = df["day"].values
    ud, inv = np.unique(days, return_inverse=True)
    idx_by_day = [np.where(inv == i)[0] for i in range(len(ud))]
    est = ols_slope(df, y, covs)
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(nb):
        pick = rng.integers(0, len(ud), len(ud))
        idx = np.concatenate([idx_by_day[p] for p in pick])
        try:
            out.append(ols_slope(df.iloc[idx], y, covs))
        except np.linalg.LinAlgError:
            continue
    out = np.array(out)
    return est, [float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))], float(np.std(out, ddof=1))


def design_mde(df, y="fuel_L_per_100km", nb_unused=None):
    """Outcome-blind sizing: payload SD, intraclass correlation by day, effective number of days and the expected MDE of the slope per 100 kg.
    The residual SD is the drive-level SD of the outcome itself (the covariate-adjusted SD cannot be known outcome-blind; stated)."""
    x = df["payload100"].values.astype(float)
    g = df["day"].values
    n = len(x)
    ud, inv = np.unique(g, return_inverse=True)
    k = len(ud)
    means = np.array([x[inv == i].mean() for i in range(k)])
    sizes = np.array([(inv == i).sum() for i in range(k)])
    msb = float(np.sum(sizes * (means - x.mean()) ** 2) / max(k - 1, 1))
    msw = float(np.sum([((x[inv == i] - means[i]) ** 2).sum() for i in range(k)]) / max(n - k, 1))
    n0 = (n - float(np.sum(sizes ** 2)) / n) / max(k - 1, 1)
    icc = max(0.0, (msb - msw) / (msb + (n0 - 1) * msw)) if (msb + (n0 - 1) * msw) > 0 else 0.0
    m_bar = n / k
    deff = 1 + (m_bar - 1) * icc
    n_eff = n / deff
    sd_x = float(np.std(x, ddof=1))
    sd_y = float(np.nanstd(df[y].values.astype(float), ddof=1))
    se = sd_y / (sd_x * np.sqrt(max(n_eff, 1.0)))
    return {"drives": int(n), "days": int(k), "payload_sd_per100kg": sd_x, "payload_icc_by_day": float(icc), "design_effect": float(deff), "n_eff": float(n_eff), "outcome_sd": sd_y,
            "expected_se_per100kg": float(se), "expected_mde_per100kg": float(2.8 * se), "note": "outcome SD, not the adjusted residual SD, because the latter cannot be known outcome-blind"}


def expectation_per100kg(mean_outcome):
    """Pre-registered expectation for fuel: elasticity 0.2 to 0.6 times the relative mass change (100 kg of 1900 kg), in outcome units per 100 kg."""
    rel = 100.0 / MEAN_MASS
    return {"low": ELASTICITY[0] * rel * mean_outcome, "high": ELASTICITY[1] * rel * mean_outcome, "relative_low_pct": 100 * ELASTICITY[0] * rel, "relative_high_pct": 100 * ELASTICITY[1] * rel}


def reading(mde, exp_low):
    """Pre-registered reading rule: informative only if the MDE is at most half the LOWER end of the expectation."""
    return "informative" if mde <= 0.5 * exp_low else "not informative at this support"


def displaced_payload(df, rng):
    """Displaced-day placebo: each drive gets the payload of another drive from a DIFFERENT day in the same class, thermal class and month, distance within 25 %. Drives without a donor are dropped."""
    d = df.reset_index(drop=True)
    pay = np.full(len(d), np.nan)
    key = d["cls"].astype(str) + "|" + d["thermal"].astype(str) + "|" + d["month"].astype(str)
    for i in range(len(d)):
        cand = np.where((key.values == key.values[i]) & (d["day"].values != d["day"].values[i]) & (np.abs(d["distance_km"].values / d["distance_km"].values[i] - 1.0) <= 0.25))[0]
        if len(cand):
            pay[i] = d["payload100"].values[rng.choice(cand)]
    out = d.copy()
    out["payload100"] = pay
    return out[np.isfinite(pay)]


def placebo(df, y, covs, nb, primary_est, seed=SEED):
    rng = np.random.default_rng(seed)
    pl = displaced_payload(df, rng)
    est, ci, sd = day_boot(pl, y, covs, max(nb // 4, 200), seed)
    ratio = abs(est) / abs(primary_est) if primary_est else None
    return {"drives": int(len(pl)), "days": int(pl["day"].nunique()), "slope_per100kg": est, "ci95": ci, "ratio_to_primary": ratio, "interval_excludes_zero": bool(ci[0] > 0 or ci[1] < 0),
            "read": "association not separable from route and day structure" if (ci[0] > 0 or ci[1] < 0 or (ratio is not None and ratio > 0.5)) else "placebo contains zero and is below half of the primary"}


def within_day_variation(df):
    """Diagnostic only: the share of days whose estimated payload varies between drives."""
    g = df.groupby("day")["payload100"].nunique()
    multi = g[df.groupby("day").size().reindex(g.index) > 1]
    return float((multi > 1).mean()) if len(multi) else None


# ------------------------------------------------------------------ kinematic reference B1
def kinematic_reference(v, dt):
    """Per-kg positive kinetic-energy throughput (J/kg) = sum of 0.5 (v2^2 - v1^2) over accelerating steps and the distance (m) from a speed trace (m/s) and its time steps (s)."""
    v = np.asarray(v, float)
    dt = np.asarray(dt, float)
    dv2 = np.diff(v ** 2)
    ke = float(np.sum(0.5 * np.clip(dv2, 0.0, None)))
    dist = float(np.sum(0.5 * (v[1:] + v[:-1]) * dt[1:]))
    return ke, dist


def b1_payload_energy(ke_per_kg, dist_m, payload_kg, c_rr):
    """Mass-dependent work added by a payload (kWh per 100 km): (KE throughput per kg + C_rr g d) x payload, scaled to 100 km."""
    if dist_m <= 0:
        return float("nan")
    e_j = payload_kg * (ke_per_kg + c_rr * G_ACC * dist_m)
    return e_j / 3.6e6 * (100000.0 / dist_m)


# ------------------------------------------------------------------ data
def load_frame(master, fuel_csv, payload_csv, seasonal):
    dm = pd.read_csv(master, low_memory=False)
    fr = pd.read_csv(fuel_csv)
    pl = pd.read_csv(payload_csv)
    sd = pd.read_csv(seasonal, usecols=["file", "thermal_regime", "ambient_time_mean_c"], low_memory=False)
    d = dm[["file", "date", "drive_type", "distance_km", "time_start", "speed_mean_moving", "speed_p95", "soc_delta_kwh", "ens_outlier_v2"]].copy()
    d["date"] = d["date"].astype(str)
    d = d.merge(pl[["file", "has_pattern", "payload_low", "payload_central", "payload_high", "class_mass"]], on="file", how="left")
    d = d.merge(sd, on="file", how="left")
    d = d.merge(fr.drop(columns=[c for c in ("drive_type", "date", "distance_km", "soc_delta_kwh") if c in fr.columns]), on="file", how="left")
    d["cls"] = d["drive_type"].where(d["drive_type"].isin(CLASSES), "unknown")
    d["thermal"] = d["thermal_regime"].astype(str)
    d["day"] = d["date"]
    d["month"] = d["date"].str.slice(0, 7)
    d["payload100"] = d["payload_central"] / 100.0
    d["logdist"] = np.log(d["distance_km"].astype(float))
    d["v2"] = d["speed_mean_moving"].astype(float) ** 2
    d["dsoc100"] = d["soc_delta_kwh"].astype(float) / d["distance_km"].astype(float) * 100.0
    d["ambient"] = d["ambient_time_mean_c"].astype(float)
    order = d.sort_values(["date", "time_start"]).groupby("date").cumcount()
    d["first_of_day"] = (order.reindex(d.index) == 0).astype(float)
    return d


def eligible(d, dist_min=DIST_MIN, need_fuel=True):
    ok = (d["ens_outlier_v2"].astype(str).str.lower() != "true") & d["has_pattern"].astype(str).eq("True") & (d["distance_km"].astype(float) >= dist_min) & d["cls"].isin(CLASSES)
    if need_fuel:
        ok &= d["fuel_L_per_100km"].notna()
    ok &= d[["payload100", "ambient", "v2", "dsoc100", "logdist"]].notna().all(1)
    return d[ok].copy()


COVS = ["ambient", "logdist", "speed_mean_moving", "v2", "dsoc100", "first_of_day"]


def analyse(d, nb, raw_dir=None, rng_seed=SEED):
    res = {}
    e = eligible(d)
    res["design_mde"] = design_mde(e)
    exp = expectation_per100kg(float(e["fuel_L_per_100km"].mean()))
    res["expectation_fuel_per100kg"] = dict(exp, mean_fuel_L_per_100km=float(e["fuel_L_per_100km"].mean()), elasticity_bracket=list(ELASTICITY))
    est, ci, sd = day_boot(e, "fuel_L_per_100km", COVS, nb)
    mde = 2.8 * sd
    res["A1"] = {"outcome": "fuel_L_per_100km (logged / app-calculated)", "drives": int(len(e)), "days": int(e["day"].nunique()), "slope_per100kg_payload": est, "ci95": ci, "bootstrap_sd": sd, "mde": mde,
                 "reading": reading(mde, exp["low"]), "covariates": ["drive class", "thermal class"] + COVS,
                 "placebo_displaced_day": placebo(e, "fuel_L_per_100km", COVS, nb, est), "within_day_payload_varies_share": within_day_variation(e)}
    low, high = e.copy(), e.copy()
    low["payload100"] = e["payload_low"] / 100.0
    high["payload100"] = e["payload_high"] / 100.0
    res["A1"]["bracket_slope_low_high"] = [ols_slope(low.dropna(subset=["payload100"]), "fuel_L_per_100km", COVS), ols_slope(high.dropna(subset=["payload100"]), "fuel_L_per_100km", COVS)]
    sens = {}
    for dm_ in (2.0, 10.0):
        es = eligible(d, dm_)
        sens["distance_floor_%g_km" % dm_] = {"drives": int(len(es)), "days": int(es["day"].nunique()), "slope_per100kg_payload": ols_slope(es, "fuel_L_per_100km", COVS)}
    res["A1"]["sensitivities"] = sens
    a2 = {}
    for y in OUTCOMES_A2:
        ey = e[e[y].notna()]
        if len(ey) < 60 or ey["day"].nunique() < 20:
            a2[y] = {"counts_only": True, "drives": int(len(ey)), "days": int(ey["day"].nunique())}
            continue
        est2, ci2, sd2 = day_boot(ey, y, COVS, max(nb // 2, 500))
        a2[y] = {"drives": int(len(ey)), "days": int(ey["day"].nunique()), "mean": float(ey[y].mean()), "slope_per100kg_payload": est2, "ci95": ci2, "mde": 2.8 * sd2,
                 "label": "model-derived (fuel flow x BSFC plus battery power minus auxiliaries)" if y not in ("regen_to_batt_kWh_100",) else "from logged current"}
    res["A2_exploratory"] = a2
    a3 = {}
    for c in CLASSES:
        ec = e[e["cls"] == c]
        if len(ec) < 100 or ec["day"].nunique() < 30:
            a3[c] = {"counts_only": True, "drives": int(len(ec)), "days": int(ec["day"].nunique())}
        else:
            e3, c3, s3 = day_boot(ec.assign(cls="x"), "fuel_L_per_100km", [c_ for c_ in COVS], max(nb // 2, 500))
            a3[c] = {"drives": int(len(ec)), "days": int(ec["day"].nunique()), "slope_per100kg_payload": e3, "ci95": c3, "mde": 2.8 * s3}
    res["A3_exploratory"] = a3
    allp = d[(d["ens_outlier_v2"].astype(str).str.lower() != "true")]
    with_pat = allp[allp["has_pattern"].astype(str) == "True"]
    without = allp[allp["has_pattern"].astype(str) != "True"]
    res["C_integrity"] = {"drives_with_pattern": int(len(with_pat)), "drives_without_pattern": int(len(without)), "fuel_basis_drives_eligible": int(len(e)),
                          "mean_distance_km": {"with_pattern": float(with_pat["distance_km"].astype(float).mean()), "without_pattern": float(without["distance_km"].astype(float).mean())},
                          "class_counts_with_pattern": {c: int((with_pat["cls"] == c).sum()) for c in CLASSES}, "class_counts_without_pattern": {c: int((without["cls"] == c).sum()) for c in CLASSES + ("unknown",)},
                          "payload_mean_kg": float(e["payload_central"].mean()), "payload_sd_kg": float(e["payload_central"].std(ddof=1))}
    return res, e


def b1_block(e, raw_dir, dsg, nb):
    """Kinematic reference on the eligible drives with a speed trace: mean added work per 100 km for the mean payload under each C_rr, with a day-clustered interval."""
    rows = []
    for _, r in e.iterrows():
        p = os.path.join(raw_dir, r["file"])
        if not os.path.exists(p):
            continue
        a = dsg.speed_only_arrays(p, 0.0)
        if a is None:
            continue
        ke, dist = kinematic_reference(a["v"], a["dt"])
        rows.append((r["day"], ke, dist, float(r["payload_central"])))
    if not rows:
        return {"counts_only": True, "drives": 0}
    t = pd.DataFrame(rows, columns=["day", "ke", "dist", "pay"])
    out = {"drives": int(len(t)), "days": int(t["day"].nunique()), "label": "kinematic reference (kinetic-energy throughput of the logged speed plus assumed rolling work); not a measured or reconstructed traction energy; aerodynamic work excluded"}
    rng = np.random.default_rng(SEED)
    ud = t["day"].unique()
    by = {d_: t[t["day"] == d_] for d_ in ud}
    for c in C_RR:
        v = np.array([b1_payload_energy(a, b, c_, c) for a, b, c_ in zip(t["ke"], t["dist"], t["pay"])])
        est = float(np.nanmean(v))
        boots = []
        for _ in range(min(nb, 2000)):
            pick = rng.choice(ud, len(ud))
            tt = pd.concat([by[p] for p in pick])
            boots.append(float(np.nanmean([b1_payload_energy(a, b, c_, c) for a, b, c_ in zip(tt["ke"], tt["dist"], tt["pay"])])))
        out["C_rr_%g" % c] = {"payload_work_kWh_per_100km_at_mean_payload": est, "ci95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--raw-dir", default=os.environ.get("XT_RAW_DIR") or "")
    ap.add_argument("--out-dir", default=os.path.join(HERE, "..", "analyses"))
    ap.add_argument("--master", default=os.path.join(HERE, "..", "drive_master.csv"))
    ap.add_argument("--fuel", default=os.path.join(HERE, "..", "fuel_recon_master.csv"))
    ap.add_argument("--payload", default=os.path.join(HERE, "..", "analyses", "M753_drive_payload.csv"))
    ap.add_argument("--seasonal", default=os.path.join(HERE, "..", "seasonal_drive_master.csv"))
    ap.add_argument("--nb", type=int, default=NB_DEFAULT)
    a = ap.parse_args(argv)
    if not a.run:
        print(__doc__)
        return 0
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = time.time()
    try:
        if md5(a.master) != PINNED_MD5:
            print("payload_energy: master pin failed")
            return 1
        import dem_step_grade as dsg
        import odometer_jump_audit as J
        d = load_frame(a.master, a.fuel, a.payload, a.seasonal)
        res_core, e = analyse(d, a.nb)
        res = {"milestone": "M769", "spec": "analyses/M769_spec.md Rev 2", "masterMd5": PINNED_MD5, "toolSha256": sha256(os.path.abspath(__file__)), "seed": SEED, "nBoot": a.nb,
               "inputs": {"fuel_recon_master_sha256": sha256(a.fuel), "payload_table_sha256": sha256(a.payload)}}
        res.update(res_core)
        res["B1_kinematic_reference"] = b1_block(e, a.raw_dir, dsg, a.nb) if a.raw_dir and os.path.isdir(a.raw_dir) else {"skipped": "no raw directory"}
        res["limits"] = ["payload is estimated from latched seatbelts with owner-estimated seat weights; a latched belt is not a weight; proxy error attenuates the slope",
                         "association, not an effect of mass: occupants coincide with leisure, weekend and highway trips and HVAC use; fuel mass (0 to 40 kg) is unobserved",
                         "a null result is not 'no mass sensitivity' (no equivalence test); the reading rule uses the lower end of the pre-registered elasticity bracket 0.2 to 0.6",
                         "gross traction, generator and generator-to-traction energy are model-derived; regeneration-to-battery energy is from logged current; fuel is logged / app-calculated",
                         "B1 is a kinematic reference with an assumed rolling coefficient, not a measured mass effect; the class mass is not replaced; not an article figure"]
        res["seconds"] = round(time.time() - t0, 1)
        bad = J.scan_privacy(res)
        if bad:
            raise Stop("privacy scan failed: %s" % bad[:3])
        if md5(a.master) != PINNED_MD5:
            raise Stop("drive_master.csv changed during the run")
        os.makedirs(a.out_dir, exist_ok=True)
        with open(os.path.join(a.out_dir, "M769_payload_energy.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(res, f, indent=1, default=lambda o: None if o != o else str(o))
        print("payload_energy: A1 slope %.3f L/100km per 100 kg [%.3f, %.3f], MDE %.3f, %s" % (res["A1"]["slope_per100kg_payload"], res["A1"]["ci95"][0], res["A1"]["ci95"][1], res["A1"]["mde"], res["A1"]["reading"]))
        return 0
    except Stop as e:
        print("payload_energy: STOP (%s)" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
