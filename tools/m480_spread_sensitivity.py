#!/usr/bin/env python3
"""M480 (analyses/M480_spec.md Rev 2, pre-registered): sensitivity of the released cell-spread slope to drive-level logger timing, loaded support and loading-mix proxies from the M479
sidecar (timing_support.csv), plus regime strata, a support subset, covariate drift, a cutoff series and influence. Question: is the positive conditional slope explained by the TESTED
drive-level proxies? It does not test physical degradation, pair-level synchronization or restricted-condition outcomes (M480b). Nothing here changes the released estimator, the master, the payload
or the dashboard; the verdict is provisional until M480b and is not reportable on its own.
Design = the released model (degradation_trends._prep / _covars_present: cell_spread_loaded_p95_mv ~ months + T_pack_mean_avg + peak_I_discharge, ens_outlier_v2-clean, cluster = calendar day, CR1
interval with the t(G-1) reference) plus covariate blocks. Companions reuse tools/dependence_sensitivity.py (wild_cluster, cr2, pairs_block_ci) and tools/serial_dependence.py (moving_block).
Deviation recorded (spec said Webb weights): the existing wild_cluster code path uses Rademacher weights by cluster (G is about 117, far above the few-cluster regime where Webb weights matter).
Usage: python tools/m480_spread_sensitivity.py [--out analyses/M480_results.json] [--boot 4000]"""
import argparse, hashlib, json, os, sys
import numpy as np
import pandas as pd
from scipy import stats

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p_ in (ROOT, os.path.dirname(os.path.abspath(__file__))):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import dependence_sensitivity as DS      # noqa: E402
import serial_dependence as SD           # noqa: E402

METHOD_VERSION = 1
YCOL, TCOL, ICOL = "cell_spread_loaded_p95_mv", "T_pack_mean_avg", "peak_I_discharge"
S0_TOL = 0.002                            # known-answer: S0 must reproduce the released slope to this (mV/month)
HALF, MIN_ADJ = 0.5, 3                    # frozen conventions of the decision rule
SE_RATIO_MAX, VIF_MAX = 2.0, 10.0         # precision gate
FAST_S = 1.05
CUTOFFS = ("2026-07-31", "2026-08-31", "2026-09-30")
SPECS = {                                  # added columns (after transforms), frozen in the spec
    "S1": ["i_dt_q50", "i_row_cov"],
    "S2": ["log1p_n_loaded", "i_dt_iqr_ratio", "gt3_ind", "log1p_gap20_s", "vmax_dt_q50", "off_abs_p95_ms", "cur_age_p95_ms"],
    "S3": ["i_abs_med", "i_abs_p95", "soc_med", "chg_share"],
}
SPECS["S4"] = SPECS["S2"] + SPECS["S3"]
DRIFT_COLS = sorted({c for v in SPECS.values() for c in v})


# ------------------------------------------------------------------------------------------------ frame
def add_transforms(d):
    """Frozen transforms (spec Rev 2): log1p(n_loaded), log1p(i_gap20_s), indicator i_frac_dt_gt3s > 0, charge share; no winsorizing."""
    d = d.copy()
    d["log1p_n_loaded"] = np.log1p(pd.to_numeric(d["n_loaded"], errors="coerce"))
    d["log1p_gap20_s"] = np.log1p(pd.to_numeric(d["i_gap20_s"], errors="coerce"))
    g = pd.to_numeric(d["i_frac_dt_gt3s"], errors="coerce")
    d["gt3_ind"] = np.where(g.isna(), np.nan, (g > 0).astype(float))
    nl = pd.to_numeric(d["n_loaded"], errors="coerce")
    d["chg_share"] = np.where(nl > 0, pd.to_numeric(d["n_loaded_chg"], errors="coerce") / nl, np.nan)
    return d


