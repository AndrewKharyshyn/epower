#!/usr/bin/env python3
"""M771 (spec analyses/M771_spec.md Rev 2): weather proxies from the cloud export (wipers, lighting) and the drive-level figures. Auxiliary, report-only, offline.

G (support gate, written first): counts of wet-proxy drives (wiper share of the moving cloud rows at least 0.05, at least 10 rows) by class, thermal class and month, the fuel-basis counts, the within-month share of the proxy, the matched-pair
support and the design MDE; hard floor 20 wet-proxy drives on 10 days on the fuel basis. A1 (confirmatory) = fuel L/100 km (logged / app-calculated), the adjusted wet-proxy minus dry difference with month fixed effects, ONLY if the gate passes
(else counts only). A2 exploratory: SoC-ledger quantities (net battery draw, gross discharge) and the regeneration share, kWh per 100 km, never percentages. A3 darkness proxy excluding wet-proxy drives (exploratory). Displaced-day placebo.
Wiper wording: a precipitation, spray or washing proxy; never rain. Aggregates only. Reuses tools/tyre_rolling.py and tools/payload_energy.py.
Usage: python tools/weather_proxy.py --run [--out-dir analyses] [--nb 4000]   Exit codes: 0 done, 1 master pin, 3 stop."""
import argparse, json, os, sys, time
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import payload_energy as PE
import tyre_rolling as T

SEED, NB_DEFAULT = 42, 4000
PINNED_MD5 = PE.PINNED_MD5
MIN_ROWS = 10
WET_THRESHOLDS = (0.05, 0.02, 0.20)                      # primary first
DARK_HI, DARK_LO = 0.5, 0.05
FLOOR_DRIVES, FLOOR_DAYS = 20, 10
EXPECT_LOWER_PCT = 2.0                                   # assumed lower end of the fuel expectation, % of the dry mean fuel rate
COVS = ["ambient", "logdist", "speed_mean_moving", "v2", "first_of_day"]
A2_OUTCOMES = ("net_draw_per100km_corr2p", "gross_discharge_per100km", "regen_share_of_charge")


# ------------------------------------------------------------------ proxy definitions
def wet_label(share, rows, thr):
    """1 = wet-proxy drive (share at least thr), 0 = dry reference (share exactly 0), NaN = excluded (too few rows, or a share between 0 and thr)."""
    share = np.asarray(share, float)
    rows = np.asarray(rows, float)
    out = np.full(len(share), np.nan)
    ok = np.isfinite(share) & (rows >= MIN_ROWS)
    out[ok & (share >= thr)] = 1.0
    out[ok & (share == 0.0)] = 0.0
    return out


def dark_label(lowbeam, rows, wet_primary):
    """1 = dark-proxy drive (low beam at least 0.5), 0 = reference (below 0.05); wet-proxy drives are excluded (auto lamps react to rain)."""
    lb = np.asarray(lowbeam, float)
    rows = np.asarray(rows, float)
    out = np.full(len(lb), np.nan)
    ok = np.isfinite(lb) & (rows >= MIN_ROWS) & ~(np.asarray(wet_primary, float) == 1.0)
    out[ok & (lb >= DARK_HI)] = 1.0
    out[ok & (lb < DARK_LO)] = 0.0
    return out


# ------------------------------------------------------------------ gate
def matched_support(df):
    """Gate count only: a wet-proxy drive is matchable when a dry drive of the same class, thermal class and month with distance within 25 % exists on another day."""
    n = 0
    key = df["cls"].astype(str) + "|" + df["thermal"].astype(str) + "|" + df["month"].astype(str)
    dry = df[df["wet"] == 0.0]
    dkey = key[dry.index]
    for i in df.index[df["wet"] == 1.0]:
        c = dry[(dkey.values == key[i]) & (dry["day"].values != df.at[i, "day"]) & (np.abs(dry["distance_km"].values / df.at[i, "distance_km"] - 1.0) <= 0.25)]
        n += int(len(c) > 0)
    return n


def within_month_share(df):
    """Share of the variance of the wet label that lies within months (1 - between-month share)."""
    d = df[df["wet"].isin([0.0, 1.0])]
    if len(d) < 3 or d["wet"].var() == 0:
        return None
    mm = d.groupby("month")["wet"].transform("mean")
    return float(((d["wet"] - mm) ** 2).sum() / ((d["wet"] - d["wet"].mean()) ** 2).sum())


