#!/usr/bin/env python3
"""M406 (analyses/M406_spec.md): dependence and small-cluster sensitivities of the thesis KPIs and of the two released trend slopes. Additive: writes ONLY the payload block
summary_arrays.json['dependenceSensitivity'] (+ its artifact stamp); the released estimators, intervals and the TOST decision are unchanged and nothing is tuned to make procedures agree.

Trend slopes (degradation_trends.py design, rebuilt with its own _prep / _covars_present): OLS y ~ months + T + I, cluster = calendar day.
  CR1   statsmodels-compatible cluster-robust SE (small-sample factor G/(G-1) * (n-1)/(n-p)): reproduces the released slope / SE / CI.
  CR2   bias-reduced linearisation: A_g = (I - H_gg)^(-1/2), V = M [sum_g X_g' A_g e_g e_g' A_g X_g] M; interval b +/- t_df SE with the Satterthwaite df of the independent-errors working
        model, df = (sum_g ||w_g||^2)^2 / ||W'W||_F^2, w_g = (I - H)[:, g] A_g X_g M c.
  wild cluster bootstrap-t (Rademacher by cluster): null-imposed p-value and unrestricted percentile-t interval, CR1 SE per draw.
  pairs bootstraps resampling whole calendar days / whole ISO weeks (refit of the full design).
  minimum effect with 80 % power: (t_df,0.975 + t_df,0.8) * SE (two-sided 5 % test, power 0.8, given the observed standard error).
Thesis KPIs: corpus ratios and per-drive medians with day-cluster and week-block percentile bootstrap intervals (same seed and draws).
Usage: python tools/dependence_sensitivity.py [--dry-run]"""
import copy, datetime, hashlib, json, os, sys
import numpy as np
import pandas as pd
from scipy import stats

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p_ in (ROOT, os.path.dirname(os.path.abspath(__file__))):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
N_BOOT, SEED = 4000, 42
SEED_SPREAD = (42, 43, 44, 45, 46)
METHOD_VERSION = 1
FAST_S = 1.05
POWER = 0.8


# ------------------------------------------------------------------------------------------------ cluster-robust inference
def _codes(groups):
    u, inv = np.unique(np.asarray(groups), return_inverse=True)
    return inv, len(u)


def ols(X, y):
    M = np.linalg.inv(X.T @ X)
    b = M @ X.T @ y
    return b, M, y - X @ b


def cr1(X, y, groups, k):
    """(b_k, se_k, G, n, p) with the statsmodels default small-sample correction."""
    inv, G = _codes(groups)
    n, p = X.shape
    b, M, e = ols(X, y)
    S = np.zeros((G, p))
    np.add.at(S, inv, X * e[:, None])
    V = (G / (G - 1.0)) * ((n - 1.0) / (n - p)) * M @ (S.T @ S) @ M
    return float(b[k]), float(np.sqrt(V[k, k])), G, n, p


def cr2(X, y, groups, k):
    """(b_k, se_k, df, flags): bias-reduced CR2 standard error and the Satterthwaite df (see the module docstring)."""
    inv, G = _codes(groups)
    n, p = X.shape
    b, M, e = ols(X, y)
    c = M[:, k]
    se2, flagged = 0.0, 0
    W = np.zeros((n, G))
    rows = [np.flatnonzero(inv == g) for g in range(G)]
    for g, r in enumerate(rows):
        Xg = X[r]
        Hgg = Xg @ M @ Xg.T
        vals, vecs = np.linalg.eigh(np.eye(len(r)) - Hgg)
        if (vals < 1e-10).any():
            flagged += 1
        inv_sqrt = (vecs * np.where(vals > 1e-10, 1.0 / np.sqrt(np.clip(vals, 1e-10, None)), 0.0)) @ vecs.T
        a = inv_sqrt @ Xg @ c
        se2 += float(a @ e[r]) ** 2
        col = -(X @ (M @ Xg.T))                       # -(H[:, g]) , n x n_g
        col[r, np.arange(len(r))] += 1.0              # (I - H)[:, g]
        W[:, g] = col @ a
    trB = float((W ** 2).sum())
    trB2 = float(((W.T @ W) ** 2).sum())
    df = trB ** 2 / trB2 if trB2 > 0 else float("nan")
    return float(b[k]), float(np.sqrt(se2)), float(df), {"clustersWithUnitLeverage": flagged}


def hc2_equivalent_check(X, y):
    """With singleton clusters CR2 equals HC2: returns the HC2 standard errors of all coefficients (used by the known-answer test)."""
    b, M, e = ols(X, y)
    h = np.einsum("ij,jk,ik->i", X, M, X)
    meat = (X * (e ** 2 / (1.0 - h))[:, None]).T @ X
    return np.sqrt(np.diag(M @ meat @ M))


