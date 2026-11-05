#!/usr/bin/env python3
"""M573 (spec analyses/M573_spec.md Rev 1): step versus trend in the loaded p95 cell-spread slope. Analysis only: reads drive_master.csv and raw CSVs
read-only, writes analyses/M573_step_vs_trend.json, touches nothing else (no ingestion, no payload key, no master column).
Items: 1 step vs trend (AIC, day-blocked CV), 2 covariates (SOC, rest time), 3 dependence (leave-one-week-out, ISO-week cluster, week-block bootstrap,
seed 42, 4000), 4 matched-state contrast, 4b cold-start sensors and equal-length segments (raw), 5 logger cadence by month, 7 external descriptive check of
un-ingested files (never enters a fit). Usage: python tools/m573_cell_spread_step.py [--skip-raw] [--external DIR NAME ...] [--out PATH]
M574 (spec analyses/M574_spec.md Rev 1): --splice runs items 1-5 and 4b (never --external), writes analyses/M574_check.json and the additive payload block cellSpreadStep (+ stamp) into summary_arrays.json."""
import argparse, copy, datetime, hashlib, json, os, sys
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, ROOT)
SEED, NBOOT = 42, 4000
STEP_DATE = "2026-10-01"
LATE = ("2026-10-10", "2026-10-17")
SEP = ("2026-09-01", "2026-09-30")
LOOKS = os.path.join(ROOT, "analyses", "M580_looks.json")       # M580: append-only ledger of the ingestion looks at the confirmatory block (written only by --splice)
TERM_DRIVES, TERM_DAYS, TERM_FALLBACK = 20, 10, "2027-01-31"      # M580 Rev 1: terminal evaluation point (in-range drives / in-range days after the cutoff; fallback date)
CUTOFF = "2026-10-17"                       # confirmatory test: drives dated after this day (M573 Rev 2, pre-registered)
ARR = os.path.join(ROOT, "summary_arrays.json")
YCOL, TCOL, ICOL = "cell_spread_loaded_p95_mv", "T_pack_mean_avg", "peak_I_discharge"


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _r(x, nd=3):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), nd)


def fit_cluster(d, cols, group="day", ycol="y", coef="months"):
    """Cluster-robust OLS (released protocol: cluster covariance, t(G-1) interval). Returns the estimate of `coef` plus n, G, AIC, R2."""
    X = sm.add_constant(d[cols].astype(float))
    ols = sm.OLS(d[ycol].astype(float).values, X)
    res = ols.fit(cov_type="cluster", cov_kwds={"groups": d[group].values})
    G = int(d[group].nunique())
    tcrit = float(stats.t.ppf(0.975, G - 1)) if G > 1 else float(stats.norm.ppf(0.975))
    b, se = float(res.params[coef]), float(res.bse[coef])
    return {"est": _r(b, 4), "se": _r(se, 4), "ci95": [_r(b - tcrit * se, 4), _r(b + tcrit * se, 4)], "n": int(len(d)), "G": G,
            "aic": _r(ols.fit().aic, 2), "r2": _r(res.rsquared, 4)}


def week_block_bootstrap(d, cols, coef="months", n=NBOOT, seed=SEED, group="wk", ycol="y"):
    """Percentile interval of `coef` with calendar-week blocks as the resampling unit."""
    rng = np.random.default_rng(seed)
    keys = d[group].unique()
    parts = {k: g for k, g in d.groupby(group)}
    j = 1 + cols.index(coef)
    out = []
    for _ in range(n):
        s = pd.concat([parts[k] for k in rng.choice(keys, len(keys))])
        A = np.c_[np.ones(len(s)), s[cols].values.astype(float)]
        out.append(np.linalg.lstsq(A, s[ycol].values.astype(float), rcond=None)[0][j])
    out = np.asarray(out)
    return {"ci95": [_r(np.percentile(out, 2.5), 4), _r(np.percentile(out, 97.5), 4)], "median": _r(np.median(out), 4), "pGt0": _r((out > 0).mean(), 4), "nBlocks": int(len(keys)), "draws": n, "seed": seed}


def day_blocked_cv(d, cols, k=10, ycol="y"):
    """RMSE of out-of-fold predictions with whole calendar days held out (deterministic folds: days sorted, dealt round-robin)."""
    days = np.array(sorted(d["day"].unique()))
    fold = {dy: i % k for i, dy in enumerate(days)}
    f = d["day"].map(fold).values
    err = np.full(len(d), np.nan)
    X = sm.add_constant(d[cols].astype(float)).values
    y = d[ycol].astype(float).values
    for i in range(k):
        te = f == i
        if te.all() or not te.any():
            continue
        beta = np.linalg.lstsq(X[~te], y[~te], rcond=None)[0]
        err[te] = y[te] - X[te] @ beta
    return _r(np.sqrt(np.nanmean(err ** 2)), 3)