def build_frame(dm, side):
    """The released design rows (canonical-clean, outcome, T and I present) joined with the sidecar by file."""
    import degradation_trends as DT
    d = DT._prep(dm, YCOL, tcol=TCOL, icol=ICOL)
    use = DT._covars_present(d, ("T", "I"))
    d = d.dropna(subset=list(use)).reset_index(drop=True)
    cols = ["file"] + [c for c in side.columns if c not in ("file", "date")]
    d = d.merge(side[cols], on="file", how="left", suffixes=("", "_ts"))
    d["regime"] = d["I_sample_period_s"].map(lambda v: None if pd.isna(v) else ("fast" if v < FAST_S else "slow"))
    return add_transforms(d)


# ------------------------------------------------------------------------------------------------ estimation
def design(dd, cols):
    """X = [1, months, T, I] + standardised added columns (scaling is for numerics only; the months slope is unchanged by it)."""
    base = [np.ones(len(dd)), dd["months"].to_numpy(float), dd["T"].to_numpy(float), dd["I"].to_numpy(float)]
    add = []
    for c in cols:
        v = dd[c].to_numpy(float)
        sd = v.std()
        add.append((v - v.mean()) / sd if sd > 0 else v - v.mean())
    return np.column_stack(base + add), dd["y"].to_numpy(float)


def _r2(y, Z):
    if Z.shape[1] == 0:
        return 0.0
    b = np.linalg.lstsq(Z, y, rcond=None)[0]
    res = y - Z @ b
    tot = ((y - y.mean()) ** 2).sum()
    return 0.0 if tot <= 0 else float(1.0 - (res ** 2).sum() / tot)


def months_diagnostics(X):
    """VIF of months (all other columns incl. the constant), partial R2 of months on the added block after the base controls, and the number of days that carry half of the leverage on months."""
    m = X[:, 1]
    others = np.delete(X, 1, axis=1)
    r2 = _r2(m, others)
    vif = float(1.0 / (1.0 - r2)) if r2 < 1 - 1e-12 else float("inf")
    base, blk = X[:, [0, 2, 3]], X[:, 4:]
    prt = None
    if blk.shape[1]:
        rm = m - base @ np.linalg.lstsq(base, m, rcond=None)[0]
        rb = blk - base @ np.linalg.lstsq(base, blk, rcond=None)[0]
        prt = _r2(rm, rb)
    return vif, prt


def leverage_days(X, groups, share=0.5):
    """Number of calendar days that together carry `share` of the leverage on months (squared months residual after all other columns)."""
    m = X[:, 1]
    others = np.delete(X, 1, axis=1)
    rm = m - others @ np.linalg.lstsq(others, m, rcond=None)[0]
    s = pd.Series(rm ** 2).groupby(np.asarray(groups)).sum().sort_values(ascending=False)
    c = s.cumsum() / s.sum()
    return int((c < share).sum() + 1), int(len(s))


def fit(dd, cols, B, full=False):
    """One specification: CR1 (t(G-1)) slope/interval, diagnostics; full=True adds the wild cluster bootstrap-t and CR2 (and the caller adds pairs / moving-block rows)."""
    X, y = design(dd, cols)
    days = dd["day"].to_numpy()
    b, se, G, n, p = DS.cr1(X, y, days, 1)
    t1 = stats.t.ppf(0.975, G - 1)
    vif, prt = months_diagnostics(X)
    nl, nd = leverage_days(X, days)
    out = {"n_drives": int(n), "n_days": int(G), "columns": list(cols), "slope": b, "se": se, "ci95": [b - t1 * se, b + t1 * se], "ciReference": "t(df=%d)" % (G - 1),
           "vif_months": vif, "partial_r2_months_on_block": prt, "days_for_half_leverage": nl, "months_span": float(dd["months"].max() - dd["months"].min())}
    if full:
        b2, se2, df2, fl = DS.cr2(X, y, days, 1)
        out["cr2"] = {"slope": b2, "se": se2, "df": df2, "ci95T": [b2 - stats.t.ppf(0.975, df2) * se2, b2 + stats.t.ppf(0.975, df2) * se2], **fl}
        out["wildClusterBootstrapT"] = DS.wild_cluster(X, y, days, 1, B, 42)
    return out, X, y