def wild_cluster(X, y, groups, k, B=N_BOOT, seed=SEED):
    """Wild cluster bootstrap-t (Rademacher): null-imposed p-value for beta_k = 0 and the unrestricted percentile-t 95 % interval; CR1 standard error per draw."""
    inv, G = _codes(groups)
    n, p = X.shape
    order = np.argsort(inv, kind="stable")
    starts = np.r_[0, np.flatnonzero(np.diff(inv[order])) + 1]
    Xs, ys, invs = X[order], y[order], inv[order]
    b, M, e = ols(Xs, ys)
    u = (M @ Xs.T)[k]                                                  # row k of (X'X)^-1 X'
    corr = (G / (G - 1.0)) * ((n - 1.0) / (n - p))
    rng = np.random.default_rng(seed)
    v = rng.choice(np.array([-1.0, 1.0]), size=(G, B))[invs]            # n x B, constant within a cluster

    def t_stats(ystar):
        bs = (M @ Xs.T) @ ystar                                         # p x B
        es = ystar - Xs @ bs
        grp = np.add.reduceat(u[:, None] * es, starts, axis=0)           # G x B group sums of u_i e*_i
        se = np.sqrt(corr * (grp ** 2).sum(0))
        return bs[k], se
    se_hat = np.sqrt(corr * (np.add.reduceat(u * e, starts) ** 2).sum())
    # unrestricted: percentile-t interval
    bk, se = t_stats(Xs @ b[:, None] + v * e[:, None])
    t_u = (bk - b[k]) / se
    lo, hi = np.percentile(t_u, [2.5, 97.5])
    ci = [float(b[k] - hi * se_hat), float(b[k] - lo * se_hat)]
    # null-imposed p-value
    Xr = np.delete(Xs, k, axis=1)
    br, _, er = ols(Xr, ys)
    bk0, se0 = t_stats((Xr @ br)[:, None] + v * er[:, None])
    t_hat = b[k] / se_hat
    pval = (1.0 + np.sum(np.abs(bk0 / se0) >= abs(t_hat))) / (B + 1.0)
    return {"ci95PercentileT": ci, "pValueNullImposed": float(pval), "nDraws": int(B), "weights": "Rademacher by cluster", "seed": seed}


def boot_weights(n_blocks, B=N_BOOT, seed=SEED):
    return np.random.default_rng(seed).multinomial(n_blocks, np.ones(n_blocks) / n_blocks, size=B).astype(float)


def pairs_block_ci(X, y, blocks, k, B=N_BOOT, seed=SEED):
    """Percentile 95 % interval of beta_k resampling whole blocks (days or weeks) with replacement; per-block X'X and X'y (sufficient statistics), singular draws skipped."""
    inv, nb = _codes(blocks)
    p = X.shape[1]
    XX, Xy = np.zeros((nb, p, p)), np.zeros((nb, p))
    np.add.at(XX, inv, X[:, :, None] * X[:, None, :])
    np.add.at(Xy, inv, X * y[:, None])
    est, skipped = [], 0
    for w in boot_weights(nb, B, seed):
        A = np.tensordot(w, XX, 1)
        if np.linalg.matrix_rank(A) < p:
            skipped += 1
            continue
        est.append(np.linalg.solve(A, np.tensordot(w, Xy, 1))[k])
    lo, hi = np.percentile(est, [2.5, 97.5])
    return {"ci95": [float(lo), float(hi)], "nBlocks": int(nb), "nDraws": int(len(est)), "skippedSingular": int(skipped), "fewBlocks": bool(nb < 10)}


def min_effect80(se, df):
    """Slope size that a two-sided 5 % test flags with probability 0.8 given the observed standard error."""
    if not np.isfinite(df) or df <= 0:
        return float((stats.norm.ppf(0.975) + stats.norm.ppf(POWER)) * se)
    return float((stats.t.ppf(0.975, df) + stats.t.ppf(POWER, df)) * se)


def week_blocks(dates):
    iso = pd.to_datetime(pd.Series(dates)).dt.isocalendar()
    return (iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)).to_numpy()


# ------------------------------------------------------------------------------------------------ trend slopes
def _design(dm, ycol, covars, icol):
    import degradation_trends as DT
    d = DT._prep(dm, ycol, icol=icol)
    use = DT._covars_present(d, covars)
    dd = d.dropna(subset=list(use)) if use else d
    X = np.column_stack([np.ones(len(dd)), dd["months"].to_numpy()] + [dd[c].to_numpy(float) for c in use])
    return dd, X, dd["y"].to_numpy(float), use