def month_fe(d):
    m = pd.get_dummies(d["date"].dt.strftime("%m"), prefix="m", drop_first=True).astype(float)
    return pd.concat([d, m.set_index(d.index)], axis=1), list(m.columns)


def build_frame(dm):
    """Analysis frame on the canonical-clean set exactly as the released estimator (degradation_trends._prep), plus covariates."""
    import degradation_trends as dt
    full = dm.copy()
    full["_ts"] = pd.to_datetime(full["date"].astype(str) + " " + full["time_start"].astype(str), errors="coerce")
    full["_te"] = pd.to_datetime(full["date"].astype(str) + " " + full["time_end"].astype(str), errors="coerce")
    full = full.sort_values("_ts")
    full["rest_h"] = (full["_ts"] - full["_te"].shift()).dt.total_seconds() / 3600.0
    d = dt._prep(full, YCOL, icol=ICOL)
    d = d.dropna(subset=["T", "I"]).copy()
    d["soc"] = d["rf_socmean_wtd_pct"]
    d["socr"] = d["soc_max"] - d["soc_min"]
    d["lrest"] = np.log1p(d["rest_h"].clip(0, 200))
    d["first"] = (d["rest_h"] > 4).astype(float)
    d["step"] = (d["date"] >= STEP_DATE).astype(float)
    d["wk"] = d["date"].dt.strftime("%G-%V")
    d["slow"] = (d["I_sample_period_s"] >= 1.05).astype(float)
    return d


def item_models(d):
    base = ["months", "T", "I"]
    soc = base + ["soc", "socr"]
    rest = soc + ["lrest", "first"]
    specs = {"M0_linear_released": base, "M1_linear_soc": soc, "M2_linear_soc_rest": rest,
             "M3_step": ["months", "step", "T", "I"], "M4_step_soc": ["months", "step"] + soc[1:], "M5_step_soc_rest": ["months", "step"] + rest[1:]}
    out = {}
    dd = d.dropna(subset=["soc", "socr", "lrest"]).copy()
    for name, cols in specs.items():
        dat = d if name == "M0_linear_released" else dd
        r = fit_cluster(dat, cols)
        r["cv_rmse_day_blocked"] = day_blocked_cv(dat, cols)
        if "step" in cols:
            r["step_term"] = {k: v for k, v in fit_cluster(dat, cols, coef="step").items() if k in ("est", "se", "ci95")}
        r["formula"] = "y ~ " + " + ".join(cols)
        out[name] = r
    fe, fe_cols = month_fe(dd)
    r = fit_cluster(fe, ["T", "I", "soc", "socr"] + fe_cols, coef="T")
    out["M6_month_fixed_effects"] = {"aic": r["aic"], "r2": r["r2"], "n": r["n"], "cv_rmse_day_blocked": day_blocked_cv(fe, ["T", "I", "soc", "socr"] + fe_cols),
                                     "formula": "y ~ T + I + soc + socr + month dummies (no linear months term)"}
    # data-driven single level-step scan on the M1 residual (descriptive; the pre-set date STEP_DATE is the tested one)
    X = sm.add_constant(dd[["T", "I", "soc"]]); res = sm.OLS(dd["y"], X).fit().resid
    dd = dd.assign(res=res)
    days = sorted(dd["day"].unique())
    scan = []
    for c in days[20:-10]:
        a, b = dd.loc[dd["day"] < c, "res"], dd.loc[dd["day"] >= c, "res"]
        scan.append((c, float(b.mean() - a.mean()), float(((a - a.mean()) ** 2).sum() + ((b - b.mean()) ** 2).sum())))
    scan.sort(key=lambda t: t[2])
    out["changePointScan"] = {"best": [{"day": c, "jump_mv": _r(j, 2)} for c, j, _ in scan[:3]], "note": "descriptive; residual of y ~ T + I + soc; not a tested date"}
    return out, dd


def item_dependence(dd):
    cols = ["months", "T", "I", "soc", "socr"]
    stp = ["months", "step", "T", "I", "soc", "socr"]
    out = {"weekCluster_linear": fit_cluster(dd, cols, group="wk"), "weekCluster_step": fit_cluster(dd, stp, group="wk"),
           "weekBlockBootstrap_linear": week_block_bootstrap(dd, cols), "weekBlockBootstrap_step": week_block_bootstrap(dd, stp)}
    loo = []
    for w in sorted(dd["wk"].unique()):
        r = fit_cluster(dd[dd["wk"] != w], cols)
        loo.append({"weekDropped": w, "est": r["est"], "ci95": r["ci95"]})
    out["leaveOneWeekOut_linear"] = loo
    out["leaveOneWeekOut_range"] = [min(x["est"] for x in loo), max(x["est"] for x in loo)]
    res = sm.OLS(dd["y"], sm.add_constant(dd[cols])).fit().resid
    dm_ = dd.assign(res=res.values).groupby("day")["res"].mean()
    out["dayMeanResidualAutocorrLag1"] = _r(dm_.autocorr(1), 3)
    return out


