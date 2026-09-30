#!/usr/bin/env python3
"""Corpus-refit recalibration gate (Director decision, approved by Andrii 2026-09-30).

Adding drives legitimately moves two corpus-wide refits on EXISTING rows:
  * offset cascade (10 cols): the ratio-of-sums SoC-anchored current offset I_offset_A (and the two-pass I_offset_2p_A) and
    everything computed from it (compute_drive_summary_v6._v5_postprocess_master / postprocess_master M24);
  * spread-model refit (2 cols): M15 OLS and M19 Huber regression of loaded cell spread on T_pack and peak discharge current.
Policy: exactly RECAL_COLS may change on pre-existing rows; any other column changing is a HARD FAIL (implied_offset_A_drive is
per-drive and must stay invariant). Every change is quantified (n/max/median abs shift) and tested against a day-clustered
percentile bootstrap (seed 42, 4000 draws, calendar day = cluster) of the PRE-ingest estimate:
  soft flag : |new - old| > 0.25 * CI half-width
  hard flag : new value outside the old 95% CI; offsets: estimate from the new drives alone outside it (drift test);
              spread model (centred at old-median T_pack/I_peak): calibrated day-block null over distinct blocks, rank p<=0.01 hard (only if >=99 blocks, else capped soft), p<0.05 soft
              (bT left out of the joint statistic and reported not_identifiable unless new-only T_pack IQR >= 0.5 x old IQR)
Hard flags stop the ingestion unless acknowledged (--ack-recalibration REASON) after blind audit + Director review.
Language: 'corpus-refit recalibration'; corrected energies are estimated / offset-corrected, never measured."""
import numpy as np
import pandas as pd

OFFSET_COLS = ["I_offset_A_applied", "offset_kwh_removed", "net_draw_kwh_corr", "energy_residual_kwh_corr",
               "net_draw_per100km_corr", "I_offset_2p_A_applied", "offset_2p_kwh_removed", "net_draw_kwh_corr2p",
               "energy_residual_kwh_corr2p", "net_draw_per100km_corr2p"]
SPREAD_COLS = ["cell_spread_loaded_p95_adj_mv", "cell_spread_loaded_p95_adj_hub_mv"]
RECAL_COLS = OFFSET_COLS + SPREAD_COLS
N_BOOT, SEED, SOFT_FRAC = 4000, 42, 0.25


def _hours(d):
    h = d["integr_time_h"] if "integr_time_h" in d.columns else pd.Series(np.nan, index=d.index)
    return h.fillna(d["duration_s"] / 3600.0)


def _offset_parts(d, two_pass):
    """Per-row numerator/denominator of I_offset = sum(resid)*1000 / sum(V*h) on the eligible rows."""
    m = d["energy_residual_kwh"].notna() & d["duration_s"].notna() & d["V_pack_median"].notna()
    if two_pass:
        m &= ~d["f_domain_2p"].fillna(False).astype(bool)
    h = _hours(d)
    num = (d["energy_residual_kwh"] * 1000.0).where(m, 0.0)
    den = (d["V_pack_median"] * h).where(m, 0.0)
    return num, den


def _boot_ratio(days, num, den, rng):
    g = pd.DataFrame({"d": days.values, "n": num.values, "v": den.values}).groupby("d").sum()
    n, v = g["n"].values, g["v"].values
    idx = rng.integers(0, len(g), size=(N_BOOT, len(g)))
    est = n[idx].sum(1) / v[idx].sum(1)
    return np.percentile(est, [2.5, 97.5]), float(n.sum() / v.sum())


def _spread_xy(d):
    return d.dropna(subset=["cell_spread_loaded_p95_mv", "T_pack_mean_avg", "peak_I_discharge"])


def _ols(s, tref, iref):
    """Centred OLS: b0 = spread at (tref, iref). Excludes nothing (as the M15 pipeline fit)."""
    X = np.column_stack([np.ones(len(s)), s["T_pack_mean_avg"].values - tref, s["peak_I_discharge"].values - iref])
    return np.linalg.lstsq(X, s["cell_spread_loaded_p95_mv"].values, rcond=None)[0]


def _huber(s, tref, iref):
    """Centred Huber. Exclusion = canonical ens_outlier_v2 (Director 2026-09-30; the M19 pipeline fit still keys on ens_outlier,
    so this diagnostic fit differs from the published adj_hub column by design; aligning the pipeline is a separate decision)."""
    from sklearn.linear_model import HuberRegressor
    col = "ens_outlier_v2" if "ens_outlier_v2" in s.columns else "ens_outlier"
    keep = ~s[col].fillna(False).astype(bool).values
    c = s[keep]
    h = HuberRegressor(epsilon=1.35, max_iter=500).fit(
        np.column_stack([c["T_pack_mean_avg"].values - tref, c["peak_I_discharge"].values - iref]),
        c["cell_spread_loaded_p95_mv"].values)
    return np.array([h.intercept_, *h.coef_])