CR1_REFERENCE_NOTE = ("ci95NormalAsReleased is the normal-reference interval, the released convention before M473; the released interval is ci95T_Gminus1 (t reference, df = G-1), "
                      "the reference the equivalence test already used; kept as the history of the convention, not a second released interval")


def slope_block(dd, X, y, use, B=N_BOOT, seed=SEED, delta=None, spread=False):
    k = 1
    days = dd["day"].to_numpy()
    b, se1, G, n, p = cr1(X, y, days, k)
    b2, se2, df2, flags = cr2(X, y, days, k)
    t1 = stats.t.ppf(0.975, G - 1)
    out = {"n": int(n), "nDays": int(G), "formula": "y ~ months" + "".join(" + " + c for c in use),
           "cr1": {"slope": b, "se": se1, "ci95NormalAsReleased": [b - stats.norm.ppf(0.975) * se1, b + stats.norm.ppf(0.975) * se1], "ci95T_Gminus1": [b - t1 * se1, b + t1 * se1], "df": G - 1, "referenceNote": CR1_REFERENCE_NOTE},
           "cr2": {"slope": b2, "se": se2, "df": df2, "ci95T": [b2 - stats.t.ppf(0.975, df2) * se2, b2 + stats.t.ppf(0.975, df2) * se2], **flags},
           "wildClusterBootstrapT": wild_cluster(X, y, days, k, B, seed),
           "dayClusterPairsBootstrap": pairs_block_ci(X, y, days, k, B, seed),
           "weekBlockPairsBootstrap": pairs_block_ci(X, y, week_blocks(dd["date"]), k, B, seed),
           "minEffect80": {"cr1": min_effect80(se1, G - 1), "cr2": min_effect80(se2, df2),
                           "definition": "slope size that a two-sided 5 % test flags with probability 0.8 at the observed standard error; design-conditional, shown beside the zero-slope test only"}}
    if delta is not None:
        import degradation_trends as DT
        out["tostSensitivityCR2"] = {**DT._tost(b2, se2, delta, df=df2), "note": "sensitivity only: the released equivalence decision (cluster-robust OLS, t(G-1)) is unchanged; same frozen bound"}
    if spread:
        wk = week_blocks(dd["date"])
        runs = [(wild_cluster(X, y, days, k, B, s), pairs_block_ci(X, y, days, k, B, s), pairs_block_ci(X, y, wk, k, B, s)) for s in SEED_SPREAD]
        rg = lambda vals: [float(min(vals)), float(max(vals))]
        out["seedSpread"] = {"seeds": list(SEED_SPREAD), "wildPValueRange": rg([r[0]["pValueNullImposed"] for r in runs]),
                             "wildCiLowerRange": rg([r[0]["ci95PercentileT"][0] for r in runs]), "wildCiUpperRange": rg([r[0]["ci95PercentileT"][1] for r in runs]),
                             "dayPairsLowerRange": rg([r[1]["ci95"][0] for r in runs]), "dayPairsUpperRange": rg([r[1]["ci95"][1] for r in runs]),
                             "weekBlockLowerRange": rg([r[2]["ci95"][0] for r in runs]), "weekBlockUpperRange": rg([r[2]["ci95"][1] for r in runs]),
                             "note": "Monte Carlo spread of the bootstrap quantities over the listed seeds (same draws); a bound or p-value that crosses a threshold within this range does not discriminate"}
    return out


def trend_series(dm, ycol, covars, icol, B=N_BOOT, delta=None):
    dd, X, y, use = _design(dm, ycol, covars, icol)
    if len(dd) < 20:
        return {"evaluable": False, "n": int(len(dd))}
    out = slope_block(dd, X, y, use, B, delta=delta, spread=True)
    reg = dd["I_sample_period_s"].map(lambda v: None if pd.isna(v) else ("fast" if v < FAST_S else "slow")) if "I_sample_period_s" in dd.columns else None
    out["byLoggingRegime"] = {}
    if reg is not None:
        for name in ("fast", "slow"):
            m = (reg == name).to_numpy()
            if m.sum() >= 20 and dd.loc[m, "day"].nunique() >= 5:
                out["byLoggingRegime"][name] = slope_block(dd[m], X[m], y[m], use, B)
    return out