def item_matched(dd):
    d = dd.copy()
    d["grp"] = np.where((d["date"] >= LATE[0]) & (d["date"] <= LATE[1] + " 23:59"), "late", np.where((d["date"] >= SEP[0]) & (d["date"] <= SEP[1] + " 23:59"), "sep", None))
    d = d[d["grp"].notna()].copy()
    d["cT"] = pd.cut(d["T"], [-99, 15, 20, 25, 30, 99], labels=False)
    d["cI"] = pd.cut(d["I"], [0, 60, 90, 120, 160, 999], labels=False)
    d["cS"] = pd.cut(d["soc"], [0, 57, 61, 65, 100], labels=False)
    d["cD"] = pd.cut(d["distance_km"], [-1, 5, 25, 9999], labels=False)

    def eff(x):
        cells = x.groupby(["cT", "cI", "cS", "cD", "grp"])["y"].agg(["mean", "size"]).unstack("grp").dropna()
        if cells.empty:
            return np.nan, 0, 0
        w = cells[("size", "late")]
        return float(((cells[("mean", "late")] - cells[("mean", "sep")]) * w).sum() / w.sum()), int(len(cells)), int(w.sum())
    e, ncell, nlate = eff(d)
    rng = np.random.default_rng(SEED)
    ds = {g: [x for _, x in d[d["grp"] == g].groupby("day")] for g in ("late", "sep")}
    boots = []
    for _ in range(NBOOT):
        s = pd.concat([ds[g][i] for g in ("late", "sep") for i in rng.integers(0, len(ds[g]), len(ds[g]))])
        v = eff(s)[0]
        if np.isfinite(v):
            boots.append(v)
    boots = np.asarray(boots)
    return {"definition": "late (%s..%s) minus September, coarsened-exact matched on pack-T class (5), peak-I class (5), SOC class (4), distance class (3); weights = late drives per cell" % LATE,
            "effect_mv": _r(e, 2), "ci95_dayclustered_bootstrap": [_r(np.percentile(boots, 2.5), 2), _r(np.percentile(boots, 97.5), 2)] if len(boots) else None,
            "matchedCells": ncell, "lateDrivesMatched": nlate, "lateDrivesTotal": int((d["grp"] == "late").sum()), "sepDrives": int((d["grp"] == "sep").sum()),
            "lateDays": int(d.loc[d["grp"] == "late", "day"].nunique()), "sepDays": int(d.loc[d["grp"] == "sep", "day"].nunique()), "draws": len(boots), "seed": SEED}


def item_cadence(dm, dd):
    d = dm.copy(); d["date"] = pd.to_datetime(d["date"])
    d["slow"] = d["I_sample_period_s"] >= 1.05
    d["per"] = np.where(d["date"] >= LATE[0], "Oct10-17", d["date"].dt.strftime("%Y-%m"))
    g = d.groupby("per").agg(n=("slow", "size"), slowShare=("slow", "mean"), medianPeriod_s=("I_sample_period_s", "median"))
    cols = ["months", "T", "I", "soc", "socr"]
    r0 = fit_cluster(dd, cols)
    r1 = fit_cluster(dd, cols + ["slow"])
    cols2 = ["months", "step", "slow", "T", "I", "soc", "socr"]
    r2 = fit_cluster(dd, cols2)
    st2 = fit_cluster(dd, cols2, coef="step")
    return {"stepTermWithRegime": {k: st2[k] for k in ("est", "se", "ci95")}, "regimeTermWithStep": {k: v for k, v in fit_cluster(dd, cols2, coef="slow").items() if k in ("est", "se", "ci95")},"byPeriod": {k: {"n": int(v.n), "slowShare": _r(v.slowShare, 2), "medianPeriod_s": _r(v.medianPeriod_s, 3)} for k, v in g.iterrows()},
            "slopeWithoutRegime": {k: r0[k] for k in ("est", "ci95")}, "slopeWithRegime": {k: r1[k] for k in ("est", "ci95")}, "slopeWithRegimeAndStep": {k: r2[k] for k in ("est", "ci95")},
            "regimeRule": "slow: I_sample_period_s >= 1.05 s (M379a)"}