def _block_null(so, fit, n_days, min_drives, bo, bnew, cols, rng):
    """Calibrated drift test: null = fits on random contiguous old-corpus day-blocks with the same number of observed days as the
    new batch (and >= min_drives drives); statistic = Mahalanobis distance of (fit - old fit) under the block-null covariance;
    p = share of null draws with distance >= observed (Director 2026-09-30)."""
    days = np.array(sorted(so["date"].astype(str).unique()))
    dstr = so["date"].astype(str).values
    fits = []
    for k in range(0, len(days) - n_days + 1):
        blk = so[np.isin(dstr, days[k:k + n_days])]
        if len(blk) >= min_drives:
            try:
                fits.append(fit(blk))
            except Exception:
                pass
    if len(fits) < 10:
        return {"error": f"only {len(fits)} valid blocks", "p": None}
    F = np.array(fits)[:, cols]                       # distinct blocks, NO resampling (resampling gave a spurious p resolution)
    S = np.linalg.pinv(np.cov(F, rowvar=False).reshape(len(cols), len(cols)))
    Dn = F - bo[cols]
    null = np.einsum("ij,jk,ik->i", Dn, S, Dn)
    dn = bnew[cols] - bo[cols]
    obs = float(dn @ S @ dn)
    nb = len(F)
    span = len(days)
    return {"n_valid_blocks": nb, "n_eff_blocks_approx": float(span / n_days), "block_days": int(n_days), "min_drives": int(min_drives),
            "mahalanobis_obs": obs, "null_median": float(np.median(null)),
            "p": float((1 + np.sum(null >= obs)) / (nb + 1)), "p_min": float(1.0 / (nb + 1)),
            "note": "rank p over distinct overlapping blocks; hard flag only if n_valid_blocks >= 99 and p <= 0.01, else capped at soft"}


def _boot_coefs(s, fit, rng):
    days = s["date"].astype(str).values
    ud = np.unique(days)
    groups = [np.where(days == u)[0] for u in ud]
    out = []
    for _ in range(N_BOOT):
        pick = rng.integers(0, len(ud), len(ud))
        idx = np.concatenate([groups[k] for k in pick])
        try:
            out.append(fit(s.iloc[idx]))
        except Exception:
            continue
    return np.percentile(np.array(out), [2.5, 97.5], axis=0)


def _judge(name, old, new, only_new, ci, drift=True):
    lo, hi = float(ci[0]), float(ci[1])
    half = (hi - lo) / 2.0
    r = {"quantity": name, "old": float(old), "new": float(new),
         "new_drives_only": None if only_new is None else float(only_new),
         "old_ci95": [lo, hi], "shift": float(new - old),
         "shift_over_half_width": float(abs(new - old) / half) if half > 0 else None}
    r["soft_flag"] = bool(half > 0 and abs(new - old) > SOFT_FRAC * half)
    r["hard_new_outside_old_ci"] = bool(not (lo <= new <= hi))
    # drift=False for the spread coefficients: the new-only-vs-full-corpus-CI rule is uncalibrated at n_new << n_old (replaced by _block_null)
    r["hard_drift_new_only_outside_old_ci"] = bool(drift and only_new is not None and not (lo <= only_new <= hi))
    return r