# ------------------------------------------------------------------------------------------------ thesis KPIs
def weighted_median(values, W_rows):
    """Median of `values` under integer row weights W_rows (B x n): equals np.median(values) for unit weights."""
    o = np.argsort(values, kind="stable")
    v = np.asarray(values)[o]
    cum = np.cumsum(W_rows[:, o], axis=1)
    T = cum[:, -1]
    lo = (cum >= np.floor((T + 1) / 2.0)[:, None]).argmax(axis=1)
    hi = (cum >= (np.floor(T / 2.0) + 1)[:, None]).argmax(axis=1)
    return 0.5 * (v[lo] + v[hi])


def _kpi_ci(kind, num, den, blocks, B, seed):
    inv, nb = _codes(blocks)
    W = boot_weights(nb, B, seed)
    if kind == "ratio":
        sn, sd = np.bincount(inv, weights=num, minlength=nb), np.bincount(inv, weights=den, minlength=nb)
        stat = (W @ sn) / (W @ sd)
    elif kind == "absratio":
        sn, sd = np.bincount(inv, weights=num, minlength=nb), np.bincount(inv, weights=den, minlength=nb)
        stat = np.abs(W @ sn) / (W @ sd)
    else:                                                               # median over drives of `num`
        stat = weighted_median(num, W[:, inv])
    lo, hi = np.percentile(stat, [2.5, 97.5])
    return [float(lo), float(hi)]


def kpis(dm, B=N_BOOT, seed=SEED):
    flag = dm["ens_outlier_v2"].map(lambda v: str(v).strip().lower() == "true")
    d = dm[~flag].copy()
    days = d["date"].astype(str).to_numpy()
    weeks = week_blocks(d["date"])
    out = {}

    def add(name, kind, num, den, mask, extra=None):
        m = mask.to_numpy()
        n_ = days[m]
        if kind == "ratio":
            est = float(num[m].sum() / den[m].sum())
        elif kind == "absratio":
            est = float(abs(num[m].sum()) / den[m].sum())
        else:
            est = float(np.median(num[m]))
        dci = _kpi_ci(kind, num[m], None if den is None else den[m], n_, B, seed)
        wci = _kpi_ci(kind, num[m], None if den is None else den[m], weeks[m], B, seed)
        out[name] = {"estimate": est, "n": int(m.sum()), "nDays": int(len(set(n_))), "nWeeks": int(len(set(weeks[m]))), "dayClusterCI95": dci, "weekBlockCI95": wci,
                     "widthRatioWeekOverDay": float((wci[1] - wci[0]) / (dci[1] - dci[0])) if dci[1] > dci[0] else None, **(extra or {})}
    thr, dis, net, netraw = (d[c].to_numpy(float) for c in ("gross_throughput_kwh", "gross_discharge_kwh", "net_draw_kwh_corr", "net_draw_kwh"))
    ok = d["gross_throughput_kwh"].notna() & d["gross_discharge_kwh"].notna() & d["net_draw_kwh_corr"].notna() & (d["gross_throughput_kwh"] > 0)
    add("K1_throughputOverDischarge", "ratio", np.nan_to_num(thr), np.nan_to_num(dis), ok, {"definition": "sum(gross throughput) / sum(gross discharge) over the eligible drives"})
    add("K2_netShare_corrected", "absratio", np.nan_to_num(net), np.nan_to_num(thr), ok, {"definition": "|sum(offset-adjusted net draw)| / sum(gross throughput)"})
    add("K2raw_netShare_uncorrected", "absratio", np.nan_to_num(netraw), np.nan_to_num(thr), ok, {"definition": "|sum(net draw)| / sum(gross throughput), before the offset adjustment"})
    band = d["soc_band"].to_numpy(float)
    add("K3_socBandMedianPp", "median", np.nan_to_num(band), None, d["soc_band"].notna(), {"definition": "median over drives of the per-drive SoC band (pp)"})
    pk = d["peak_discharge_kw"].to_numpy(float)
    add("K4_peakDischargeMedianKw", "median", np.nan_to_num(pk), None, d["peak_discharge_kw"].notna(), {"definition": "median over drives of the per-drive peak discharge power (kW)"})
    share = np.where(thr > 0, np.abs(net) / np.where(thr > 0, thr, 1), np.nan)
    add("K5_perDriveNetShareMedian", "median", np.nan_to_num(share), None, ok, {"definition": "median over drives of |offset-adjusted net| / gross throughput"})
    return out