# ----------------------------------------------------------------------------------------------- raw-based items
def _paired_spread(csv_bytes):
    """Pipeline pairing (compute_drive_summary_v6: Vmax/Vmin merge_asof within SPREAD_TOL; I aligned within V_ALIGN_TOL). Returns (frame t, spread_mv, I, T1..T4 start, t0)."""
    import compute_drive_summary_v6 as c
    df, t = c._prep_bytes(csv_bytes)
    vmax, vmin = c._series(df, t, "Vcell_max", lo=2.0, hi=5.0), c._series(df, t, "Vcell_min", lo=2.0, hi=5.0)
    I = c._series(df, t, "I")
    if I is not None:
        I = I[I["v"].abs() < 900]
    if vmax is None or vmin is None:
        return None
    p = pd.merge_asof(vmax.rename(columns={"v": "vmax"}), vmin.rename(columns={"v": "vmin"}), on="t", direction="nearest", tolerance=pd.Timedelta(c.SPREAD_TOL)).dropna().reset_index(drop=True)
    p["spread"] = (p["vmax"] - p["vmin"]) * 1000.0
    p = c._asof(p, I, "I", c.V_ALIGN_TOL)
    t0 = t.min()
    p["s"] = (p["t"] - t0).dt.total_seconds()
    temps = []
    for k in ("T1", "T2", "T3", "T4"):
        s = c._series(df, t, k, lo=-40, hi=90)
        temps.append(float(s["v"].iloc[0]) if s is not None else np.nan)
    return p, temps


def _raw_path(raw_dir, fn):
    p = os.path.join(raw_dir, fn)
    return p if os.path.exists(p) else os.path.join(raw_dir, fn[:10] + " " + fn[11:])


def item_cold_and_segments(dm, d_all, raw_dir):
    rows = []
    sub = d_all[((d_all["date"] >= SEP[0]) & (d_all["date"] <= SEP[1] + " 23:59")) | ((d_all["date"] >= LATE[0]) & (d_all["date"] <= LATE[1] + " 23:59"))]
    for _, r in sub.iterrows():
        pth = _raw_path(raw_dir, r["file"])
        if not os.path.exists(pth):
            continue
        out = _paired_spread(open(pth, "rb").read())
        if out is None:
            continue
        p, temps = out
        row = {"file": r["file"], "date": r["date"], "late": float(r["date"] >= pd.Timestamp(LATE[0])), "rest_h": r["rest_h"], "T": r["T"], "Imax": r["I"], "y": r["y"], "t1": temps[0], "t2": temps[1], "t3": temps[2], "t4": temps[3]}
        for lab, (a, b) in {"w0_2": (0, 120), "w2_10": (120, 600)}.items():
            w = p[(p["s"] >= a) & (p["s"] < b)]
            row[lab + "_med"] = w["spread"].median() if len(w) >= 5 else np.nan
            row[lab + "_p95"] = w["spread"].quantile(0.95) if len(w) >= 20 else np.nan
            row[lab + "_absI"] = w["I"].abs().median() if len(w) >= 5 else np.nan
        w = p[(p["s"] < 1200) & (p["I"].abs() > 50)]
        row["first20_loaded_p95"] = w["spread"].quantile(0.95) if len(w) >= 10 else np.nan
        row["first20_n_loaded"] = len(w)
        rows.append(row)
    f = pd.DataFrame(rows)
    f["tmean"] = f[["t1", "t2", "t3", "t4"]].mean(axis=1)
    f["trange"] = f[["t1", "t2", "t3", "t4"]].max(axis=1) - f[["t1", "t2", "t3", "t4"]].min(axis=1)
    f["pairgrad"] = (f.t1 + f.t2) / 2 - (f.t3 + f.t4) / 2
    cold = f[(f["rest_h"] > 4) | f["rest_h"].isna()].copy()

    def eff(dat, ycol, adj):
        x = dat.dropna(subset=[ycol] + adj)
        if len(x) < 12 or x["late"].nunique() < 2:
            return None
        res = sm.OLS(x[ycol], sm.add_constant(x[adj + ["late"]])).fit(cov_type="cluster", cov_kwds={"groups": x["date"].astype(str).values})
        G = x["date"].nunique(); t = stats.t.ppf(0.975, G - 1)
        b, se = float(res.params["late"]), float(res.bse["late"])
        return {"lateEffect_mv": _r(b, 2), "ci95": [_r(b - t * se, 2), _r(b + t * se, 2)], "n": int(len(x)), "nLate": int(x["late"].sum()), "days": int(G)}
    o = {"definition": "cold start = first drive after >4 h rest; late = %s..%s vs September; effect adjusted for start-sensor mean T and the window median |I| (day-clustered, t(G-1))" % LATE,
         "startTempMedians_cold": {g: {k: _r(v, 1) for k, v in cold[cold["late"] == g][["t1", "t2", "t3", "t4", "tmean", "trange", "pairgrad"]].median().items()} for g in (0.0, 1.0)},
         "nCold": {"sep": int((cold["late"] == 0).sum()), "late": int((cold["late"] == 1).sum())},
         "wholeDriveLoadedP95_cold": eff(cold, "y", ["tmean"]),
         "wholeDriveLoadedP95_cold_plusPairGradient": eff(cold, "y", ["tmean", "pairgrad"]),
         "earlyWindow_0_2min_median": eff(cold, "w0_2_med", ["tmean", "w0_2_absI"]), "earlyWindow_0_2min_p95": eff(cold, "w0_2_p95", ["tmean", "w0_2_absI"]),
         "earlyWindow_2_10min_median": eff(cold, "w2_10_med", ["tmean", "w2_10_absI"]), "earlyWindow_2_10min_p95": eff(cold, "w2_10_p95", ["tmean", "w2_10_absI"]),
         "first20min_loaded_p95_allDrives": eff(f.assign(Tm=f["T"]), "first20_loaded_p95", ["Tm", "Imax"]),
         "first20min_loaded_p95_cold": eff(cold.assign(Tm=cold["T"]), "first20_loaded_p95", ["Tm", "Imax"]),
         "sensorResolution": "integer degC; a gradient below 1 degC is not resolvable; cell-level temperatures are not logged"}
    return o


