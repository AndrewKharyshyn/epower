#!/usr/bin/env python3
"""M603 (analyses/M603_spec.md Rev 1): steady-load (low-slew) cell-spread drift, a measurement-design robustness check of the released loaded cell-spread slope.
Per drive, on the pipeline's own paired frame (Vcell_max/Vcell_min nearest-paired within SPREAD_TOL, current as-of aligned within V_ALIGN_TOL):
  loaded  = |I| > 50 A (the pipeline selection; must reconcile with cell_spread_loaded_p95_mv, zero tolerance after round(., 1));
  steady  = 30 <= |I| <= 100 A and local slew <= 3 A/s (bracket of native current samples around the pair midpoint, gap <= 2 s);
  sensitivities: fixed-window slew (range of native I within t +/- 1 s <= 3 A), 20-pair seeded subsample p95, pairing-lag cap 0.2 s, interpolated min-cell pairing.
Sidecars steady_load_spread.csv (per drive) and steady_load_contexts.csv (per drive x context) are written ONLY by this tool; drive_master.csv is read-only.
Usage: python tools/steady_load_spread.py [--rebuild] [--check] [--out analyses/M603_result.json] [--draws N]"""
import hashlib, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (ROOT, os.path.join(ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
SIDECAR = os.path.join(ROOT, "steady_load_spread.csv")
CTX_SIDECAR = os.path.join(ROOT, "steady_load_contexts.csv")
METHOD_VERSION = 1
I_LO, I_HI, SLEW_MAX, GAP_MAX_S = 30.0, 100.0, 3.0, 2.0
WIN_S, WIN_RANGE_A, LAG_CAP_S, SUBSAMPLE_N = 1.0, 3.0, 0.2, 20
FLOOR_PAIRS, CTX_FLOOR_PAIRS = 20, 10
COLS = ["file", "date", "n_pairs_loaded", "p95_loaded_mv", "n_steady", "p95_steady_mv", "n_fixedwin", "p95_fixedwin_mv", "p95_steady_n20_mv",
        "n_lag", "p95_lag_mv", "n_interp", "p95_interp_mv", "raw_sha256", "method_version", "reason"]
CTX_COLS = ["file", "date", "t1bin", "socbin", "iband", "n", "p95"]
NUMC = [c for c in COLS if c.startswith(("n_", "p95_"))]
STEP_DATE, PID_DATE = "2026-10-01", "2026-11-03"
SEED, DRAWS = 42, 4000
SUPPORT_DRIVES, SUPPORT_DAYS = 40, 15          # spec section 6 of Rev 1 (overall)
STRAT_DRIVES, STRAT_DAYS = 20, 8               # E4 per-stratum floor
CTX_MIN_DRIVES, CTX_MIN_DAYS = 5, 3            # E5 common-context rule per side


# ---------------------------------------------------------------- selection (pure, unit-tested)
def steady_mask(abs_I, tm_ns, tI_ns, vI, lo=I_LO, hi=I_HI, slew_max=SLEW_MAX, gap_max=GAP_MAX_S):
    """Pair qualifies when lo <= |I| <= hi and the slew of the bracket (last native sample at or before tm, first strictly after) is <= slew_max A/s
    with a bracket gap in (0, gap_max]. Duplicate native timestamps are dropped (first kept). Undefined slew -> False."""
    abs_I = np.asarray(abs_I, dtype=float); tm_ns = np.asarray(tm_ns, dtype=np.int64)
    tI_ns = np.asarray(tI_ns, dtype=np.int64); vI = np.asarray(vI, dtype=float)
    keep = np.r_[True, np.diff(tI_ns) != 0] if len(tI_ns) else np.zeros(0, bool)
    tI_ns, vI = tI_ns[keep], vI[keep]
    band = (abs_I >= lo) & (abs_I <= hi)
    if len(tI_ns) < 2:
        return np.zeros(len(abs_I), bool)
    nxt = np.searchsorted(tI_ns, tm_ns, side="right")
    prv = nxt - 1
    ok = (prv >= 0) & (nxt < len(tI_ns))
    p, n = np.clip(prv, 0, len(tI_ns) - 1), np.clip(nxt, 0, len(tI_ns) - 1)
    dt = (tI_ns[n] - tI_ns[p]) / 1e9
    with np.errstate(divide="ignore", invalid="ignore"):
        slew = np.abs(vI[n] - vI[p]) / dt
    ok &= (dt > 0) & (dt <= gap_max) & np.isfinite(slew) & (slew <= slew_max)
    return band & ok


def fixed_window_mask(abs_I, tm_ns, tI_ns, vI, lo=I_LO, hi=I_HI, win_s=WIN_S, rng_a=WIN_RANGE_A):
    """Sensitivity: at least 2 native current samples in [tm - win_s, tm + win_s] and their range <= rng_a."""
    abs_I = np.asarray(abs_I, dtype=float); tm_ns = np.asarray(tm_ns, dtype=np.int64)
    tI_ns = np.asarray(tI_ns, dtype=np.int64); vI = np.asarray(vI, dtype=float)
    out = np.zeros(len(abs_I), bool)
    band = (abs_I >= lo) & (abs_I <= hi)
    w = int(win_s * 1e9)
    lo_i = np.searchsorted(tI_ns, tm_ns - w, side="left"); hi_i = np.searchsorted(tI_ns, tm_ns + w, side="right")
    for k in np.flatnonzero(band & (hi_i - lo_i >= 2)):
        seg = vI[lo_i[k]:hi_i[k]]
        out[k] = (seg.max() - seg.min()) <= rng_a
    return out


def p95(x):
    x = np.asarray(x, dtype=float)
    return float(pd.Series(x).quantile(0.95)) if len(x) else None


def iband(i):
    """Signed 20 A band index inside 30-100 A: +1..+4 for [30,50) [50,70) [70,90) [90,100]; -1..-4 mirrored; 0 outside."""
    a = abs(i)
    if a < I_LO or a > I_HI:
        return 0
    b = min(int((a - 30.0) // 20.0) + 1, 4)
    return b if i > 0 else -b


# ---------------------------------------------------------------- extraction
def extract_from_bytes(csv_bytes, name=""):
    import compute_drive_summary_v6 as D
    out = {c: None for c in COLS}
    out["reason"] = None
    ctx = []
    df, t = D._prep_bytes(csv_bytes)
    I = D._series(df, t, "I")
    if I is not None:
        I = I[I["v"].abs() < 900]
    vmax = D._series(df, t, "Vcell_max", lo=2.0, hi=5.0); vmin = D._series(df, t, "Vcell_min", lo=2.0, hi=5.0)
    if vmax is None or vmin is None or I is None:
        out["reason"] = "no_spread_or_current_series"
        return out, ctx
    vmn = vmin.rename(columns={"v": "vmin"}); vmn["tmin"] = vmn["t"]
    p = pd.merge_asof(vmax.rename(columns={"v": "vmax"}), vmn, on="t", direction="nearest", tolerance=pd.Timedelta(D.SPREAD_TOL)).dropna().reset_index(drop=True)
    if not len(p):
        out["reason"] = "no_paired_pairs"
        return out, ctx
    p["spread_mv"] = (p["vmax"] - p["vmin"]) * 1000.0
    p2 = D._asof(p, I, "I", D.V_ALIGN_TOL)
    sp = p2["spread_mv"].to_numpy(); Iv = p2["I"].to_numpy(dtype=float)
    loaded = np.abs(Iv) > 50                       # NaN -> False, as the pipeline's .abs() > 50
    out["n_pairs_loaded"] = int(loaded.sum())
    if loaded.any():
        out["p95_loaded_mv"] = p95(sp[loaded])
    tI = I["t"].astype("datetime64[ns]").astype("int64").to_numpy(); vI = I["v"].to_numpy(dtype=float)
    tm = (p2["t"].astype("datetime64[ns]").astype("int64").to_numpy() + p2["tmin"].astype("datetime64[ns]").astype("int64").to_numpy()) // 2
    absI = np.abs(Iv)
    st = steady_mask(absI, tm, tI, vI)
    out["n_steady"] = int(st.sum())
    if st.any():
        out["p95_steady_mv"] = p95(sp[st])
    fw = fixed_window_mask(absI, tm, tI, vI)
    out["n_fixedwin"] = int(fw.sum())
    if fw.any():
        out["p95_fixedwin_mv"] = p95(sp[fw])
    if st.sum() >= SUBSAMPLE_N:
        seed = (int(hashlib.sha1(name.encode()).hexdigest()[:8], 16) ^ SEED) & 0x7FFFFFFF
        pick = np.random.default_rng(seed).choice(np.flatnonzero(st), SUBSAMPLE_N, replace=False)
        out["p95_steady_n20_mv"] = p95(sp[pick])
    lag = np.abs(p2["t"].astype("datetime64[ns]").astype("int64").to_numpy() - p2["tmin"].astype("datetime64[ns]").astype("int64").to_numpy()) / 1e9 <= LAG_CAP_S
    ml = st & lag
    out["n_lag"] = int(ml.sum())
    if ml.any():
        out["p95_lag_mv"] = p95(sp[ml])
    # interpolated min-cell pairing at the max-cell time (bracket gap <= GAP_MAX_S), on the steady pairs
    tmin_s = vmin["t"].astype("datetime64[ns]").astype("int64").to_numpy(); vmin_v = vmin["v"].to_numpy(dtype=float)
    tt = p2["t"].astype("datetime64[ns]").astype("int64").to_numpy()
    j = np.searchsorted(tmin_s, tt, side="right")
    okj = (j > 0) & (j < len(tmin_s))
    jj = np.clip(j, 1, len(tmin_s) - 1)
    gap = (tmin_s[jj] - tmin_s[jj - 1]) / 1e9
    okj &= (gap > 0) & (gap <= GAP_MAX_S)
    w = (tt - tmin_s[jj - 1]) / np.maximum(tmin_s[jj] - tmin_s[jj - 1], 1)
    vint = vmin_v[jj - 1] + w * (vmin_v[jj] - vmin_v[jj - 1])
    spi = (p2["vmax"].to_numpy() - vint) * 1000.0
    mi = st & okj
    out["n_interp"] = int(mi.sum())
    if mi.any():
        out["p95_interp_mv"] = p95(spi[mi])
    # contexts (steady pairs): T1 5 degC bin x SoC 10-point bin x signed 20 A band
    T1 = D._series(df, t, "T1", lo=-40, hi=90); soc = D._series(df, t, "soc")
    if st.any() and T1 is not None and soc is not None:
        q = D._asof(D._asof(p2.loc[st, ["t", "spread_mv", "I"]].reset_index(drop=True), T1, "T1", "3s"), soc, "soc", D.V_ALIGN_TOL).dropna(subset=["T1", "soc"])
        if len(q):
            q = q.assign(t1bin=(np.floor(q["T1"] / 5.0) * 5).astype(int), socbin=np.minimum(np.floor(q["soc"] / 10.0) * 10, 90).astype(int),
                         iband=q["I"].map(iband))
            for (a, b, c), g in q.groupby(["t1bin", "socbin", "iband"]):
                if len(g) >= CTX_FLOOR_PAIRS:
                    ctx.append({"t1bin": int(a), "socbin": int(b), "iband": int(c), "n": int(len(g)), "p95": p95(g["spread_mv"])})
    return out, ctx


def build_sidecars(master, loader, rebuild=False):
    old, oldc = {}, {}
    if os.path.exists(SIDECAR) and os.path.exists(CTX_SIDECAR) and not rebuild:
        o = pd.read_csv(SIDECAR, dtype={"raw_sha256": str}, keep_default_na=False, na_values=[""], float_precision="round_trip")
        old = {r["file"]: r for r in o.to_dict("records")}
        c = pd.read_csv(CTX_SIDECAR, keep_default_na=False, na_values=[""], float_precision="round_trip")
        oldc = {f: g.to_dict("records") for f, g in c.groupby("file")}
    rows, crows = [], []
    for _, m in master.iterrows():
        f, date = str(m["file"]), str(m["date"])
        b = loader(f)
        if b is None:
            r = {k: None for k in COLS}; r.update(file=f, date=date, reason="raw_file_missing", method_version=METHOD_VERSION)
            rows.append(r); continue
        h = hashlib.sha256(b).hexdigest()
        prev = old.get(f)
        if prev is not None and prev.get("raw_sha256") == h and prev.get("method_version") == METHOD_VERSION:
            rows.append({k: (None if pd.isna(prev.get(k)) else prev.get(k)) for k in COLS}); crows.extend(oldc.get(f, [])); continue
        res, ctx = extract_from_bytes(b, f)
        r = dict(res); r.update(file=f, date=date, raw_sha256=h, method_version=METHOD_VERSION)
        rows.append(r)
        crows.extend({"file": f, "date": date, **c} for c in ctx)
    out = pd.DataFrame(rows, columns=COLS)
    for c in NUMC:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out.to_csv(SIDECAR, index=False, lineterminator="\n")
    pd.DataFrame(crows, columns=CTX_COLS).to_csv(CTX_SIDECAR, index=False, lineterminator="\n")
    return load_sidecars()


def load_sidecars():
    s = pd.read_csv(SIDECAR, dtype={"raw_sha256": str}, keep_default_na=False, na_values=[""], float_precision="round_trip")
    c = pd.read_csv(CTX_SIDECAR, keep_default_na=False, na_values=[""], float_precision="round_trip")
    return s, c


def reconcile(side, master):
    """Zero tolerance after round(., 1): loaded p95 and pair count equal the master's cell_spread_loaded_p95_mv / n_loaded_spread_samples."""
    mm = master.set_index("file"); s = side.set_index("file")
    bad_p, bad_n, n = [], [], 0
    for f in s.index:
        if f not in mm.index or pd.isna(mm.loc[f, "cell_spread_loaded_p95_mv"]):
            continue
        n += 1
        if pd.isna(s.loc[f, "p95_loaded_mv"]) or float(round(np.float64(s.loc[f, "p95_loaded_mv"]), 1)) != float(round(np.float64(mm.loc[f, "cell_spread_loaded_p95_mv"]), 1)):   # numpy rounding, as the pipeline rounds a numpy float
            bad_p.append(f)
        if pd.isna(s.loc[f, "n_pairs_loaded"]) or int(s.loc[f, "n_pairs_loaded"]) != int(mm.loc[f, "n_loaded_spread_samples"]):
            bad_n.append(f)
    return {"rows_equal_to_master": list(side["file"]) == list(master["file"]), "n_compared": n, "mismatch_p95": bad_p, "mismatch_n": bad_n,
            "n_raw_missing": int((side["reason"] == "raw_file_missing").sum()), "ok": bool(list(side["file"]) == list(master["file"]) and not bad_p and not bad_n)}


# ---------------------------------------------------------------- statistics
def theil_sen(x, y):
    """Median of pairwise slopes over pairs with distinct x; None when no pair."""
    x = np.asarray(x, dtype=float); y = np.asarray(y, dtype=float)
    i, j = np.triu_indices(len(x), 1)
    dx = x[j] - x[i]
    ok = dx > 0
    # pairs with dx < 0 cannot occur for sorted x; resampled duplicates give dx == 0 and are skipped
    if not ok.any():
        return None
    return float(np.median((y[j] - y[i])[ok] / dx[ok]))


def day_table(d, ycol):
    g = d.dropna(subset=[ycol]).groupby("day").agg(x=("months", "mean"), y=(ycol, "median"), wk=("wk", "first"), n=(ycol, "size")).sort_values("x").reset_index()
    return g


def _ts_boot(g, unit, draws, seed=SEED):
    """Theil-Sen of day medians; percentile interval with `unit` ('day' or 'wk') as the resampling cluster."""
    rng = np.random.default_rng(seed)
    x, y = g["x"].to_numpy(), g["y"].to_numpy()
    est = theil_sen(x, y)
    if unit == "day":
        idx = [np.array([k]) for k in range(len(g))]
    else:
        idx = [np.flatnonzero(g["wk"].to_numpy() == w) for w in g["wk"].unique()]
    m = len(idx)
    out = []
    for _ in range(draws):
        pick = rng.integers(0, m, m)
        sel = np.concatenate([idx[k] for k in pick])
        v = theil_sen(x[sel], y[sel])
        if v is not None:
            out.append(v)
    out = np.asarray(out)
    return est, float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5)), int(len(out))


def e1(d, ycol, draws=DRAWS):
    g = day_table(d, ycol)
    if len(g) < 3:
        return {"nDrives": int(d[ycol].notna().sum()), "nDays": int(len(g)), "est": None}
    est, lo, hi, nb = _ts_boot(g, "day", draws)
    _, wlo, whi, _ = _ts_boot(g, "wk", draws)
    return {"est": round(est, 4), "ci95Day": [round(lo, 4), round(hi, 4)], "ci95Week": [round(wlo, 4), round(whi, 4)], "nDrives": int(d[ycol].notna().sum()), "nDays": int(len(g)),
            "nWeeks": int(g["wk"].nunique())}


def e2b(d, ycol):
    """Released model y ~ months + T + I with the released cluster protocol (statsmodels cluster covariance, t(G-1)); CR2 beside it."""
    import m573_cell_spread_step as m573, dependence_sensitivity as ds
    from scipy import stats
    dd = d.dropna(subset=[ycol]).copy(); dd["y"] = dd[ycol].astype(float)
    r = m573.fit_cluster(dd, ["months", "T", "I"], ycol="y")
    X = np.c_[np.ones(len(dd)), dd[["months", "T", "I"]].to_numpy(dtype=float)]
    b, se, df, _ = ds.cr2(X, dd["y"].to_numpy(dtype=float), dd["day"].to_numpy(), 1)
    tc = float(stats.t.ppf(0.975, df)) if np.isfinite(df) and df > 1 else float("nan")
    r["cr2"] = {"est": round(b, 4), "se": round(se, 4), "df": round(df, 2), "ci95": [round(b - tc * se, 4), round(b + tc * se, 4)]}
    r["halfWidth"] = round((r["ci95"][1] - r["ci95"][0]) / 2, 4)
    r["mde80"] = round(2.8 * r["se"], 4)
    return r


def paired_difference(d, y_steady, y_loaded, draws=DRAWS):
    """D = slope(steady) - slope(loaded) from the same drives and the same OLS (months + T + I); day-clustered pairs bootstrap."""
    dd = d.dropna(subset=[y_steady, y_loaded]).copy()
    X = np.c_[np.ones(len(dd)), dd[["months", "T", "I"]].to_numpy(dtype=float)]
    Y = dd[[y_steady, y_loaded]].to_numpy(dtype=float)
    beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    est = float(beta[1, 0] - beta[1, 1])
    days = dd["day"].to_numpy()
    uniq = pd.unique(days); rows = {u: np.flatnonzero(days == u) for u in uniq}
    rng = np.random.default_rng(SEED)
    out = []
    for _ in range(draws):
        sel = np.concatenate([rows[u] for u in uniq[rng.integers(0, len(uniq), len(uniq))]])
        bb = np.linalg.lstsq(X[sel], Y[sel], rcond=None)[0]
        out.append(bb[1, 0] - bb[1, 1])
    out = np.asarray(out)
    return {"est": round(est, 4), "ci95": [round(float(np.percentile(out, 2.5)), 4), round(float(np.percentile(out, 97.5)), 4)], "nDrives": int(len(dd)), "nDays": int(len(uniq)),
            "slopeSteady": round(float(beta[1, 0]), 4), "slopeLoaded": round(float(beta[1, 1]), 4)}


def grade(steady, loaded, diff):
    """Spec Rev 1 section 0.5. steady/loaded: e2b dicts (ci95, est, halfWidth); diff: paired_difference dict. Order matters."""
    if steady["halfWidth"] > abs(loaded["est"]):
        return "UNINFORMATIVE"
    s_lo, s_hi = steady["ci95"]; l_lo, l_hi = loaded["ci95"]
    d_lo, d_hi = diff["ci95"]
    overlap = s_lo <= l_hi and l_lo <= s_hi
    if d_lo <= 0 <= d_hi and overlap:
        return "CONSISTENT"
    if diff["est"] < 0 and d_hi < 0:
        return "ARTEFACT-SUPPORTED" if s_lo <= 0 <= s_hi else "ATTENUATED"
    return "UNDECIDED"


def analysis_frame(master, side, ycols, floor=FLOOR_PAIRS, nfloor_col="n_steady", pcol="p95_steady_mv", exclude_after=None):
    import m573_cell_spread_step as m573
    d = m573.build_frame(master)
    s = side.set_index("file")
    d["y_loaded"] = d["file"].map(s["p95_loaded_mv"])
    d["y_steady"] = d["file"].map(s[pcol]).where(d["file"].map(s[nfloor_col]).ge(floor))
    if exclude_after:
        d = d[d["date"] < pd.Timestamp(exclude_after)]
    return d


def view(d, draws):
    both = d.dropna(subset=["y_steady", "y_loaded"])
    r = {"steadyTheilSen": e1(d, "y_steady", draws), "loadedTheilSen": e1(both, "y_loaded", draws), "steadyModel": e2b(d, "y_steady"), "loadedModel": e2b(both, "y_loaded"),
         "difference": paired_difference(d, "y_steady", "y_loaded", draws)}
    r["grade"] = grade(r["steadyModel"], r["loadedModel"], r["difference"])
    return r


def strata(d, draws):
    out = {}
    cuts = {"fast": d["slow"] == 0, "slow": d["slow"] == 1, "beforeStep": d["date"] < pd.Timestamp(STEP_DATE), "fromStep": d["date"] >= pd.Timestamp(STEP_DATE)}
    for k, m in cuts.items():
        g = d[m].dropna(subset=["y_steady"])
        nd, ndays = len(g), g["day"].nunique()
        if nd < STRAT_DRIVES or ndays < STRAT_DAYS:
            out[k] = {"nDrives": int(nd), "nDays": int(ndays), "reported": False, "note": "not reported (support)"}
        else:
            out[k] = {"reported": True, **e1(g, "y_steady", draws)}
    return out


def contexts(master, side, ctx, draws):
    """E5 matched contexts, split at STEP_DATE inside each cadence stratum; descriptive count plus a day-clustered bootstrap of the median difference."""
    import m573_cell_spread_step as m573
    d = m573.build_frame(master)[["file", "day", "date", "slow"]]
    c = ctx.merge(d, on="file", how="inner")
    c = c[c["n"] >= CTX_FLOOR_PAIRS].copy()
    c["late"] = (pd.to_datetime(c["date_x"]) >= pd.Timestamp(STEP_DATE)).astype(int)
    keys = ["slow", "t1bin", "socbin", "iband"]
    common = []
    for k, g in c.groupby(keys):
        e, l = g[g["late"] == 0], g[g["late"] == 1]
        if len(e) >= CTX_MIN_DRIVES and e["day"].nunique() >= CTX_MIN_DAYS and len(l) >= CTX_MIN_DRIVES and l["day"].nunique() >= CTX_MIN_DAYS:
            common.append(k)
    if not common:
        return {"nCommon": 0, "note": "no common context"}
    cm = pd.DataFrame(common, columns=keys).assign(cid=range(len(common)))
    cc = c.merge(cm, on=keys, how="inner")
    diffs = cc.groupby(["cid", "late"])["p95"].median().unstack()
    dif = (diffs[1] - diffs[0]).to_numpy()
    res = {"nCommon": int(len(common)), "nPositive": int((dif > 0).sum()), "medianDifferenceMv": round(float(np.median(dif)), 3), "contextKeys": keys,
           "floors": {"drivesPerSide": CTX_MIN_DRIVES, "daysPerSide": CTX_MIN_DAYS, "pairsPerDriveContext": CTX_FLOOR_PAIRS}, "label": "conditional on a post hoc split date (2026-10-01, M573)"}
    days = cc["day"].to_numpy(); uniq = pd.unique(days)
    rows = {u: np.flatnonzero(days == u) for u in uniq}
    cid, late, val = cc["cid"].to_numpy(), cc["late"].to_numpy(), cc["p95"].to_numpy()
    rng = np.random.default_rng(SEED)
    meds = []
    for _ in range(draws):
        sel = np.concatenate([rows[u] for u in uniq[rng.integers(0, len(uniq), len(uniq))]])
        dd = []
        for k in range(len(common)):
            m = cid[sel] == k
            e, l = val[sel][m & (late[sel] == 0)], val[sel][m & (late[sel] == 1)]
            if len(e) and len(l):
                dd.append(np.median(l) - np.median(e))
        if dd:
            meds.append(np.median(dd))
    meds = np.asarray(meds)
    res["medianDifferenceCi95Day"] = [round(float(np.percentile(meds, 2.5)), 3), round(float(np.percentile(meds, 97.5)), 3)]
    return res


def qualifying_share(master, side):
    import m573_cell_spread_step as m573
    d = m573.build_frame(master)[["file", "date", "slow"]].merge(side[["file", "n_pairs_loaded", "n_steady"]], on="file")
    d["month"] = d["date"].dt.strftime("%Y-%m")
    g = d.groupby(["slow", "month"])[["n_steady", "n_pairs_loaded"]].sum()
    g["share"] = (g["n_steady"] / g["n_pairs_loaded"]).round(4)
    return {f"{'slow' if s else 'fast'}|{m}": {"qualifying": int(r.n_steady), "loaded": int(r.n_pairs_loaded), "share": float(r.share)} for (s, m), r in g.iterrows()}


def run(master, side, ctx, draws=DRAWS):
    d = analysis_frame(master, side, None)
    support = d.dropna(subset=["y_steady"])
    res = {"specRev": "analyses/M603_spec.md Rev 1", "methodVersion": METHOD_VERSION, "bootstrap": {"unit": "calendar day (E3 week)", "draws": draws, "seed": SEED, "ci": "percentile 95%"},
           "population": {"canonicalCleanDrives": int(len(d)), "withSteadyS": int(len(support)), "days": int(support["day"].nunique()),
                          "lostToFloor": int((d["file"].map(side.set_index("file")["n_steady"]).fillna(0) < FLOOR_PAIRS).sum()),
                          "supportMet": bool(len(support) >= SUPPORT_DRIVES and support["day"].nunique() >= SUPPORT_DAYS)},
           "releasedReference": {"slope": 0.7396, "ci95": [0.4128, 1.0665], "nObs": 600, "nDays": 122, "masterMd5": "1574a8156a36c6ea4ea1dfdaafc7cc72"}}
    res["primary"] = view(d, draws)
    res["strata"] = strata(d, draws)
    res["matchedContexts"] = contexts(master, side, ctx, draws)
    res["qualifyingShare"] = qualifying_share(master, side)
    # sensitivities (report, do not tune)
    sens = {}
    for name, kw in {"floor10": dict(floor=10), "floor40": dict(floor=40), "fixedWindowSlew": dict(pcol="p95_fixedwin_mv", nfloor_col="n_fixedwin"),
                     "subsample20": dict(pcol="p95_steady_n20_mv", nfloor_col="n_steady"), "lagCap0.2s": dict(pcol="p95_lag_mv", nfloor_col="n_lag"),
                     "interpolatedPairing": dict(pcol="p95_interp_mv", nfloor_col="n_interp")}.items():
        sens[name] = view(analysis_frame(master, side, None, **kw), draws)
    nopid = analysis_frame(master, side, None, exclude_after=PID_DATE)
    sens["withoutFrom2026-11-03"] = view(nopid, draws)
    res["sensitivity"] = sens
    res["pidSetCheck"] = {"gradeWith": res["primary"]["grade"], "gradeWithout": sens["withoutFrom2026-11-03"]["grade"]}
    res["finalGrade"] = res["primary"]["grade"] if res["pidSetCheck"]["gradeWith"] == res["pidSetCheck"]["gradeWithout"] else "UNDECIDED"
    wk = d.dropna(subset=["y_steady"])["wk"].unique()
    loo = [e2b(d[d["wk"] != w], "y_steady")["est"] for w in wk]
    res["leaveOneWeekOut"] = {"min": round(min(loo), 4), "max": round(max(loo), 4), "nWeeks": int(len(wk))}
    res["basis"] = "raw/ = sha256-verified originals (M366)"
    return res


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    master = pd.read_csv("drive_master.csv", low_memory=False)
    draws = int(argv[argv.index("--draws") + 1]) if "--draws" in argv else DRAWS
    if "--check" in argv:
        side, ctx = load_sidecars()
        rc = reconcile(side, master)
        print(json.dumps({"check": "steadyLoadSpread", "reconciliationOk": rc["ok"], "nCompared": rc["n_compared"]}))
        return 0 if rc["ok"] else 1
    from ah_throughput import raw_loader
    side, ctx = build_sidecars(master, raw_loader(), rebuild="--rebuild" in argv)
    rc = reconcile(side, master)
    print(json.dumps({k: (rc[k] if not isinstance(rc[k], list) else len(rc[k])) for k in rc}))
    if not rc["ok"]:
        return 1
    out = argv[argv.index("--out") + 1] if "--out" in argv else "analyses/M603_result.json"
    res = run(master, side, ctx, draws)
    res["reconciliation"] = {"nCompared": rc["n_compared"], "mismatchP95": 0, "mismatchN": 0}
    res["sidecars"] = {"steady_load_spread.csv": hashlib.sha256(open(SIDECAR, "rb").read()).hexdigest(), "steady_load_contexts.csv": hashlib.sha256(open(CTX_SIDECAR, "rb").read()).hexdigest(),
                       "masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()}
    json.dump(res, open(out, "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False)
    print("wrote", out, "grade", res["finalGrade"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