def label(spec, ref_se, vif_max=VIF_MAX, ratio_max=SE_RATIO_MAX):
    """Precision gate: imprecise if the cluster SE exceeds twice the reference SE or the VIF of months exceeds 10."""
    ratio = spec["se"] / ref_se if ref_se else float("inf")
    spec["se_ratio_vs_ref"] = ratio
    spec["label"] = "imprecise" if (ratio > ratio_max or not np.isfinite(spec["vif_months"]) or spec["vif_months"] > vif_max) else "ok"
    return spec["label"]


def verdict(adj):
    """Pure decision rule (spec Rev 2). adj: dicts for S1-S4 with slope, ci95, s0 (S0|rows slope on the same rows), label. Returns one of supported_provisional / not_supported / attenuated_inconclusive / not_evaluable."""
    ok = [s for s in adj if s["label"] != "imprecise"]
    if any(not (s["s0"] > 0) for s in ok):
        return "not_evaluable"
    below_half = [s for s in ok if s["slope"] < HALF * s["s0"] and s["ci95"][1] < s["s0"]]
    neg = [s for s in ok if s["slope"] < 0 and s["ci95"][1] < s["s0"]]
    if len(below_half) >= 2 or neg:
        return "not_supported"
    if len(ok) >= MIN_ADJ and all(s["slope"] > 0 and s["slope"] >= HALF * s["s0"] for s in ok) and sum(s["ci95"][0] > 0 for s in ok) >= 3:
        return "supported_provisional"
    return "attenuated_inconclusive"


# ------------------------------------------------------------------------------------------------ companions
def drift(dd):
    """Slope of each added covariate on calendar months, day-clustered (CR1, t(G-1)): does the logging regime or loading mix move with time?"""
    out = {}
    for c in DRIFT_COLS:
        m = dd[c].notna().to_numpy()
        if m.sum() < 20 or dd.loc[m, "day"].nunique() < 5:
            out[c] = None
            continue
        X = np.column_stack([np.ones(m.sum()), dd.loc[m, "months"].to_numpy(float)])
        b, se, G, n, p = DS.cr1(X, dd.loc[m, c].to_numpy(float), dd.loc[m, "day"].to_numpy(), 1)
        t1 = stats.t.ppf(0.975, G - 1)
        out[c] = {"slope_per_month": b, "ci95": [b - t1 * se, b + t1 * se], "n_drives": int(n), "n_days": int(G)}
    return out


def cutoff_series(dm, side, cuts, last_date):
    """S0 refitted on the drives dated up to each cutoff; plus leave-last-8-days-out. Cumulative refits reuse observations: no claim of persistence."""
    rows = []
    for c in list(cuts) + [last_date]:
        sub = dm[pd.to_datetime(dm["date"]) <= pd.Timestamp(c)]
        d = build_frame(sub, side)
        if len(d) < 20 or d["day"].nunique() < 5:
            rows.append({"cutoff": c, "evaluable": False, "n_drives": int(len(d))})
            continue
        s, _, _ = fit(d, [], 0)
        rows.append({"cutoff": c, "n_drives": s["n_drives"], "n_days": s["n_days"], "slope": s["slope"], "ci95": s["ci95"]})
    full = build_frame(dm, side)
    keep = sorted(full["day"].unique())[:-8]
    s, _, _ = fit(full[full["day"].isin(keep)], [], 0)
    rows.append({"cutoff": "leave_last_8_days_out", "n_drives": s["n_drives"], "n_days": s["n_days"], "slope": s["slope"], "ci95": s["ci95"]})
    return rows