def item_external(dm, dd, ext_dir, names):
    import compute_drive_summary_v6 as c
    X = sm.add_constant(dd[["T", "I", "soc"]]); m = sm.OLS(dd["y"], X).fit()
    rows = []
    for n in names:
        pth = os.path.join(ext_dir, n if n.endswith(".csv") else n + ".csv")
        b = open(pth, "rb").read()
        r = c.analyze_bytes(b, os.path.basename(pth))
        row = {"file": os.path.basename(pth), "sha256": sha256(pth), "I_sample_period_s": r.get("I_sample_period_s"), "regime": None if r.get("I_sample_period_s") is None else ("slow" if r["I_sample_period_s"] >= 1.05 else "fast"),
               "T": r.get(TCOL), "peak_I": r.get(ICOL), "soc": r.get("rf_socmean_wtd_pct"), "loaded_p95": r.get(YCOL), "n_loaded": r.get("n_loaded_spread_samples"), "mean_spread": r.get("cell_spread_mean_mv")}
        if None not in (row["T"], row["peak_I"], row["soc"]):
            row["modelResidual_mv"] = _r(((row["loaded_p95"] - float(m.predict([[1, row["T"], row["peak_I"], row["soc"]]])[0])) if row["loaded_p95"] is not None and row["loaded_p95"] == row["loaded_p95"] else np.nan), 2)
        rows.append(row)
    ok = [x for x in rows if x.get("n_loaded") and x["n_loaded"] >= 15 and x.get("modelResidual_mv") is not None]
    return {"status": "NOT INGESTED, descriptive only; never enters a fit or an interval", "residualModel": "y ~ T + I + soc on the master analysis frame (n=%d)" % len(dd), "files": rows,
            "summary_nLoadedGe15": {"n": len(ok), "residualMedian_mv": _r(np.median([x["modelResidual_mv"] for x in ok]), 2) if ok else None, "loadedP95Median_mv": _r(np.median([x["loaded_p95"] for x in ok]), 1) if ok else None},
            "modelResidualSD_mv": _r(np.sqrt(m.scale), 2)}


def _mean_resid_ci(res, groups):
    """Intercept-only OLS on the residuals, calendar-day cluster covariance, t(G-1) interval (the M574 estimator)."""
    G = int(len(set(groups)))
    r = sm.OLS(res, np.ones((len(res), 1))).fit(cov_type="cluster", cov_kwds={"groups": groups})
    tc = float(stats.t.ppf(0.975, G - 1)) if G > 1 else float(stats.norm.ppf(0.975))
    b, se = float(r.params[0]), float(r.bse[0])
    return b, [_r(b - tc * se, 3), _r(b + tc * se, 3)]