def evaluate(dm_old, dm_new, diffs_before):
    """dm_old/dm_new: typed master frames. diffs_before: {col: n_rows_changed} on pre-existing rows (CSV-text comparison).
    Returns (report, hard_flags). Raises nothing; the caller decides."""
    rng = np.random.default_rng(SEED)
    is_old = dm_new["file"].astype(str).isin(set(dm_old["file"].astype(str)))
    new_rows, old_in_new = dm_new[~is_old], dm_new[is_old]
    rep = {"method": f"day-clustered percentile bootstrap, seed {SEED}, {N_BOOT} draws, calendar day = cluster; ratio of sums",
           "n_new_drives": int(len(new_rows)), "n_old_drives": int(len(dm_old)),
           "n_days_old": int(dm_old["date"].astype(str).nunique()), "columns_changed_rows": diffs_before, "tests": []}
    for label, col, tp in (("I_offset_A", "I_offset_A_applied", False), ("I_offset_2p_A", "I_offset_2p_A_applied", True)):
        num, den = _offset_parts(dm_old, tp)
        ci, est = _boot_ratio(dm_old["date"].astype(str), num, den, rng)
        old = float(dm_old[col].dropna().iloc[0])
        new = float(dm_new[col].dropna().iloc[0])
        nn, nd = _offset_parts(new_rows, tp)
        only = float(nn.sum() / nd.sum()) if nd.sum() > 0 else None
        t = _judge(label, old, new, only, ci)
        t["recomputed_old_point_estimate"] = est          # sanity: reproduces the stored old value up to rounding
        rep["tests"].append(t)
    so, sn, snew = _spread_xy(dm_old), _spread_xy(dm_new), _spread_xy(new_rows)
    tref, iref = float(so["T_pack_mean_avg"].median()), float(so["peak_I_discharge"].median())
    iqr = lambda x: float(np.percentile(x, 75) - np.percentile(x, 25))
    q_old, q_new = iqr(so["T_pack_mean_avg"]), iqr(snew["T_pack_mean_avg"]) if len(snew) else 0.0
    ident = bool(q_new >= 0.5 * q_old)
    rep["spread_identifiability"] = {"T_pack_old": [float(so["T_pack_mean_avg"].min()), q_old, float(so["T_pack_mean_avg"].max())],
                                     "T_pack_new": [float(snew["T_pack_mean_avg"].min()), q_new, float(snew["T_pack_mean_avg"].max())],
                                     "fields": "[min, IQR, max]", "bT_identifiable_new_only": ident,
                                     "T_ref_old_median": tref, "I_ref_old_median": iref}
    cols = [0, 1, 2] if ident else [0, 2]          # bT reported 'not_identifiable' and left out of the joint statistic
    for label, fit0 in (("spread_OLS", _ols), ("spread_Huber", _huber)):
        fit = lambda s, f=fit0: f(s, tref, iref)
        try:
            ci = _boot_coefs(so, fit, rng)
            bo, bn = fit(so), fit(sn)
            bnew = fit(snew) if len(snew) >= 8 else None
            nd_new = int(snew["date"].astype(str).nunique())
            nb = _block_null(so, fit, nd_new, len(snew), bo, bnew, cols, rng) if bnew is not None else {"error": "new-only n<8", "p": None}
        except Exception as ex:
            rep["tests"].append({"quantity": label, "error": repr(ex), "hard_new_outside_old_ci": True})
            continue
        for k, nm in enumerate(["b0", "bT", "bI"]):
            tt = _judge(f"{label}.{nm}(centred)", bo[k], bn[k], None if bnew is None else bnew[k], ci[:, k], drift=False)
            if nm == "bT" and not ident:
                tt["status"] = "not_identifiable_new_only"
            rep["tests"].append(tt)
        p = nb.get("p")
        jt = {"quantity": f"{label}.joint_block_null", "coefficients_in_statistic": [["b0", "bT", "bI"][c] for c in cols], **nb}
        nvb = nb.get("n_valid_blocks", 0)
        jt["hard_drift_block_null"] = bool(p is None or (nvb >= 99 and p <= 0.01))
        jt["soft_flag"] = bool(p is not None and p < 0.05 and not jt["hard_drift_block_null"])
        rep["tests"].append(jt)
    old_idx = dm_old.set_index(dm_old["file"].astype(str))
    cur = old_in_new.set_index(old_in_new["file"].astype(str))
    shifts = {}
    for c in diffs_before:
        a = pd.to_numeric(old_idx[c], errors="coerce")
        b = pd.to_numeric(cur[c].reindex(old_idx.index), errors="coerce")
        dlt = (b - a).abs().dropna()
        dlt = dlt[dlt > 0]
        shifts[c] = {"n_changed": int(diffs_before[c]), "max_abs_shift": float(dlt.max()) if len(dlt) else None,
                     "median_abs_shift": float(dlt.median()) if len(dlt) else None}
    rep["per_column_shift_preexisting"] = shifts
    hard = [t["quantity"] for t in rep["tests"] if t.get("hard_new_outside_old_ci") or t.get("hard_drift_new_only_outside_old_ci") or t.get("hard_drift_block_null")]
    rep["soft_flags"] = [t["quantity"] for t in rep["tests"] if t.get("soft_flag")]
    rep["hard_flags"] = hard
    rep["note"] = ("corpus-refit recalibration (offset cascade + spread-model refit); corrected energies are estimated/offset-corrected, "
                   "never measured. KPI delta vs S.* keys and claim_register figures is produced by delta_report.py / claim-check.")
    return rep, hard