def influence(dd):
    """Leave-one-day-out slope range and the slope without the three most influential days (descriptive)."""
    X, y = design(dd, [])
    days = dd["day"].to_numpy()
    full = np.linalg.lstsq(X, y, rcond=None)[0][1]
    loo = {}
    for g in np.unique(days):
        m = days != g
        loo[g] = np.linalg.lstsq(X[m], y[m], rcond=None)[0][1]
    top = sorted(loo, key=lambda g: -abs(loo[g] - full))[:3]
    m = ~np.isin(days, top)
    return {"slope_full": float(full), "loo_min": float(min(loo.values())), "loo_max": float(max(loo.values())), "top3_days": top,
            "slope_without_top3": float(np.linalg.lstsq(X[m], y[m], rcond=None)[0][1]), "n_days_after_dropping": int(len(np.unique(days[m])))}


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


# ------------------------------------------------------------------------------------------------ run
def analyse(frame, B, released=None):
    """All specifications on a design frame (columns: months, T, I, y, day, date, the sidecar columns, regime). Returns the results dict (without provenance)."""
    d0 = frame
    s0, X0, y0 = fit(d0, [], B, full=True)
    if released is not None:
        if abs(s0["slope"] - released["slope"]) > S0_TOL or s0["n_drives"] != released["nObs"] or s0["n_days"] != released["nDays"]:
            raise SystemExit("STOP: S0 does not reproduce the released model (slope %.4f vs %.4f, n %d vs %d, days %d vs %d)" % (s0["slope"], released["slope"], s0["n_drives"], released["nObs"], s0["n_days"], released["nDays"]))
    s0["label"] = "reference"
    res = {"S0": s0, "specs": {}}
    adj = []
    for name, cols in SPECS.items():
        rows = d0.dropna(subset=cols)
        sk, Xk, yk = fit(rows, cols, B, full=True)
        s0r, _, _ = fit(rows, [], 0)
        sk["rows_dropped_vs_S0"] = int(len(d0) - len(rows))
        sk["S0_on_rows"] = {"slope": s0r["slope"], "se": s0r["se"], "ci95": s0r["ci95"], "n_drives": s0r["n_drives"], "n_days": s0r["n_days"]}
        sk["slope_ratio_vs_S0_rows"] = sk["slope"] / s0r["slope"] if s0r["slope"] else None
        label(sk, s0r["se"])
        res["specs"][name] = sk
        adj.append({"slope": sk["slope"], "ci95": sk["ci95"], "s0": s0r["slope"], "label": sk["label"], "name": name})
    res["verdict"] = verdict(adj)
    res["verdictLabel"] = "provisional; pair-level test M480b pending" if res["verdict"] == "supported_provisional" else "see rule"
    # procedure dependence of the S0 and S4 models: day pairs bootstrap and the 7- and 14-day moving blocks
    t = SD.day_axis(d0["date"])
    res["S0"]["dayClusterPairsBootstrap"] = DS.pairs_block_ci(X0, y0, d0["day"].to_numpy(), 1, B, 42)
    res["S0"]["movingBlock"] = {"L%d" % L: SD.moving_block(X0, y0, t, L, B) for L in SD.BLOCK_L}
    r4 = d0.dropna(subset=SPECS["S4"])
    _, X4, y4 = fit(r4, SPECS["S4"], 0)
    t4 = SD.day_axis(r4["date"])
    res["specs"]["S4"]["dayClusterPairsBootstrap"] = DS.pairs_block_ci(X4, y4, r4["day"].to_numpy(), 1, B, 42)
    res["specs"]["S4"]["movingBlock"] = {"L%d" % L: SD.moving_block(X4, y4, t4, L, B) for L in SD.BLOCK_L}
    # strata (S5) and support subset (S6): reported, never in the verdict
    res["S5"] = {}
    for g in ("fast", "slow"):
        rr = d0[d0["regime"] == g]
        if len(rr) >= 20 and rr["day"].nunique() >= 5:
            sg, _, _ = fit(rr, [], B, full=True)
            label(sg, s0["se"])
            res["S5"][g] = sg
        else:
            res["S5"][g] = {"evaluable": False, "n_drives": int(len(rr))}
    res["S5"]["unknown_regime_drives_excluded"] = int(d0["regime"].isna().sum())
    sub = d0[(pd.to_numeric(d0["n_loaded"], errors="coerce") >= 30) & (pd.to_numeric(d0["n_episodes"], errors="coerce") >= 3)]
    if len(sub) >= 20 and sub["day"].nunique() >= 5:
        s6, _, _ = fit(sub, [], B, full=True)
        s6["rows_dropped_vs_S0"] = int(len(d0) - len(sub))
        s6["S0_on_rows"] = {"slope": s6["slope"], "se": s6["se"], "ci95": s6["ci95"], "n_drives": s6["n_drives"], "n_days": s6["n_days"],
                            "note": "S6 is the S0 model fitted on the support-subset rows, so S0 on these rows is this fit itself; ratio below is against the full-sample S0"}
        s6["slope_ratio_vs_S0_full"] = s6["slope"] / s0["slope"]
        label(s6, s0["se"])
        res["S6"] = s6
    else:
        res["S6"] = {"evaluable": False, "n_drives": int(len(sub))}
    # a within-regime slope at or below zero that passes the precision gate is stated beside the verdict
    res["strataAtOrBelowZeroPassingGate"] = [g for g in ("fast", "slow") if isinstance(res["S5"].get(g), dict) and res["S5"][g].get("label") == "ok" and res["S5"][g]["slope"] <= 0]
    res["drift"] = drift(d0)
    res["influence"] = influence(d0)
    res["correlation_i_abs_p95_vs_peak_I_discharge"] = float(d0[["i_abs_p95", "I"]].dropna().corr().iloc[0, 1])
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "analyses", "M480_results.json"))
    ap.add_argument("--boot", type=int, default=4000)
    a = ap.parse_args(argv)
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"), low_memory=False)
    side = pd.read_csv(os.path.join(ROOT, "timing_support.csv"), keep_default_na=False, na_values=[""], dtype={"raw_sha256": str})
    A = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
    released = A["degradationTrends"]["cellSpread"]["clusterRobustOLS"]
    frame = build_frame(dm, side)
    res = analyse(frame, a.boot, released)
    res["cutoffSeries"] = cutoff_series(dm, side, CUTOFFS, str(pd.to_datetime(dm["date"]).max().date()))
    res["deviations"] = ["wild cluster bootstrap uses the existing Rademacher-by-cluster code path (spec text said Webb weights; G is about 117)",
                         "precision-gate SE ratio for S5 and S6 is taken against the full-sample S0 SE (their rows differ from S0)"]
    res["method"] = {"version": METHOD_VERSION, "design": "OLS y ~ months + T + I + block; cluster = calendar day; CR1 interval t(G-1); wild cluster bootstrap-t and CR2 from tools/dependence_sensitivity.py; seed 42; %d draws" % a.boot,
                     "halfRule": HALF, "minAdjSpecs": MIN_ADJ, "seRatioMax": SE_RATIO_MAX, "vifMax": VIF_MAX}
    res["provenance"] = {"master_md5": hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest(), "sidecar_sha256": sha256(os.path.join(ROOT, "timing_support.csv")),
                         "script_sha256": sha256(os.path.abspath(__file__)), "spec_sha256": sha256(os.path.join(ROOT, "analyses", "M480_spec.md"))}
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=float)
        f.write("\n")
    print(json.dumps({"verdict": res["verdict"], "S0": [round(res["S0"]["slope"], 4), res["S0"]["n_drives"], res["S0"]["n_days"]]}))


if __name__ == "__main__":
    main()