def confirmatory(dd, cutoff=CUTOFF, min_n=10, min_days=5, through=None):
    """Pre-registered confirmatory test (M573 Rev 2): drives dated after `cutoff` against the pre-step model (y ~ T + I + soc fitted on drives before STEP_DATE):
    mean residual with a day-clustered t(G-1) interval, and the post-step months slope. Evaluable only with >= min_n drives on >= min_days days."""
    if through is not None:
        dd = dd[dd["date"] <= pd.Timestamp(through)]
    post = dd[dd["date"] > pd.Timestamp(cutoff)]
    n, days = int(len(post)), int(post["day"].nunique())
    base = {"cutoff": cutoff, "stepDate": STEP_DATE, "minDrives": min_n, "minDays": min_days, "nDrivesAfterCutoff": n, "nDaysAfterCutoff": days}
    if n < min_n or days < min_days:
        return {**base, "status": "awaiting data", "note": "no number is given below the support floor"}
    pre = dd[dd["date"] < pd.Timestamp(STEP_DATE)]
    m = sm.OLS(pre["y"], sm.add_constant(pre[["T", "I", "soc"]])).fit()
    res = post["y"].values - m.predict(sm.add_constant(post[["T", "I", "soc"]], has_constant="add")).values
    b, lvl = _mean_resid_ci(res, post["day"].values)
    sl = fit_cluster(dd[dd["date"] >= pd.Timestamp(STEP_DATE)], ["months", "T", "I", "soc"])
    lvl_up, sl_zero, sl_up = lvl[0] > 0, sl["ci95"][0] <= 0 <= sl["ci95"][1], sl["ci95"][0] > 0
    label = "continued rise" if sl_up else ("raised level, flat slope" if (lvl_up and sl_zero) else ("back at pre-step level" if lvl[0] <= 0 <= lvl[1] else "mixed"))
    # M580 (spec Rev 1): additive caveat fields; every existing leaf above is unchanged
    tmin, tmax, p5 = float(pre["T"].min()), float(pre["T"].max()), float(np.percentile(pre["T"], 5))
    inr = post[(post["T"] >= tmin) & (post["T"] <= tmax)]
    i_n, i_days = int(len(inr)), int(inr["day"].nunique())
    meets = bool(i_n >= min_n and i_days >= min_days)
    ir = {"n": i_n, "days": i_days, "meetsSupportFloor": meets, "label": "post hoc sensitivity" if meets else "post hoc; below the floor", "meanResidualMv": None, "meanResidualCi95": None}
    if i_n >= 2 and i_days >= 2:
        ib, ici = _mean_resid_ci(inr["y"].values - m.predict(sm.add_constant(inr[["T", "I", "soc"]], has_constant="add")).values, inr["day"].values)
        ir["meanResidualMv"], ir["meanResidualCi95"] = _r(ib, 3), ici
    fit_hash = hashlib.sha256(json.dumps({"n": int(len(pre)), "coef": {k: round(float(v), 6) for k, v in m.params.items()}}, sort_keys=True).encode("utf-8")).hexdigest()
    return {**base, "status": "evaluated", "meanResidualMv": _r(b, 3), "meanResidualCi95": lvl, "postStepSlope": {k: sl[k] for k in ("est", "se", "ci95", "n", "G")}, "outcome": label,
            "preStepModel": {"n": int(len(pre)), "formula": "y ~ T + I + soc"},
            "predictionMet": bool(label == "raised level, flat slope"),
            "preStepTRange": {"min": _r(tmin, 2), "p5": _r(p5, 2), "max": _r(tmax, 2), "nFitDrives": int(len(pre))}, "preStepFitHash": fit_hash,
            "nBelowPreStepTmin": int((post["T"] < tmin).sum()), "nAbovePreStepTmax": int((post["T"] > tmax).sum()), "inRangeSensitivity": ir}


def terminal_day(dd, cutoff=CUTOFF):
    """First calendar day D with >= TERM_DRIVES in-range drives on >= TERM_DAYS distinct in-range days dated in (cutoff, D]; in-range = within the pre-step fit T range (strict bounds as in M580)."""
    pre = dd[dd["date"] < pd.Timestamp(STEP_DATE)]
    post = dd[dd["date"] > pd.Timestamp(cutoff)]
    inr = post[(post["T"] >= pre["T"].min()) & (post["T"] <= pre["T"].max())].sort_values("date")
    for d in sorted(inr["date"].unique()):
        s = inr[inr["date"] <= d]
        if len(s) >= TERM_DRIVES and s["day"].nunique() >= TERM_DAYS:
            return pd.Timestamp(d).strftime("%Y-%m-%d")
    return None