# ------------------------------------------------------------------------------------------------ block and stage
def build(dm, B=N_BOOT, released=None):
    dl = lambda key: ((released or {}).get(key) or {}).get("releasedEquivalence", {}).get("delta")
    kp = kpis(dm, B)
    ratio_w = [v["widthRatioWeekOverDay"] for n, v in kp.items() if n.startswith(("K1", "K2"))]
    median_w = [v["widthRatioWeekOverDay"] for n, v in kp.items() if n.startswith(("K3", "K4", "K5"))]
    return {"_provenance": "GENERATED by tools/dependence_sensitivity.py (M406); do not hand-edit. Additive block: the released estimators and the TOST decision are unchanged.",
            "methodVersion": METHOD_VERSION, "resampling": "calendar day = cluster; ISO calendar week = block; percentile bootstrap, seed %d, %d draws; Rademacher weights by cluster for the wild bootstrap" % (SEED, B),
            "thesisKpis": kp,
            "kpiWidthRatioWeekOverDay": {"corpusRatios": [min(ratio_w), max(ratio_w)], "driveMedians": [min(median_w), max(median_w)],
                                         "note": "the week-block interval is the dependence-conservative one (residual day-to-day autocorrelation known in advance); the KPI intervals describe precision, they do not test the thesis"},
            "trendSlopes": {"cellSpread": trend_series(dm, "cell_spread_loaded_p95_mv", ("T", "I"), "peak_I_discharge", B, dl("cellSpread")),
                            "resistanceVreg": trend_series(dm, "vreg_R_pack_mohm", ("T", "I"), "vreg_I_p95_A", B, dl("resistanceVreg"))},
            "reportingOrder": ["cr1 (released interval, the reference)", "cr2", "wildClusterBootstrapT", "dayClusterPairsBootstrap", "weekBlockPairsBootstrap"],
            "reportingRule": "all procedures are shown in this fixed order with the same format; no single interval is designated primary and no envelope is formed; disagreement between procedures is reported, not tuned away",
            "reading": "sensitivities of conditional intervals to the choice of resampling unit and to small-cluster bias; they do not remove season, logging-regime or calendar-drift confounding and do not change the released estimators",
            "limits": ["week blocks address serial dependence at the weekly scale only and about 20 weeks make the block bootstrap coarse", "CR2 and the wild bootstrap are small-cluster corrections, not a model of dependence",
                       "the trend slopes are conditional on the design y ~ months + T + I", "one vehicle, May-October data"]}


def _round(o, nd=5):
    if isinstance(o, dict):
        return {k: _round(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_round(v, nd) for v in o]
    if isinstance(o, (float, np.floating)):
        return None if not np.isfinite(o) else round(float(o), nd)
    if isinstance(o, np.integer):
        return int(o)
    return o


def _paths(a, b, p=""):
    if isinstance(a, dict) and isinstance(b, dict):
        return [x for k in sorted(set(a) | set(b)) for x in (_paths(a.get(k), b.get(k), "%s/%s" % (p, k)) if (k in a and k in b) else ["%s/%s" % (p, k)])]
    return [] if json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True) else [p]


ALLOWED = ["/dependenceSensitivity", "/_artifactStamps/dependenceSensitivity"]


def splice(A, blk, master_md5="", now=None):
    new = copy.deepcopy(A)
    new["dependenceSensitivity"] = blk
    old = (A.get("_artifactStamps") or {}).get("dependenceSensitivity")
    if old and A.get("dependenceSensitivity") == blk and old.get("corpusHash") == master_md5:
        new["_artifactStamps"]["dependenceSensitivity"] = old
    else:
        st = copy.deepcopy(A["_artifactStamps"]["fuelContract"])
        st.update(corpusHash=master_md5, generatedAt=(now or datetime.datetime.now(datetime.timezone.utc)).isoformat(), computationStatus="computed",
                  computationStatusNote="M406: derived by tools/dependence_sensitivity.py from drive_master.csv; additive sensitivities (CR2, wild cluster bootstrap, week-block bootstrap, minimum effect with 80 % power); the released estimators are unchanged; not M299-reproducible.",
                  upstreamHashes={"driveMasterMd5": master_md5})
        st.pop("carriedForward", None)
        new["_artifactStamps"]["dependenceSensitivity"] = st
    ch = _paths(A, new)
    return new, ch, [c for c in ch if not any(c == a_ or c.startswith(a_ + "/") for a_ in ALLOWED)]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    raw = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    A0 = json.loads(raw)
    blk = _round(build(dm, released=A0.get("degradationTrends")))
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    new, changed, bad = splice(A0, blk, md5)
    cs = blk["trendSlopes"]["cellSpread"]
    print(json.dumps({"nChanged": len(changed), "outsideAllowList": bad, "cellSpreadCR1": cs["cr1"]["slope"], "cellSpreadCR2SE": cs["cr2"]["se"], "wildP": cs["wildClusterBootstrapT"]["pValueNullImposed"]}))
    if bad:
        return 1
    if "--dry-run" not in argv and changed:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
