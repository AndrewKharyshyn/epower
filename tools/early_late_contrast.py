#!/usr/bin/env python3
"""M678 (N-04, spec analyses/M677_spec.md Rev 1.1 and 1.2): exploratory early-versus-late contrast of three outcomes inside matched state cells. Reads drive_master.csv and two sidecars (read-only), writes the
additive payload block summary_arrays.json['earlyLateContrast'] (+ stamp). Path A: coarsened exact matching (covariate-only granularity ladder), late-count-weighted difference, day-clustered bootstrap with fixed cells
(seed 42, 4000 draws). Path B: OLS with day-cluster CR1 errors and t(G-1). Descriptive, not an M622 look, no equivalence verdict, no alpha spent.
Usage: python tools/early_late_contrast.py [--out PATH] [--nboot N]"""
import copy, datetime, hashlib, json, os, sys
import numpy as np
import pandas as pd
from scipy import stats

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
KEY = "earlyLateContrast"
SEED, NBOOT = 42, 4000
MIN_CELL, MIN_CELL_DAYS = 3, 2
SHOW_DRIVES, SHOW_DAYS = 10, 5
UPDATE_DATE = "2026-08-25"
LEVELS = [{"name": "5x5x4x2", "nT": 5, "nI": 5, "nS": 4}, {"name": "3x3x3x2", "nT": 3, "nI": 3, "nS": 3}]
DIST_EDGES = [-1, 5, 25, 9999]
ALPHA_BONF = 0.05 / 3
OUTCOMES = {
    "Y1": ("resistance proxy a1_R (model-derived), drives with a1_n >= 600", "resistance_joint_sidecar.csv:a1_R"),
    "Y2": ("loaded p95 cell spread (mV)", "master:cell_spread_loaded_p95_mv"),
    "Y3": ("median pack voltage V_pack_median (V); cap_ah_est is 2.1 kWh divided by this value, a voltage proxy and not a capacity", "master:V_pack_median"),
}
FROZEN_PATH = os.path.join(ROOT, "analyses", "M678_frozen_windows.json")


