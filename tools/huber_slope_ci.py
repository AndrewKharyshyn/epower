"""Bootstrap intervals for the Huber-adjusted cell-spread trend (M317; spec analyses/M317_spec.md rev 2). Single source for the pipeline
(compute_summary_arrays._cell_health_trend), tools/record_spread_fit.py, the calibration run and the tests.

Objects
  primary  : second-stage HuberRegressor slope of the STORED adjusted series (rounded to 0.1 mV) on months, day-clustered percentile bootstrap, CONDITIONAL on the
             first-stage fit (the adjusted series is held fixed).
  S1       : two-stage: per draw refit the first-stage Huber (T, peak current; epsilon 1.35, max_iter 500) on the resampled kept rows, recompute I_ref from the resample
             (T_ref fixed), recompute every resampled row's adjusted value UNROUNDED, refit the second-stage slope.
  S2 / S2-S1 : the same two intervals with 7-day calendar BLOCKS as the resampling unit (serial correlation across days).
months = total_seconds / (30.4375 x 86400) since the first kept drive (this is the definition behind cellHealthTrend.huberSlopeMvPerMo).
Failed draws (exceptions) are dropped and counted; non-converged draws (sklearn ConvergenceWarning) are kept and counted separately; more than 1% of either kind makes the interval INCONCLUSIVE.
"""
import warnings
import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import HuberRegressor

MONTH_S = 30.4375 * 86400
SPREAD_T_REF = 25.0          # must equal compute_drive_summary_v6.SPREAD_T_REF (asserted by the tests)
T_COL, I_COL, Y_COL = "T_pack_mean_avg", "peak_I_discharge", "cell_spread_loaded_p95_mv"


def months_since_first(dates):
    d = pd.to_datetime(pd.Series(dates).reset_index(drop=True))
    return ((d - d.min()).dt.total_seconds() / MONTH_S).values


def _groups(labels):
    _, inv = np.unique(np.asarray(labels), return_inverse=True)
    return [np.where(inv == k)[0] for k in range(inv.max() + 1)]


def _fit(fn):
    """Run fn(); returns (value, nonconverged_flag); exceptions propagate."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        v = fn()
    return v, any(issubclass(x.category, ConvergenceWarning) for x in w)


def second_stage_slope(months, adj):
    return float(HuberRegressor().fit(np.asarray(months).reshape(-1, 1), np.asarray(adj)).coef_[0])


def first_stage_adjust(T, I, y, eps=1.35):
    """Huber first stage; returns (unrounded adjusted values, coefficients incl. I_ref)."""
    X = np.column_stack([T, I])
    h = HuberRegressor(epsilon=eps, max_iter=500).fit(X, y)
    iref = float(np.median(I))
    ref = h.predict([[SPREAD_T_REF, iref]])[0]
    return ref + (y - h.predict(X)), {"intercept": float(h.intercept_), "bT": float(h.coef_[0]), "bI": float(h.coef_[1]), "I_ref": iref}


def _summarise(est, failed, nonconv, n_groups, n_boot, label):
    est = np.asarray(est)
    bad = (failed + nonconv) / max(n_boot, 1)
    out = {"method": label, "n_groups": int(n_groups), "n_draws": int(n_boot), "failed_draws": int(failed), "nonconverged_draws": int(nonconv),
           "inconclusive": bool(failed / max(n_boot, 1) > 0.01 or nonconv / max(n_boot, 1) > 0.01 or len(est) == 0)}
    if len(est):
        lo, hi = np.percentile(est, [2.5, 97.5])
        out.update({"ci95": [float(lo), float(hi)], "half_width": float((hi - lo) / 2)})
    return out


def primary_ci(months, adj, cluster_labels, n_boot=4000, seed=42, label="primary (day-clustered, conditional on the first stage)"):
    months, adj = np.asarray(months, float), np.asarray(adj, float)
    groups = _groups(cluster_labels)
    rng = np.random.default_rng(seed)
    est, failed, nonconv = [], 0, 0
    for _ in range(n_boot):
        idx = np.concatenate([groups[k] for k in rng.integers(0, len(groups), len(groups))])
        try:
            v, nc = _fit(lambda: second_stage_slope(months[idx], adj[idx]))
            est.append(v)
            nonconv += int(nc)
        except Exception:
            failed += 1
    return _summarise(est, failed, nonconv, len(groups), n_boot, label)


def two_stage_ci(months, T, I, y, cluster_labels, n_boot=4000, seed=42, label="S1 (day-clustered, two-stage)"):
    months, T, I, y = (np.asarray(a, float) for a in (months, T, I, y))
    groups = _groups(cluster_labels)
    rng = np.random.default_rng(seed)
    est, failed, nonconv = [], 0, 0
    for _ in range(n_boot):
        idx = np.concatenate([groups[k] for k in rng.integers(0, len(groups), len(groups))])
        try:
            def one():
                adj, _ = first_stage_adjust(T[idx], I[idx], y[idx])
                return second_stage_slope(months[idx], adj)
            v, nc = _fit(one)
            est.append(v)
            nonconv += int(nc)
        except Exception:
            failed += 1
    return _summarise(est, failed, nonconv, len(groups), n_boot, label)


def week_labels(dates):
    d = pd.to_datetime(pd.Series(dates).reset_index(drop=True))
    return ((d - d.min()).dt.days // 7).values


def day_labels(dates):
    return pd.to_datetime(pd.Series(dates).reset_index(drop=True)).dt.date.astype(str).values


def bundle(kept, stored_adj, n_boot=4000, seed=42):
    """kept: DataFrame of the canonical-clean kept rows with date, T, I, y columns (in the same order as stored_adj).
    Returns the primary interval, S1, S2 (week blocks, conditional) and S2-S1 (week blocks, two-stage), plus the point slope and the 'materially wider' verdicts."""
    m = months_since_first(kept["date"])
    days, weeks = day_labels(kept["date"]), week_labels(kept["date"])
    out = {"point_slope_mv_per_month": second_stage_slope(m, stored_adj), "n": int(len(kept)), "n_days": int(len(np.unique(days))), "seed": seed}
    out["primary"] = primary_ci(m, stored_adj, days, n_boot, seed)
    out["S1"] = two_stage_ci(m, kept[T_COL].values, kept[I_COL].values, kept[Y_COL].values, days, n_boot, seed)
    out["S2"] = primary_ci(m, stored_adj, weeks, n_boot, seed, "S2 (7-day blocks, conditional)")
    out["S2_S1"] = two_stage_ci(m, kept[T_COL].values, kept[I_COL].values, kept[Y_COL].values, weeks, n_boot, seed, "S2-S1 (7-day blocks, two-stage)")
    base = out["primary"].get("half_width")
    for k in ("S1", "S2", "S2_S1"):
        hw = out[k].get("half_width")
        out[k]["materially_wider_than_primary"] = bool(base and hw and hw / base > 1.2)
        out[k]["half_width_ratio_to_primary"] = float(hw / base) if base and hw else None
    return out