def gate(df, fuel_df):
    out = {"thresholds": {}}
    for thr in WET_THRESHOLDS:
        lab = wet_label(df["wiper_nonzero_share"], df["moving_n_veh"], thr)
        w = df[lab == 1.0]
        wf = fuel_df[wet_label(fuel_df["wiper_nonzero_share"], fuel_df["moving_n_veh"], thr) == 1.0]
        out["thresholds"]["%g" % thr] = {"wet_proxy_drives": int(len(w)), "wet_proxy_days": int(w["day"].nunique()), "fuel_basis_wet_proxy_drives": int(len(wf)), "fuel_basis_wet_proxy_days": int(wf["day"].nunique()),
                                         "dry_reference_drives": int(((lab == 0.0)).sum())}
    p = out["thresholds"]["%g" % WET_THRESHOLDS[0]]
    out["floor"] = {"drives": FLOOR_DRIVES, "days": FLOOR_DAYS}
    out["passed"] = bool(p["fuel_basis_wet_proxy_drives"] >= FLOOR_DRIVES and p["fuel_basis_wet_proxy_days"] >= FLOOR_DAYS)
    return out


def boot_diff(df, y, nb, month_fe=True):
    """Adjusted difference (wet minus dry) with class and thermal indicators, covariates and month fixed effects; day-clustered bootstrap; counts the rank-deficient resamples."""
    d = df[df["wet"].isin([0.0, 1.0])].copy()
    d["reg"] = d["wet"]
    T.RANK_DEFICIENT["draws"] = T.RANK_DEFICIENT["deficient"] = 0
    extra = ("month",) if month_fe else ()
    est, ci, sd = T.boot(d, y, COVS, nb, extra_cat=extra)
    return {"difference_after_adjustment": est, "ci95": ci, "mde": 2.8 * sd, "drives": int(len(d)), "wet_drives": int((d["reg"] == 1).sum()), "days": int(d["day"].nunique()),
            "bootstrap_rank_deficient_resamples": dict(T.RANK_DEFICIENT)}


def displaced_labels(df, rng):
    """Displaced-day placebo: each drive gets the wet label of another drive from a DIFFERENT day in the same class, thermal class and month with distance within 25 %; drives without a donor are dropped."""
    d = df.reset_index(drop=True)
    key = (d["cls"].astype(str) + "|" + d["thermal"].astype(str) + "|" + d["month"].astype(str)).values
    lab = np.full(len(d), np.nan)
    for i in range(len(d)):
        cand = np.where((key == key[i]) & (d["day"].values != d["day"].values[i]) & (np.abs(d["distance_km"].values / d["distance_km"].values[i] - 1.0) <= 0.25))[0]
        if len(cand):
            lab[i] = d["wet"].values[rng.choice(cand)]
    out = d.copy()
    out["wet"] = lab
    return out[np.isfinite(lab)]


# ------------------------------------------------------------------ data
def load(master, fuel, payload, seasonal, coverage):
    d = PE.load_frame(master, fuel, payload, seasonal)
    dm = pd.read_csv(master, low_memory=False, usecols=["file", "net_draw_per100km_corr2p", "gross_discharge_kwh", "regen_share_of_charge"])
    d = d.merge(dm, on="file", how="left")
    d["gross_discharge_per100km"] = d["gross_discharge_kwh"].astype(float) / d["distance_km"].astype(float) * 100.0
    cov = pd.read_csv(coverage)[["file", "wiper_nonzero_share", "lowbeam_share", "moving_n_veh"]]
    return d.merge(cov, on="file", how="left")


def eligible(d, dist_min=PE.DIST_MIN, need_fuel=False):
    ok = (d["ens_outlier_v2"].astype(str).str.lower() != "true") & (d["distance_km"].astype(float) >= dist_min) & d["cls"].isin(PE.CLASSES) & (d["moving_n_veh"].astype(float) >= MIN_ROWS)
    if need_fuel:
        ok &= d["fuel_L_per_100km"].notna()
    ok &= d[["ambient", "v2", "logdist"]].notna().all(axis=1)
    return d[ok].copy()