def apply_looks(conf, dd, dm_md5, path=None, write=True, spec_path=None):
    """M580 (spec Rev 1 R6/R7): evaluationNumber, lookLabel and terminalEvaluation from an append-only looks ledger keyed by the master MD5. Idempotent: the same master is never a second look; the terminal
    evaluation, once written, is frozen. A change of the pre-step fit (n or hash) STOPs for the Director."""
    path = path or LOOKS
    led = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {"schema": 1, "looks": [], "terminal": None, "preStepFit": None}
    conf = dict(conf)
    post = dd[dd["date"] > pd.Timestamp(conf["cutoff"])]
    pre = dd[dd["date"] < pd.Timestamp(STEP_DATE)]
    inr = post[(post["T"] >= pre["T"].min()) & (post["T"] <= pre["T"].max())]
    term_rule = ("terminal = first calendar day D after the cutoff %s with >= %d in-range drives on >= %d distinct in-range days (in-range = within the pre-step fit temperature range); "
                 "fallback: the drives dated <= %s; later looks are descriptive" % (conf["cutoff"], TERM_DRIVES, TERM_DAYS, TERM_FALLBACK))
    if conf["status"] != "evaluated":
        conf["terminalEvaluation"] = {"status": "not evaluable yet", "rule": term_rule}
        return conf, led
    fit = {"n": conf["preStepModel"]["n"], "hash": conf["preStepFitHash"]}
    if led["preStepFit"] is None:
        led["preStepFit"] = fit
    elif led["preStepFit"] != fit:
        raise SystemExit("STOP: the pre-step fit changed (n or coefficient hash): the M580 frozen fit is violated; Director")
    rec = next((x for x in led["looks"] if x["masterMd5"] == dm_md5), None)
    if rec is None:
        rec = {"masterMd5": dm_md5, "nDrivesFrame": int(len(dd)), "dataThrough": pd.Timestamp(dd["date"].max()).strftime("%Y-%m-%d"), "evaluationNumber": 1 + len(led["looks"]),
               "outcome": conf["outcome"], "nDrivesAfterCutoff": conf["nDrivesAfterCutoff"], "nDaysAfterCutoff": conf["nDaysAfterCutoff"]}
        led["looks"].append(rec)
    if led["terminal"] is None:
        D = terminal_day(dd, conf["cutoff"])
        through, how = D, "primary"
        if D is None and dd["date"].max() >= pd.Timestamp(TERM_FALLBACK):
            through, how = TERM_FALLBACK, "fallback"
        if through is not None:
            full = confirmatory(dd, conf["cutoff"], through=through)
            sha = hashlib.sha256(open(spec_path or os.path.join(ROOT, "analyses", "M580_spec.md"), "rb").read()).hexdigest()
            led["terminal"] = {"frozen": True, "rule": term_rule, "how": how, "D": D, "dataThrough": through, "evaluationNumber": rec["evaluationNumber"], "specSha256": sha,
                               "n": full["nDrivesAfterCutoff"], "days": full["nDaysAfterCutoff"], "outcome": full.get("outcome"),
                               "values": {k: full.get(k) for k in ("meanResidualMv", "meanResidualCi95", "postStepSlope", "predictionMet", "inRangeSensitivity", "nBelowPreStepTmin", "nAbovePreStepTmax")}}
    conf["evaluationNumber"] = rec["evaluationNumber"]
    t = led["terminal"]
    if t is None:
        conf["terminalEvaluation"] = {"status": "not reached", "rule": term_rule, "nInRangeDrives": int(len(inr)), "nInRangeDays": int(inr["day"].nunique()), "needDrives": TERM_DRIVES, "needDays": TERM_DAYS, "fallbackDate": TERM_FALLBACK}
        conf["lookLabel"] = ("first evaluation at the minimum support (%d days)" % conf["minDays"]) if (rec["evaluationNumber"] == 1 and conf["nDaysAfterCutoff"] == conf["minDays"]) else ("interim look %d; not the terminal evaluation" % rec["evaluationNumber"])
    else:
        conf["terminalEvaluation"] = t
        conf["lookLabel"] = ("terminal evaluation (data through %s)" % t["dataThrough"]) if rec["evaluationNumber"] == t["evaluationNumber"] else "after the terminal evaluation; descriptive"
    if write:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(led, f, indent=1)
    return conf, led


def build_block(out, conf, dm_md5):
    """Payload block cellSpreadStep from the analysis result (no external files, no free text beyond the declared statement)."""
    mod = out["item1_2_models"]
    keep = ("est", "se", "ci95", "n", "G", "aic", "cv_rmse_day_blocked", "formula", "step_term", "r2")
    models = {k: {x: v[x] for x in keep if x in v} for k, v in mod.items() if k != "changePointScan"}
    dep = out["item3_dependence"]
    win = out["analysisFrame"]["windowMonths"]
    m0, m2, m3, m5 = mod["M0_linear_released"], mod["M2_linear_soc_rest"], mod["M3_step"], mod["M5_step_soc_rest"]
    step_better = bool(m3["aic"] < m0["aic"] and m5["aic"] < m2["aic"] and m3["cv_rmse_day_blocked"] <= m0["cv_rmse_day_blocked"] and m5["cv_rmse_day_blocked"] <= m2["cv_rmse_day_blocked"])
    lo, hi = m5["ci95"]
    spans0 = bool(lo <= 0 <= hi)
    base = "degradation and real imbalance growth are neither established nor excluded; the cause is unidentified; the step size is conditional on a post hoc date and is not adjusted for selection."
    if step_better and spans0:
        st = f"Within the {win}-month window, a level shift around late September / early October (date chosen post hoc) fits better than a steady linear trend (model-derived); the steady trend is not established once the shift is allowed; " + base
    elif step_better:
        st = f"Within the {win}-month window, a level shift around late September / early October (date chosen post hoc) fits better than a steady linear trend (model-derived), and the months slope still excludes zero with the shift allowed; " + base
    else:
        st = f"Within the {win}-month window, the level-shift model does not fit better than the steady linear trend on both criteria (model-derived); " + base
    return {"_provenance": "GENERATED by tools/m573_cell_spread_step.py --splice (M574). Do not hand-edit.", "schemaVersion": 1, "stepPreferred": step_better, "monthsSlopeWithStepSpansZero": spans0, "statement": st,
            "stepDate": STEP_DATE, "stepDateNote": "chosen post hoc and fixed; never re-picked (M573 Rev 2)",
            "inputs": {"driveMasterMd5": dm_md5, "excludedFiles": "none: every file of the master listed in driveMasterMd5 enters this block (M575 corrected the earlier wording about the Nov 1-2 files, which are ingested since M575)"},
            "analysisFrame": out["analysisFrame"], "models": models, "changePointScan": mod["changePointScan"],
            "dependence": {k: dep[k] for k in ("weekCluster_linear", "weekCluster_step", "weekBlockBootstrap_linear", "weekBlockBootstrap_step", "leaveOneWeekOut_range", "dayMeanResidualAutocorrLag1")},
            "matchedContrast": out["item4_matched"], "cadence": out["item5_cadence"], "coldStartAndSegments": out.get("item4b_cold_start_and_segments"), "confirmatory": conf,
            "limits": ["step date chosen post hoc (the data-driven scan's best date is reported); AIC and intervals ignore date selection and multiplicity",
                       "residual lag-1 autocorrelation about 0.27; the late window is 8 days and the week-cluster count is small",
                       "month fixed effects fit as well as the step, so a single October step is not uniquely supported",
                       "cold-start early-window intervals are wide: not detected, not excluded", "the polling regime is reported with the step, not excluded",
                       "cell-level temperatures are not logged; the four pack sensors are integer degC", "one half-season only; a return to the same temperature in spring is not observed",
                       "model-derived association: no capacity, state-of-health or cell-deterioration quantity is estimated"]}