# ------------------------------------------------------------ data
def load(root=ROOT, master_path=None):
    m = pd.read_csv(master_path or os.path.join(root, "drive_master.csv"), low_memory=False)
    m = m[m["ens_outlier_v2"] == False].copy()                                 # noqa: E712
    res = pd.read_csv(os.path.join(root, "resistance_joint_sidecar.csv")).set_index("file")
    cad = pd.read_csv(os.path.join(root, "cadence_regime.csv")).set_index("file")
    d = pd.DataFrame({"file": m["file"].values, "date": pd.to_datetime(m["date"]).values, "T": m["T_pack_mean_avg"].astype(float).values,
                      "I": m["peak_I_discharge"].astype(float).values, "S": m["rf_socmean_wtd_pct"].astype(float).values,
                      "dist": m["distance_km"].astype(float).values})
    d["reg"] = m["file"].map(cad["regime"]).values
    r = m["file"].map(res["a1_R"]).values.astype(float); rn = m["file"].map(res["a1_n"]).values.astype(float)
    d["Y1"] = np.where(rn >= 600, r, np.nan)
    d["Y2"] = m["cell_spread_loaded_p95_mv"].astype(float).values
    d["Y3"] = m["V_pack_median"].astype(float).values
    d["day"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
    return d.reset_index(drop=True), hashlib.md5(open(master_path or os.path.join(root, "drive_master.csv"), "rb").read()).hexdigest()


def windows(d, frozen_path=FROZEN_PATH, write=True):
    """Frozen primary windows (thirds of the span first..last clean-drive date); the first run writes the frozen file."""
    d0, d1 = pd.Timestamp(d["date"].min()).normalize(), pd.Timestamp(d["date"].max()).normalize()
    span = (d1 - d0).days
    derived = {"spanFirst": str(d0.date()), "spanLast": str(d1.date()), "earlyEnd": str((d0 + pd.Timedelta(days=span // 3)).date()), "lateStart": str((d1 - pd.Timedelta(days=span // 3)).date())}
    if os.path.exists(frozen_path):
        fz = json.load(open(frozen_path, encoding="utf-8"))
    else:
        fz = {"frozenAt": datetime.datetime.now(datetime.timezone.utc).isoformat(), "spec": "analyses/M677_spec.md Rev 1.1", **derived}
        if write:
            json.dump(fz, open(frozen_path, "w", encoding="utf-8"), indent=1)
    return fz, derived


# -------------------------------------------------- cells (covariates only)
def make_edges(T, I, S, level):
    """Quantile edges computed from the covariates ONLY (V5: no outcome column reaches this function). Right-closed, lowest bin closed, duplicates merged."""
    def q(x, n):
        e = np.unique(np.quantile(x, np.linspace(0, 1, n + 1)))
        return e if len(e) >= 2 else np.array([x.min(), x.min() + 1.0])
    return {"T": q(T, level["nT"]), "I": q(I, level["nI"]), "S": q(S, level["nS"])}


def assign(df, edges, level, with_dist=False, reg_in_key=True):
    cols = []
    for v in ("T", "I", "S"):
        e = edges[v]
        c = pd.cut(df[v], bins=e, labels=False, include_lowest=True)
        c = np.where(df[v].values < e[0], 0, np.where(df[v].values > e[-1], len(e) - 2, c)).astype(int)
        cols.append(c)
    cols.append((df["reg"].astype(str).values == "fast").astype(int) if reg_in_key else np.zeros(len(df), dtype=int))          # fixed coding (fast = 1, slow = 0) so the early and late frames use the same cell keys
    if with_dist:
        cols.append(pd.cut(df["dist"], DIST_EDGES, labels=False).fillna(0).astype(int).values)
    key = np.zeros(len(df), dtype=np.int64)
    for c in cols:
        key = key * 100 + c
    return key


def used_cells(key_e, day_e, key_l, day_l):
    ce = pd.DataFrame({"k": key_e, "d": day_e}).groupby("k").agg(n=("d", "size"), nd=("d", "nunique"))
    cl = pd.DataFrame({"k": key_l, "d": day_l}).groupby("k").agg(n=("d", "size"), nd=("d", "nunique"))
    j = ce.join(cl, lsuffix="_e", rsuffix="_l", how="inner")
    ok = j[(j["n_e"] >= MIN_CELL) & (j["n_l"] >= MIN_CELL) & (j["nd_e"] >= MIN_CELL_DAYS) & (j["nd_l"] >= MIN_CELL_DAYS)]
    return list(ok.index)


def choose_level(early, late, with_dist=False, reg_in_key=True):
    """Covariate-only ladder (no outcome read): first level that matches at least 50 % of the late drives."""
    pool = pd.concat([early, late])
    best = None
    for lv in LEVELS:
        ed = make_edges(pool["T"].values, pool["I"].values, pool["S"].values, lv)
        ke, kl = assign(early, ed, lv, with_dist, reg_in_key), assign(late, ed, lv, with_dist, reg_in_key)
        cells = used_cells(ke, early["day"].values, kl, late["day"].values)
        share = float(np.isin(kl, cells).mean()) if len(late) else 0.0
        best = (lv, ed, ke, kl, cells, share)
        if share >= 0.5:
            return best, True
    return best, False


# ---------------------------------------------------------------- path A
def _day_tables(y, key, day, cells):
    """Per-day sums and counts for each used cell: arrays [n_days, n_cells]."""
    ud, inv = np.unique(day, return_inverse=True)
    ci = {c: i for i, c in enumerate(cells)}
    S = np.zeros((len(ud), len(cells))); N = np.zeros((len(ud), len(cells)))
    for r, (k, v) in enumerate(zip(key, y)):
        if k in ci:
            S[inv[r], ci[k]] += v; N[inv[r], ci[k]] += 1
    return S, N


def path_a(early, late, ycol, with_dist=False, nboot=NBOOT, seed=SEED):
    ey = early.dropna(subset=[ycol]).reset_index(drop=True); ly = late.dropna(subset=[ycol]).reset_index(drop=True)
    if len(ey) < 10 or len(ly) < 10:
        return {"status": "not shown", "reason": "fewer than 10 drives in a window", "nEarly": int(len(ey)), "nLate": int(len(ly))}
    (lv, ed, ke, kl, cells, share), reached = choose_level(ey, ly, with_dist)
    out = {"level": lv["name"], "levelReachedFiftyPercent": bool(reached), "nEarlyDrives": int(len(ey)), "nLateDrives": int(len(ly)),
           "nEarlyDays": int(ey["day"].nunique()), "nLateDays": int(ly["day"].nunique()), "nCellsUsed": int(len(cells)), "matchedLateShare": share,
           "edges": {k: [float(x) for x in v] for k, v in ed.items()}}
    mask_l = np.isin(kl, cells); mask_e = np.isin(ke, cells)
    out["matchedLateDrives"] = int(mask_l.sum()); out["matchedLateDays"] = int(ly.loc[mask_l, "day"].nunique())
    out["matchedEarlyDrives"] = int(mask_e.sum()); out["matchedEarlyDays"] = int(ey.loc[mask_e, "day"].nunique())
    if not cells or out["matchedLateDrives"] < SHOW_DRIVES or out["matchedLateDays"] < SHOW_DAYS:
        out.update(status="not shown", reason="fewer than %d matched late drives or %d matched late days" % (SHOW_DRIVES, SHOW_DAYS)); return out
    Se, Ne = _day_tables(ey[ycol].values, ke, ey["day"].values, cells)
    Sl, Nl = _day_tables(ly[ycol].values, kl, ly["day"].values, cells)
    w = Nl.sum(0); w = w / w.sum()
    me, ml = Se.sum(0) / Ne.sum(0), Sl.sum(0) / Nl.sum(0)
    est = float(((ml - me) * w).sum()); ebar = float((me * w).sum())
    rng = np.random.default_rng(seed)
    nde, ndl = len(Se), len(Sl)
    B, dropped = [], 0
    ie = rng.integers(0, nde, size=(nboot, nde)); il = rng.integers(0, ndl, size=(nboot, ndl))
    for b in range(nboot):
        ne = Ne[ie[b]].sum(0); nl = Nl[il[b]].sum(0)
        if (ne == 0).any() or (nl == 0).any():
            dropped += 1; continue
        B.append((((Sl[il[b]].sum(0) / nl) - (Se[ie[b]].sum(0) / ne)) * w).sum())
    B = np.array(B)
    se = float(B.std(ddof=1)) if len(B) > 1 else float("nan")
    out.update(status="computed" if share >= 0.5 else "weakly overlapping", estimate=est, pctOfEarlyMatchedMean=float(100 * est / ebar) if ebar else None,
               ci95=[float(np.percentile(B, 2.5)), float(np.percentile(B, 97.5))],
               ci98_33=[float(np.percentile(B, 100 * ALPHA_BONF / 2)), float(np.percentile(B, 100 * (1 - ALPHA_BONF / 2)))],
               bootstrapSe=se, twoPointEightSe=float(2.8 * se), nDraws=int(len(B)), droppedDraws=int(dropped), droppedShare=float(dropped / nboot), unstable=bool(dropped / nboot > 0.05),
               unadjustedLateMinusEarly=float(ly[ycol].mean() - ey[ycol].mean()))
    out["_cellsMask"] = (mask_e, mask_l)           # internal (removed before output)
    return out


# ---------------------------------------------------------------- path B
def path_b(early, late, ycol, matched_masks=None, arrhenius=False):
    """OLS y ~ late + T term + I + S + regime; day-cluster CR1 SE; t(G-1) intervals (95 % and 98.33 %). matched_masks=(mask_early, mask_late) restricts to the matched-support drives."""
    e = early.dropna(subset=[ycol]).reset_index(drop=True); l = late.dropna(subset=[ycol]).reset_index(drop=True)
    if matched_masks is not None:
        e, l = e[matched_masks[0]], l[matched_masks[1]]
    df = pd.concat([e.assign(late=0.0), l.assign(late=1.0)], ignore_index=True)
    if len(df) < 20 or df["late"].nunique() < 2:
        return {"status": "not estimable"}
    tv = 1000.0 / (df["T"].values + 273.15) if arrhenius else df["T"].values
    X = np.column_stack([np.ones(len(df)), df["late"].values, tv, df["I"].values, df["S"].values, (df["reg"].astype(str) == "fast").astype(float).values])
    y = df[ycol].values
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    XtXi = np.linalg.pinv(X.T @ X)
    ud, inv = np.unique(df["day"].values, return_inverse=True)
    G = len(ud); n, k = X.shape
    meat = np.zeros((k, k))
    for g in range(G):
        xg = X[inv == g].T @ resid[inv == g]
        meat += np.outer(xg, xg)
    V = XtXi @ meat @ XtXi * (G / (G - 1)) * ((n - 1) / (n - k))
    se = float(np.sqrt(V[1, 1]))
    out = {"status": "computed", "estimate": float(beta[1]), "se": se, "nDrives": int(n), "nDays": int(G), "df": int(G - 1)}
    for nm, a in (("ci95", 0.05), ("ci98_33", ALPHA_BONF)):
        tq = stats.t.ppf(1 - a / 2, G - 1)
        out[nm] = [float(beta[1] - tq * se), float(beta[1] + tq * se)]
    return out


def excl0(ci):
    return bool(ci[0] > 0 or ci[1] < 0)



# ============================================================ M680: intervals with simulated coverage (spec analyses/M679_spec.md Rev 1.1)
COVERAGE_PATH = os.path.join(ROOT, "analyses", "M679_coverage.json")
CONSTRUCTIONS = ("C1", "C2", "C3")
NREP, NB_STUDY = 400, 1000


def setup(early, late, ycol, with_dist=False, slow_only=False):
    """Cells and drive-to-cell/day indices exactly as path_a builds them (same ladder, floors, edges); returns None when no cell is used."""
    ey = early.dropna(subset=[ycol]).reset_index(drop=True); ly = late.dropna(subset=[ycol]).reset_index(drop=True)
    if slow_only:
        ey = ey[ey["reg"].astype(str) == "slow"].reset_index(drop=True); ly = ly[ly["reg"].astype(str) == "slow"].reset_index(drop=True)
    if len(ey) < 10 or len(ly) < 10:
        return None
    (lv, ed, ke, kl, cells, share), reached = choose_level(ey, ly, with_dist, reg_in_key=not slow_only)
    if not cells:
        return None
    ci = {c: i for i, c in enumerate(cells)}
    ce = np.array([ci.get(k, -1) for k in ke]); cl = np.array([ci.get(k, -1) for k in kl])
    ude, ie = np.unique(ey["day"].values, return_inverse=True); udl, il = np.unique(ly["day"].values, return_inverse=True)
    C = len(cells)
    Ne = np.zeros((len(ude), C)); Nl = np.zeros((len(udl), C))
    np.add.at(Ne, (ie[ce >= 0], ce[ce >= 0]), 1.0); np.add.at(Nl, (il[cl >= 0], cl[cl >= 0]), 1.0)
    w = Nl.sum(0) / Nl.sum()
    return {"ey": ey, "ly": ly, "ce": ce, "cl": cl, "ie": ie, "il": il, "Ne": Ne, "Nl": Nl, "w": w, "C": C, "level": lv["name"], "share": float(share),
            "nde": len(ude), "ndl": len(udl)}


def day_tables(st, ye, yl):
    Se = np.zeros_like(st["Ne"]); Sl = np.zeros_like(st["Nl"])
    me, ml = st["ce"] >= 0, st["cl"] >= 0
    np.add.at(Se, (st["ie"][me], st["ce"][me]), ye[me]); np.add.at(Sl, (st["il"][ml], st["cl"][ml]), yl[ml])
    return Se, Sl


def est_from(Se, Ne, Sl, Nl, w):
    return float((((Sl.sum(0) / Nl.sum(0)) - (Se.sum(0) / Ne.sum(0))) * w).sum())


def _ci_pct(B, alpha):
    return [float(np.percentile(B, 100 * alpha / 2)), float(np.percentile(B, 100 * (1 - alpha / 2)))]


def c1_draws(Se, Ne, Sl, Nl, w, B, rng):
    """Cell-by-side stratified day bootstrap: days resampled within every used cell and side; no cell loses a side."""
    C = len(w); mean = {}
    for side, (S, N) in (("e", (Se, Ne)), ("l", (Sl, Nl))):
        m = np.zeros((B, C))
        for c in range(C):
            days = np.where(N[:, c] > 0)[0]
            idx = rng.integers(0, len(days), size=(B, len(days)))
            m[:, c] = S[days, c][idx].sum(1) / N[days, c][idx].sum(1)
        mean[side] = m
    return ((mean["l"] - mean["e"]) * w).sum(1)


def c3_draws(Se, Ne, Sl, Nl, w, B, rng):
    """Day-level Dirichlet (Bayesian bootstrap) weights within each side; no cell empties; cross-cell day dependence kept."""
    ke = Ne.sum(1) > 0; kl = Nl.sum(1) > 0
    We = rng.gamma(1.0, size=(B, int(ke.sum()))); Wl = rng.gamma(1.0, size=(B, int(kl.sum())))
    me = (We @ Se[ke]) / (We @ Ne[ke]); ml = (Wl @ Sl[kl]) / (Wl @ Nl[kl])
    return ((ml - me) * w).sum(1)


def c2_interval(Se, Ne, Sl, Nl, w, alphas=(0.05, ALPHA_BONF)):
    """Stratified delete-one-day jackknife (strata: early, late; days with at least one drive in a used cell); df = G_e + G_l - 2."""
    est = est_from(Se, Ne, Sl, Nl, w)
    ke = np.where(Ne.sum(1) > 0)[0]; kl = np.where(Nl.sum(1) > 0)[0]
    se_, ne_, sl_, nl_ = Se.sum(0), Ne.sum(0), Sl.sum(0), Nl.sum(0)
    th_e = np.array([(((sl_ / nl_) - ((se_ - Se[g]) / (ne_ - Ne[g]))) * w).sum() for g in ke])
    th_l = np.array([((((sl_ - Sl[g]) / (nl_ - Nl[g])) - (se_ / ne_)) * w).sum() for g in kl])
    Ge, Gl = len(th_e), len(th_l)
    var = (Ge - 1) / Ge * ((th_e - th_e.mean()) ** 2).sum() + (Gl - 1) / Gl * ((th_l - th_l.mean()) ** 2).sum()
    se = float(np.sqrt(var)); df = Ge + Gl - 2
    out = {"estimate": est, "se": se, "df": int(df), "Ge": int(Ge), "Gl": int(Gl)}
    for nm, a in (("ci95", alphas[0]), ("ci98_33", alphas[1])):
        tq = stats.t.ppf(1 - a / 2, df)
        out[nm] = [est - tq * se, est + tq * se]
    return out


def all_intervals(Se, Ne, Sl, Nl, w, B, rng):
    r = {}
    d1 = c1_draws(Se, Ne, Sl, Nl, w, B, rng)
    r["C1"] = {"ci95": _ci_pct(d1, 0.05), "ci98_33": _ci_pct(d1, ALPHA_BONF)}
    r["C2"] = c2_interval(Se, Ne, Sl, Nl, w)
    d3 = c3_draws(Se, Ne, Sl, Nl, w, B, rng)
    r["C3"] = {"ci95": _ci_pct(d3, 0.05), "ci98_33": _ci_pct(d3, ALPHA_BONF)}
    return r


def var_components(st, ye, yl, nboot=200, seed=SEED):
    """REML random-day-intercept fit on the residuals after removing the cell-by-side means (both windows); upper 95 % limit of the day SD by a day bootstrap."""
    rows = []
    for side, (y, c, i) in (("e", (ye, st["ce"], st["ie"])), ("l", (yl, st["cl"], st["il"]))):
        m = c >= 0
        df = pd.DataFrame({"y": y[m], "c": c[m], "d": [side + str(k) for k in i[m]]})
        df["r"] = df["y"] - df.groupby("c")["y"].transform("mean")
        rows.append(df)
    df = pd.concat(rows, ignore_index=True)

    def fit(d):
        """Exact REML of the one-way random-day-intercept model by the profile over lambda = var_day / var_resid (closed forms; the statsmodels optimiser failed on the boundary)."""
        r = d["r"].values.astype(float); g = pd.factorize(d["d"].values)[0]
        n_g = np.bincount(g).astype(float); s_g = np.bincount(g, weights=r); N = float(len(r))
        if len(n_g) < 3 or N < 10:
            return None

        def prof(lam):
            wg = n_g / (1.0 + lam * n_g)
            mu = (wg * s_g / n_g).sum() / wg.sum()
            # GLS residual sum of squares of the marginal model with compound symmetry within day
            rss = ((r - mu) ** 2).sum() - (lam / (1.0 + lam * n_g) * (s_g - n_g * mu) ** 2).sum()
            if rss <= 0:
                return np.inf, mu, rss
            sig2 = rss / (N - 1.0)
            nll = 0.5 * (np.log1p(lam * n_g).sum() + (N - 1.0) * np.log(sig2) + np.log(wg.sum()))
            return nll, mu, sig2
        grid = np.concatenate([[0.0], np.logspace(-4, 3, 120)])
        vals = [prof(x)[0] for x in grid]
        j = int(np.argmin(vals))
        lam = grid[j]
        if 0 < j < len(grid) - 1:
            from scipy.optimize import minimize_scalar
            o = minimize_scalar(lambda x: prof(x)[0], bounds=(grid[j - 1], grid[j + 1]), method="bounded", options={"xatol": 1e-9})
            lam = float(o.x) if prof(o.x)[0] <= vals[j] else lam
        _, _, sig2 = prof(lam)
        return float(np.sqrt(lam * sig2)), float(np.sqrt(sig2))
    f = fit(df)
    sd_d, sd_e = f if f else (0.0, float(df["r"].std()))
    groups = [g for _, g in df.groupby("d")]
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(nboot):
        pick = rng.integers(0, len(groups), len(groups))
        d = pd.concat([groups[k].assign(d=groups[k]["d"].iloc[0] + "_%d" % j) for j, k in enumerate(pick)], ignore_index=True)
        fb = fit(d)
        if fb:
            boots.append(fb[0])
    lo, hi = (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))) if boots else (0.0, sd_d)
    zero = sd_d < 1e-6 or lo < 1e-6
    used = hi if zero else sd_d
    icc = float(sd_d ** 2 / (sd_d ** 2 + sd_e ** 2)) if (sd_d + sd_e) > 0 else 0.0
    return {"sdDay": sd_d, "sdResid": sd_e, "icc": icc, "sdDayBootstrapCi95": [lo, hi], "dayEffectIncludesZero": bool(zero), "sdDayUsedInScenarios": float(used),
            "pool": [g["r"].values for g in groups]}


def simulate(st, mu_c, sd_e, sd_d, delta_c, rng, pool=None):
    def side(c, idx, nd, late):
        de = rng.normal(0, sd_d, nd) if sd_d > 0 else np.zeros(nd)
        n = len(c)
        if pool is None:
            noise = rng.normal(0, sd_e, n)
        else:
            noise = np.zeros(n)
            pick = rng.integers(0, len(pool), nd)
            cnt = np.zeros(nd, dtype=int)
            for j in range(n):
                v = pool[pick[idx[j]]]; noise[j] = v[cnt[idx[j]] % len(v)]; cnt[idx[j]] += 1
        cc = np.clip(c, 0, None)
        base = np.where(c >= 0, mu_c[cc] + (delta_c[cc] if late else 0.0), 0.0)
        return base + de[idx] + noise
    return side(st["ce"], st["ie"], st["nde"], False), side(st["cl"], st["il"], st["ndl"], True)


def fingerprint(st):
    """Design fingerprint of the used-drive set (drive ids, cells, side, late-count weights) and the used-cell day counts (days with at least one drive in a used cell)."""
    rows = [("e", str(f), int(c)) for f, c in zip(st["ey"]["file"].values, st["ce"]) if c >= 0] + [("l", str(f), int(c)) for f, c in zip(st["ly"]["file"].values, st["cl"]) if c >= 0]
    rows.sort()
    h = hashlib.sha256(json.dumps({"rows": rows, "w": [round(float(x), 12) for x in st["w"]]}, sort_keys=True).encode("utf-8")).hexdigest()
    return {"usedDriveSetHash": h, "Ge": int((st["Ne"].sum(1) > 0).sum()), "Gl": int((st["Nl"].sum(1) > 0).sum()), "nCells": int(st["C"]), "nUsedEarlyDrives": int((st["ce"] >= 0).sum()), "nUsedLateDrives": int((st["cl"] >= 0).sum()),
            "definition": "Ge and Gl count the calendar days with at least one drive in a used cell (nEarlyDays / nLateDays count all days of the window frame)"}


def real_setup(d, oid, fz):
    dd = clean_cov(d.dropna(subset=[oid])); e, l = split(dd, fz["earlyEnd"], fz["lateStart"])
    return setup(e, l, oid)


def add_fingerprints(path=COVERAGE_PATH, root=ROOT):
    """Writes the design fingerprint of the real used-drive set into the coverage file (same setup() as the study and the payload); asserts the study's cell and day structure equals it."""
    d, md5 = load(root); fz, derived = windows(d, write=False)
    cov = json.load(open(path, encoding="utf-8"))
    for oid in ("Y2", "Y3"):
        st = real_setup(d, oid, fz); f = fingerprint(st)
        o = cov["outcomes"][oid]
        assert o["nCells"] == f["nCells"] and o["nEarlyDays"] == st["nde"] and o["nLateDays"] == st["ndl"], (oid, "the study used a different design")
        o["designFingerprint"] = f
    cov["fingerprintNote"] = "added after the study by --fingerprint from the same setup() (no change of any number); the assertion above compares the study's cells and window-frame day counts"
    json.dump(cov, open(path, "w", encoding="utf-8"), indent=1, default=str)
    return {o: cov["outcomes"][o]["designFingerprint"] for o in ("Y2", "Y3")}


def select_construction(res):
    """Per outcome: admissible = 95 % coverage >= 0.90 in every scenario and <= 0.99 in S1; among admissible the higher minimum over S2-S4; tie -> C2; none -> None."""
    adm = []
    for c in CONSTRUCTIONS:
        cv = {s: res[s][c]["coverage95"] for s in res}
        if all(v >= 0.90 for v in cv.values()) and cv["S1"] <= 0.99:
            adm.append((min(cv[s] for s in ("S2", "S3", "S4")), c))
    if not adm:
        return None
    top = max(a[0] for a in adm)
    tied = [c for m_, c in adm if abs(m_ - top) < 1e-12]
    return "C2" if "C2" in tied else tied[0]


def coverage_study(root=ROOT, nrep=NREP, nb=NB_STUDY):
    d, md5 = load(root)
    fz, derived = windows(d, write=False)
    out = {"spec": "analyses/M679_spec.md Rev 1.1", "corpusHash": md5, "nRep": nrep, "nBoot": nb,
           "scenarios": {"S1": "delta 0, no day effect", "S2": "delta 0, day effect at the fitted size (upper 95 % limit if zero)",
                         "S3": "delta differs by cell (target = late-weighted mean), day effect fitted", "S4": "delta 0, day effect 2 x fitted",
                         "S5": "S3 delta with non-Gaussian errors (day-blocked residual resampling)"}, "outcomes": {}}
    for oid in ("Y2", "Y3"):
        dd = clean_cov(d.dropna(subset=[oid])); e, l = split(dd, fz["earlyEnd"], fz["lateStart"])
        st = setup(e, l, oid)
        ye, yl = st["ey"][oid].values, st["ly"][oid].values
        mu = np.zeros(st["C"])
        for c in range(st["C"]):
            mu[c] = np.concatenate([ye[st["ce"] == c], yl[st["cl"] == c]]).mean()
        vc = var_components(st, ye, yl)
        sd_e, sd_d = vc["sdResid"], vc["sdDayUsedInScenarios"]
        dl = 1.5 * sd_e * (0.5 + np.linspace(0, 1, st["C"]))
        zero = np.zeros(st["C"])
        scen = {"S1": (0.0, zero, None), "S2": (sd_d, zero, None), "S3": (sd_d, dl, None), "S4": (2 * sd_d, zero, None), "S5": (sd_d, dl, vc["pool"])}
        res = {}
        for k, (sname, (sdd, delta_c, pool)) in enumerate(scen.items()):
            rng = np.random.default_rng(42 + k)
            truth = float((delta_c * st["w"]).sum())
            cnt = {c: {"c95": 0, "c98": 0, "lo": 0, "hi": 0} for c in CONSTRUCTIONS}
            for r in range(nrep):
                yes, yls = simulate(st, mu, sd_e, sdd, delta_c, rng, pool)
                Se, Sl = day_tables(st, yes, yls)
                iv = all_intervals(Se, st["Ne"], Sl, st["Nl"], st["w"], nb, rng)
                for c in CONSTRUCTIONS:
                    a, b = iv[c]["ci95"]; a2, b2 = iv[c]["ci98_33"]
                    cnt[c]["c95"] += int(a <= truth <= b); cnt[c]["c98"] += int(a2 <= truth <= b2); cnt[c]["lo"] += int(truth < a); cnt[c]["hi"] += int(truth > b)
            res[sname] = {c: {"coverage95": cnt[c]["c95"] / nrep, "coverage98_33": cnt[c]["c98"] / nrep, "missLow": cnt[c]["lo"] / nrep, "missHigh": cnt[c]["hi"] / nrep,
                              "mcSe": float(np.sqrt(cnt[c]["c95"] / nrep * (1 - cnt[c]["c95"] / nrep) / nrep))} for c in CONSTRUCTIONS}
            res[sname]["truth"] = truth; res[sname]["seed"] = 42 + k
        sel = select_construction({s: {c: res[s][c] for c in CONSTRUCTIONS} for s in res})
        out["outcomes"][oid] = {"varianceComponents": {k: v for k, v in vc.items() if k != "pool"}, "scenarios": res, "selected": sel,
                                "nCells": st["C"], "nEarlyDays": st["nde"], "nLateDays": st["ndl"], "matchedLateShare": st["share"], "level": st["level"], "designFingerprint": fingerprint(st)}
    return out


def interval_v2(oid, e, l, pb_p, slow_only=False, seed=SEED):
    """intervalV2 for the real data: all three constructions beside, the selected one from the coverage file; persistsV2."""
    st = setup(e, l, oid, slow_only=slow_only)
    if st is None:
        return {"status": "not shown"}, False
    ye, yl = st["ey"][oid].values, st["ly"][oid].values
    Se, Sl = day_tables(st, ye, yl)
    iv = all_intervals(Se, st["Ne"], Sl, st["Nl"], st["w"], NBOOT, np.random.default_rng(seed))
    cov = json.load(open(COVERAGE_PATH, encoding="utf-8")) if os.path.exists(COVERAGE_PATH) else None
    rec = {"construction": None, "intervalsAllConstructions": iv, "estimate": est_from(Se, st["Ne"], Sl, st["Nl"], st["w"]), "droppedDraws": 0}
    if slow_only:
        rec.update(status="interval not shown (no coverage run of its own)"); return rec, False
    if cov is None or oid not in cov.get("outcomes", {}):
        rec.update(status="coverage study not run", note="interval not valid, not for display"); return rec, False
    sel = cov["outcomes"][oid]["selected"]
    fpr = fingerprint(st); fpc = cov["outcomes"][oid].get("designFingerprint")
    rec["coverageStudyRef"] = {"file": "analyses/M679_coverage.json", "corpusHash": cov["corpusHash"], "nRep": cov["nRep"], "selected": sel, "usedDriveSetHash": fpc["usedDriveSetHash"] if fpc else None,
                               "currentUsedDriveSetHash": fpr["usedDriveSetHash"], "Ge": fpr["Ge"], "Gl": fpr["Gl"]}
    scen = cov["outcomes"][oid]["scenarios"]
    for c in CONSTRUCTIONS:
        ok = all(scen[x][c]["coverage95"] >= 0.90 for x in scen) and scen["S1"][c]["coverage95"] <= 0.99
        rec["intervalsAllConstructions"][c]["admissible"] = bool(ok)
        if not ok:
            rec["intervalsAllConstructions"][c]["label"] = "not admissible (coverage gate), reference only"
    if not fpc or fpc["usedDriveSetHash"] != fpr["usedDriveSetHash"]:
        rec.update(status="coverage study stale", note="the used-drive set differs from the one the coverage study was run on; rerun the study; not for display"); return rec, False
    if sel is None:
        rec.update(status="no construction passed the coverage gate", note="interval not valid, not for display"); return rec, False
    rec.update(status="interval with simulated coverage", construction=sel, ci95=iv[sel]["ci95"], ci98_33=iv[sel]["ci98_33"],
               simulatedCoverage95={s: cov["outcomes"][oid]["scenarios"][s][sel]["coverage95"] for s in ("S1", "S2", "S3", "S4", "S5")})
    persists = bool(pb_p and pb_p.get("status") == "computed" and np.sign(rec["estimate"]) == np.sign(pb_p["estimate"]) and excl0(rec["ci98_33"]) and excl0(pb_p["ci98_33"]))
    return rec, persists



# --------------------------------------------------------------- per outcome
def split(d, early_end, late_start):
    e = d[d["date"] <= pd.Timestamp(early_end) + pd.Timedelta(hours=23, minutes=59)]
    l = d[d["date"] >= pd.Timestamp(late_start)]
    return e, l


def clean_cov(d):
    return d.dropna(subset=["T", "I", "S", "reg"]).reset_index(drop=True)


def outcome_block(oid, d, fz, derived, nboot):
    ycol = oid
    dd = clean_cov(d.dropna(subset=[ycol]))
    e, l = split(dd, fz["earlyEnd"], fz["lateStart"])
    rec = {"label": OUTCOMES[oid][0], "source": OUTCOMES[oid][1], "windows": {"earlyEnd": fz["earlyEnd"], "lateStart": fz["lateStart"]}}
    pa = path_a(e, l, ycol, nboot=nboot)
    masks = pa.pop("_cellsMask", None)
    rec["pathA"] = pa
    arr = (oid == "Y1")
    pb_p = path_b(e, l, ycol, masks, arrhenius=arr) if masks else {"status": "not estimable"}
    pb_s = path_b(e, l, ycol, None, arrhenius=arr)
    rec["pathB"] = {"primaryMatchedSupport": pb_p, "secondaryAllDrives": pb_s, "temperatureTerm": "1000/(T+273.15)" if arr else "linear"}
    shown = pa.get("status") in ("computed", "weakly overlapping")
    sameSign = shown and pb_p.get("status") == "computed" and np.sign(pa["estimate"]) == np.sign(pb_p["estimate"])
    rec["agreement"] = {"sameSign": bool(sameSign) if shown else None,
                        "pathAExcludesZero95": excl0(pa["ci95"]) if shown else None, "pathBExcludesZero95": excl0(pb_p["ci95"]) if pb_p.get("status") == "computed" else None}
    rec["persists"] = bool(pa.get("status") == "computed" and not pa.get("unstable") and pb_p.get("status") == "computed" and sameSign and excl0(pa["ci98_33"]) and excl0(pb_p["ci98_33"]))
    rec["persistsRev11"] = bool(shown and pb_p.get("status") == "computed" and sameSign and excl0(pa["ci98_33"]) and excl0(pb_p["ci98_33"]))
    if shown:
        pa["intervalStatus"] = "unstable, not for display (drop-conditioned bootstrap)" if pa.get("unstable") else "stable under the 5 % drop rule"
        pa["widthAboveEstimate"] = bool(pa["twoPointEightSe"] > abs(pa["estimate"]))
    rec["persistsRule"] = ("same sign and both Path A and Path B (matched-support) 98.33 % intervals exclude zero (Bonferroni over three outcomes); sensitivities never upgrade a result. "
                           "Rev 1.2 (stricter than Rev 1.1, added after the first run was seen): also requires a matched late share of at least 50 % (status computed, not weakly overlapping) and a stable interval (at most 5 % of draws dropped). persistsRev11 is the Rev 1.1 rule alone, shown beside")
    if shown:
        iv2, pv2 = interval_v2(oid, e, l, pb_p)
        rec["intervalV2"] = iv2; rec["persistsV2"] = pv2
        slow, _ = interval_v2(oid, e, l, pb_p, slow_only=True)
        rec["slowOnlyDescriptive"] = {"note": "descriptive variant, not a second primary, never enters persists; interval not shown (no coverage run of its own)", "status": slow.get("status"), "estimate": slow.get("estimate")}
    else:
        rec["persistsV2"] = False
    rec["sensitivities"] = sens(oid, dd, fz, derived, pa, nboot)
    return rec


def _brief(pa):
    if pa.get("status") in ("computed", "weakly overlapping"):
        return {"status": pa["status"], "estimate": pa["estimate"], "ci95": pa["ci95"], "level": pa["level"], "matchedLateShare": pa["matchedLateShare"], "matchedLateDrives": pa["matchedLateDrives"], "matchedLateDays": pa["matchedLateDays"],
                "nDraws": pa["nDraws"], "droppedShare": pa["droppedShare"], "unstable": pa["unstable"]}
    return {"status": pa.get("status"), "reason": pa.get("reason")}


def sens(oid, dd, fz, derived, primary, nboot):
    ycol = oid
    out = {}
    nb = min(nboot, 2000)

    def run(e, l, **kw):
        p = path_a(e, l, ycol, nboot=nb, **kw); p.pop("_cellsMask", None); return _brief(p)
    lo, hi = pd.Timestamp(derived["spanFirst"]), pd.Timestamp(derived["spanLast"])
    half = lo + (hi - lo) / 2
    eh = dd[dd["date"] <= half]; lh = dd[dd["date"] > half]
    out["a_halves"] = run(eh, lh)
    # b cadence strata
    e, l = split(dd, fz["earlyEnd"], fz["lateStart"])
    for r in ("fast", "slow"):
        out["b_cadence_" + r] = run(e[e["reg"] == r], l[l["reg"] == r])
    out["c_wider_late_narrower_early"] = run(dd[dd["date"] < pd.Timestamp("2026-07-01")], dd[dd["date"] >= pd.Timestamp("2026-09-01")])
    u = pd.Timestamp(UPDATE_DATE)
    keep = (dd["date"] < u - pd.Timedelta(days=7)) | (dd["date"] > u + pd.Timedelta(days=7))
    dk = dd[keep]
    out["d_halves_excluding_update_pm7d"] = run(dk[dk["date"] <= half], dk[dk["date"] > half])
    # e leave-one-week-out of the primary
    wk = e["date"].dt.isocalendar().week.astype(int); wl = l["date"].dt.isocalendar().week.astype(int)
    ests = []
    for w in sorted(set(wk) | set(wl)):
        p = path_a(e[wk != w], l[wl != w], ycol, nboot=200)
        if p.get("estimate") is not None:
            ests.append(p["estimate"])
    out["e_leave_one_week_out"] = {"n": len(ests), "min": float(min(ests)) if ests else None, "max": float(max(ests)) if ests else None}
    out["f_with_distance_class"] = run(e, l, with_dist=True)
    # re-derived thirds (differs from the frozen windows only after later ingestions)
    e2, l2 = split(dd, derived["earlyEnd"], derived["lateStart"])
    out["reDerivedThirds"] = {"windows": {"earlyEnd": derived["earlyEnd"], "lateStart": derived["lateStart"]}, **run(e2, l2)}
    return out


# ---------------------------------------------------------------- block
def build(root=ROOT, master_path=None, nboot=NBOOT, frozen_path=None, write_frozen=True):
    d, md5 = load(root, master_path)
    fz, derived = windows(d, frozen_path or FROZEN_PATH, write=write_frozen)
    u = pd.Timestamp(UPDATE_DATE)
    inMiddle = bool(pd.Timestamp(fz["earlyEnd"]) < u < pd.Timestamp(fz["lateStart"]))
    block = {"spec": "analyses/M677_spec.md Rev 1.1, 1.2", "exploratory": True, "articleUse": False, "descriptiveNotALook": "descriptive, not a look, no equivalence verdict, no alpha spent; never feeds the month-9 or month-12 looks",
             "estimand": "late-drive-weighted matched difference on the matched late subset (late minus early), in the outcome units",
             "seed": SEED, "nBoot": nboot, "corpusHash": md5, "frozenWindows": fz, "updateDateInExcludedMiddle": inMiddle, "outcomes": {}}
    if not inMiddle:
        block["flag"] = "2026-08-25 is not in the excluded middle third: results are not shown"
    else:
        for oid in OUTCOMES:
            block["outcomes"][oid] = outcome_block(oid, d, fz, derived, nboot)
    block["deviations"] = ["Y3 is the median pack voltage V_pack_median, not cap_ah_est: cap_ah_est (2.1 kWh divided by the median pack voltage) was already known to be a voltage proxy (M413), so this is a spec omission, not a new finding; the SOC-swing eligibility of Director change 8 has no object.",
                           "persists additionally requires status computed and a stable interval (Rev 1.2, added after the first run); persistsRev11 shown beside."]
    block["reading"] = [
        "A difference between early and late drives in matched state bins; time, season, route mix, load, logger configuration and the HV-battery software update (owner-reported around 2026-08-25, in the excluded middle third) move together on one vehicle. Not an ageing estimate; a same-season comparison is not available in a 12-month study.",
        "The estimand covers only the matched late subset (overlap is partial; the matched late share is reported). Drive-mean pack temperature does not describe the thermal state.",
        "Y3 is the median pack voltage: cap_ah_est in the master is 2.1 kWh divided by the median pack voltage (a voltage proxy scaled by an assumed energy, not a capacity or an Ah-per-SOC measurement); SOC level is a matching variable.",
        "Cadence is part of the cell key and all early drives of the window are slow-polled, so fast-polled late drives cannot match: the matched late share has a structural ceiling (the share of slow-polled late drives) and 'weakly overlapping' is structural, not a tuning outcome. When no ladder level reaches 50 % the coarsest level is used and the status stays 'weakly overlapping'. Path B on the matched support uses the early and late drives in the used cells.",
        "Coarse cells (the ladder falls back to 3 temperature classes of roughly 10 deg C width) leave within-cell covariate differences; Path B adjusts linearly beside it and the two are compared, never tuned to agree. Many bootstrap draws can be dropped when a used cell loses a side (droppedShare); an interval with more than 5 % dropped is flagged unstable.",
        "'persists' (Rev 1.2) needs the same sign, both paths' 98.33 % intervals excluding zero, a matched late share of at least 50 % and at most 5 % of bootstrap draws dropped; persistsRev11 applies the first two conditions only and is shown beside, the stricter rule having been added after the first run was seen. persists = false is not 'no difference'. Every other statement is descriptive and unadjusted.",
        "Path A intervals with more than 5 % of draws dropped are selected on cell survival and are not valid confidence intervals: unstable, not for display. Path B (CR1) may be shown beside. intervalV2 (M680, spec analyses/M679_spec.md Rev 1.1) is an interval with simulated coverage: the construction selected by the planted-effect coverage gate (analyses/M679_coverage.json: 400 replicates per scenario, 95 % coverage per scenario in simulatedCoverage95); it supersedes the Path A bootstrap interval, which stays as the reference construction C0 labelled unstable. The coverage holds only under the fitted variance components and a day-independent error structure (correlation across days or weeks is not modelled); the study is not re-run at each ingestion (coverageStudyRef.corpusHash names its corpus).",
        "Where 2.8 times the bootstrap standard error (twoPointEightSe, a bootstrap-width quantity, not a power calculation) exceeds the estimate (widthAboveEstimate), the contrast cannot be distinguished from zero at this support.",
    ]
    block["validity"] = validate(block, d)
    return block


def validate(block, d):
    for oid, rec in block["outcomes"].items():
        pa = rec["pathA"]
        if pa.get("status") in ("computed", "weakly overlapping"):
            assert pa["matchedLateDrives"] <= pa["nLateDrives"] and pa["matchedEarlyDrives"] <= pa["nEarlyDrives"], (oid, "V3")
            assert pa["nCellsUsed"] >= 1, (oid, "V3 cells")
    e_end, l_start = pd.Timestamp(block["frozenWindows"]["earlyEnd"]), pd.Timestamp(block["frozenWindows"]["lateStart"])
    assert e_end < l_start, "V2 early and late windows overlap"
    return {"V2_V3_V4_V5": True}


def stamp(A, md5):
    import stamp_common as _sc
    old = (A.get("_artifactStamps") or {}).get(KEY)
    st = copy.deepcopy(A["_artifactStamps"]["headroomUtilization"]) if "headroomUtilization" in A.get("_artifactStamps", {}) else {}
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for k in ("carriedForward", "recomputeMode", "corpusSizeAtRecompute"):
        st.pop(k, None)
    st.update(corpusHash=md5, generatedAt=now, computationStatus="computed", upstreamHashes={"driveMasterMd5": md5},
              computationStatusNote="M678: derived by tools/early_late_contrast.py from drive_master.csv and two sidecars (spec analyses/M677_spec.md Rev 1.1, 1.2); exploratory")
    st["includedInReleaseAt"] = st["computedAt"] = st["generatedAt"]
    A["_artifactStamps"][KEY] = _sc.carry_declared(old, st)


def main(argv):
    sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
    nboot = int(argv[argv.index("--nboot") + 1]) if "--nboot" in argv else NBOOT
    if "--fingerprint" in argv:
        print(json.dumps(add_fingerprints())); return
    if "--coverage" in argv:
        res = coverage_study(nrep=int(argv[argv.index("--reps") + 1]) if "--reps" in argv else NREP)
        json.dump(res, open(argv[argv.index("--coverage") + 1], "w", encoding="utf-8"), indent=1, default=str)
        print(json.dumps({o: v["selected"] for o, v in res["outcomes"].items()})); return
    block = build(nboot=nboot)
    md5 = block["corpusHash"]
    if "--out" in argv:
        json.dump(block, open(argv[argv.index("--out") + 1], "w", encoding="utf-8"), indent=1, default=str)
        print("wrote block"); return
    p = os.path.join(ROOT, "summary_arrays.json")
    raw = open(p, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    old = copy.deepcopy(A)
    A[KEY] = json.loads(json.dumps(block, default=str))
    stamp(A, md5)
    chk = copy.deepcopy(A); chk.pop(KEY); chk["_artifactStamps"].pop(KEY)
    o2 = copy.deepcopy(old); o2.pop(KEY, None); o2["_artifactStamps"].pop(KEY, None)
    assert chk == o2, "unexpected change outside /" + KEY
    open(p, "w", encoding="utf-8", newline="").write(json.dumps(A, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    print(json.dumps({"changed": True}))


if __name__ == "__main__":
    main(sys.argv[1:])