def analyse(d, nb):
    res = {}
    e_all = eligible(d)
    e_fuel = eligible(d, need_fuel=True)
    for df_ in (e_all, e_fuel):
        df_["wet"] = wet_label(df_["wiper_nonzero_share"], df_["moving_n_veh"], WET_THRESHOLDS[0])
    res["G_support_gate"] = gate(e_all, e_fuel)
    g = res["G_support_gate"]
    res["G_support_gate"]["by_class_thermal_month_wet_proxy_counts"] = {"%s|%s|%s" % k: int(v) for k, v in e_all[e_all["wet"] == 1.0].groupby(["cls", "thermal", "month"]).size().items()}
    res["G_support_gate"]["within_month_share_of_wet_label"] = within_month_share(e_all)
    res["G_support_gate"]["matched_pair_support_wet_drives"] = matched_support(e_all.reset_index(drop=True))
    res["G_support_gate"]["design_note"] = "the design MDE of A1 is not written because the gate fails" if not g["passed"] else "gate passed"
    # A1
    if g["passed"]:
        a1 = boot_diff(e_fuel, "fuel_L_per_100km", nb)
        a1["outcome"] = "fuel_L_per_100km (logged / app-calculated)"
        dry_mean = float(e_fuel.loc[e_fuel["wet"] == 0.0, "fuel_L_per_100km"].mean())
        a1["dry_mean_fuel_L_per_100km"] = dry_mean
        a1["reading"] = T.reading(a1["mde"], EXPECT_LOWER_PCT / 100.0 * dry_mean)
        a1["sign_note"] = T.sign_note(a1["difference_after_adjustment"], a1["ci95"], expected_negative=False)
        res["A1"] = a1
    else:
        pf = g["thresholds"]["%g" % WET_THRESHOLDS[0]]
        res["A1"] = {"counts_only": True, "reason": "below the floor of %d wet-proxy drives on %d days on the fuel basis" % (FLOOR_DRIVES, FLOOR_DAYS), "fuel_basis_wet_proxy_drives": pf["fuel_basis_wet_proxy_drives"],
                     "fuel_basis_wet_proxy_days": pf["fuel_basis_wet_proxy_days"], "reading": "not supported at this support"}
    # A2: SoC-ledger quantities, exploratory, differences in kWh per 100 km (or the share), all eligible drives
    a2 = {}
    nw = int((e_all["wet"] == 1.0).sum())
    wdays = int(e_all.loc[e_all["wet"] == 1.0, "day"].nunique())
    for y in A2_OUTCOMES:
        sub = e_all[e_all[y].notna()]
        nw_y = int((sub["wet"] == 1.0).sum())
        if nw_y < FLOOR_DRIVES or sub.loc[sub["wet"] == 1.0, "day"].nunique() < FLOOR_DAYS:
            a2[y] = {"counts_only": True, "wet_proxy_drives": nw_y, "wet_proxy_days": int(sub.loc[sub["wet"] == 1.0, "day"].nunique())}
            continue
        r = boot_diff(sub, y, max(nb // 2, 500))
        r["label"] = "SoC-ledger quantity, not a road-load measure" if y != "regen_share_of_charge" else "estimated, integrated from logged current"
        a2[y] = r
    res["A2_exploratory"] = a2
    # A3
    ed = e_all.copy()
    ed["wet"] = wet_label(ed["wiper_nonzero_share"], ed["moving_n_veh"], WET_THRESHOLDS[0])
    dk = dark_label(ed["lowbeam_share"], ed["moving_n_veh"], ed["wet"])
    ed["wet"] = dk
    a3 = {"label": "darkness and visibility proxy (mainly marks evening and winter driving); wet-proxy drives excluded", "dark_proxy_drives": int((dk == 1.0).sum()), "reference_drives": int((dk == 0.0).sum())}
    a3["fuel_basis"] = {"dark_proxy_drives": int(((dk == 1.0) & ed["fuel_L_per_100km"].notna().values).sum())}
    sub = ed[ed["fuel_L_per_100km"].notna() & ed["wet"].isin([0.0, 1.0])]
    if int((sub["wet"] == 1).sum()) >= FLOOR_DRIVES and sub.loc[sub["wet"] == 1, "day"].nunique() >= FLOOR_DAYS:
        a3["fuel_L_per_100km"] = boot_diff(sub, "fuel_L_per_100km", max(nb // 2, 500))
    else:
        a3["fuel_L_per_100km"] = {"counts_only": True}
    res["A3_exploratory"] = a3
    # placebo (A1 outcome on the fuel basis when supported, else counts of donors)
    rng = np.random.default_rng(SEED)
    pl = displaced_labels(e_fuel[e_fuel["wet"].isin([0.0, 1.0])], rng)
    res["P_placebo"] = {"drives_with_donor": int(len(pl)), "wet_labelled": int((pl["wet"] == 1.0).sum()), "estimate": "counts only" if not g["passed"] else boot_diff(pl, "fuel_L_per_100km", max(nb // 4, 200))}
    # C
    c = {"drives_eligible": int(len(e_all)), "drives_below_minimum_cloud_rows_or_without": int((d["moving_n_veh"].astype(float).fillna(0) < MIN_ROWS).sum()), "minimum_moving_cloud_rows": MIN_ROWS,
         "ens_outlier_v2_missing_treated_as_clean": int(d["ens_outlier_v2"].isna().sum()), "first_of_day_flag": "computed over all drives of the master by date, not within the contrast sample", "moving_rows_quartiles": [float(x) for x in np.percentile(e_all["moving_n_veh"].astype(float), [25, 50, 75])],
         "wet_proxy_by_month": {k: int(v) for k, v in e_all[e_all["wet"] == 1.0].groupby("month").size().items()}}
    res["C_integrity"] = c
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--out-dir", default=os.path.join(HERE, "..", "analyses"))
    ap.add_argument("--master", default=os.path.join(HERE, "..", "drive_master.csv"))
    ap.add_argument("--fuel", default=os.path.join(HERE, "..", "fuel_recon_master.csv"))
    ap.add_argument("--payload", default=os.path.join(HERE, "..", "analyses", "M753_drive_payload.csv"))
    ap.add_argument("--seasonal", default=os.path.join(HERE, "..", "seasonal_drive_master.csv"))
    ap.add_argument("--coverage", default=os.path.join(HERE, "..", "analyses", "M729_cloud_coverage.csv"))
    ap.add_argument("--nb", type=int, default=NB_DEFAULT)
    a = ap.parse_args(argv)
    if not a.run:
        print(__doc__)
        return 0
    sys.stdout.reconfigure(encoding="utf-8")
    t0 = time.time()
    try:
        if PE.md5(a.master) != PINNED_MD5:
            print("weather_proxy: master pin failed")
            return 1
        import odometer_jump_audit as J
        d = load(a.master, a.fuel, a.payload, a.seasonal, a.coverage)
        res = {"milestone": "M771", "spec": "analyses/M771_spec.md Rev 2", "masterMd5": PINNED_MD5, "toolSha256": PE.sha256(os.path.abspath(__file__)), "seed": SEED, "nBoot": a.nb,
               "inputs": {"coverage_sha256": PE.sha256(a.coverage), "fuel_recon_master_sha256": PE.sha256(a.fuel)}}
        res.update(analyse(d, a.nb))
        res["limits"] = ["wipers are a precipitation, spray or washing proxy (the channel does not distinguish them; the wiper mode is unknown); lighting is a darkness and visibility proxy; no weather-service data",
                         "a drive's wiper share rests on about 12 moving cloud rows (median); the span rule of M729 is not applied at the sample level here (deviation, spec 7.5)",
                         "misclassification (a wet road without wipers, wipers used for washing) biases toward the null; association only, not an effect of weather; season, HVAC and route confound",
                         "net battery draw and gross discharge are SoC-ledger quantities, not road load; the SoC controller holds the battery near balance",
                         "a null or a gated 'not supported' is not 'no weather effect' (no equivalence test)",
                         "not an article figure"]
        res["seconds"] = round(time.time() - t0, 1)
        bad = J.scan_privacy(res)
        if bad:
            print("weather_proxy: STOP (privacy scan failed: %s)" % bad[:3])
            return 3
        if PE.md5(a.master) != PINNED_MD5:
            print("weather_proxy: STOP (drive_master.csv changed during the run)")
            return 3
        os.makedirs(a.out_dir, exist_ok=True)
        with open(os.path.join(a.out_dir, "M771_weather_proxy.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(res, f, indent=1, default=lambda o: None if o != o else str(o))
        g = res["G_support_gate"]["thresholds"]["%g" % WET_THRESHOLDS[0]]
        print("weather_proxy: gate %s | fuel-basis wet-proxy drives %d on %d days | A1 %s" % ("passed" if res["G_support_gate"]["passed"] else "not passed", g["fuel_basis_wet_proxy_drives"], g["fuel_basis_wet_proxy_days"], res["A1"].get("reading")))
        return 0
    except KeyError as e:
        print("weather_proxy: STOP (missing column %s)" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