def splice(block):
    """additive write of S.cellSpreadStep (+ stamp); no existing key and no other stamp changes."""
    block = json.loads(json.dumps(block, default=float))
    A2 = json.load(open(ARR, encoding="utf-8"))
    skip = ("cellSpreadStep", "_artifactStamps")
    before = {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    stamps_before = {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "cellSpreadStep"}
    A2["cellSpreadStep"] = block
    st = copy.deepcopy(A2["_artifactStamps"]["fuelContract"])
    st.update(corpusHash=block["inputs"]["driveMasterMd5"], generatedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), computationStatus="computed",
              computationStatusNote="M574: computed by tools/m573_cell_spread_step.py from the master and the raw CSVs; additive, no published value recomputed; not M299-reproducible.", upstreamHashes={"driveMasterMd5": block["inputs"]["driveMasterMd5"]})
    st.pop("carriedForward", None)
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A2["_artifactStamps"]["cellSpreadStep"] = st
    assert before == {k: json.dumps(v, sort_keys=True) for k, v in A2.items() if k not in skip}
    assert stamps_before == {k: json.dumps(v, sort_keys=True) for k, v in A2["_artifactStamps"].items() if k != "cellSpreadStep"}
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A2, f, ensure_ascii=False, indent=1)
    print(json.dumps({"cellSpreadStep": "written"}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-raw", action="store_true")
    ap.add_argument("--splice", action="store_true", help="M574: also write the additive payload block (never with --external)")
    ap.add_argument("--raw-dir", default=os.path.join(ROOT, "raw"))
    ap.add_argument("--external", nargs="*", default=None, help="DIR followed by file names (with or without .csv)")
    ap.add_argument("--out", default=os.path.join(ROOT, "analyses", "M573_step_vs_trend.json"))
    a = ap.parse_args()
    mpath = os.path.join(ROOT, "drive_master.csv")
    md5_before = md5(mpath)
    dm = pd.read_csv(mpath)
    d = build_frame(dm)
    models, dd = item_models(d)
    out = {"milestone": "M573", "spec": "analyses/M573_spec.md Rev 1", "masterMd5": md5_before, "masterRows": int(len(dm)), "analysisFrame": {"n": int(len(dd)), "days": int(dd["day"].nunique()), "firstDate": str(dd["date"].min().date()), "lastDate": str(dd["date"].max().date()),
           "stepDate": STEP_DATE, "windowMonths": _r(dd["months"].max(), 2)},
           "item1_2_models": models, "item3_dependence": item_dependence(dd), "item4_matched": item_matched(dd), "item5_cadence": item_cadence(dm, dd)}
    if not a.skip_raw:
        out["item4b_cold_start_and_segments"] = item_cold_and_segments(dm, d, a.raw_dir)
    out["confirmatory"] = confirmatory(dd)
    if a.splice and not a.external:
        out["confirmatory"], _ = apply_looks(out["confirmatory"], dd, md5_before)      # M580: looks ledger (idempotent per master MD5)
    if a.splice and a.external:
        sys.exit("STOP: --splice never takes external files")
    if a.external:
        out["item7_external"] = item_external(dm, dd, a.external[0], a.external[1:])
    assert md5(mpath) == md5_before, "drive_master.csv changed: STOP"
    out["masterMd5After"] = md5(mpath)
    if a.splice:
        a.out = os.path.join(ROOT, "analyses", "M574_check.json")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print("wrote", a.out)
    if a.splice:
        splice(build_block(out, out["confirmatory"], out["masterMd5After"]))


if __name__ == "__main__":
    main()
