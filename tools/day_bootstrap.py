#!/usr/bin/env python3
"""Day-clustered percentile bootstrap of a ratio of sums, from per-day sufficient statistics (M383, audit F22).

The former loop rebuilt a DataFrame per draw (pd.concat of the sampled days) and re-summed it. For an additive ratio  sum(num) / sum(den)  the
resample only needs the per-day totals: draw the same day indices, add the per-day sums, divide. The estimator, the resampling unit (calendar
day), the percentile CI, the seed and the draw count are unchanged; the per-draw rng.choice calls are kept (same stream as the former loop).
Only valid for additive ratios; medians, refits and event reconstruction need their own algorithms.
Day order = order of first appearance (DataFrame.date.unique()), exactly as the former dayboot()."""
import numpy as np


def ratio_boot_ci_detail(df, num, den, scale=1.0, nb=4000, seed=42, day_col="date", q=(2.5, 97.5), nan="raise"):
    """(CI, n_draws_used). Input semantics (M401, audit N04): an empty frame, a non-finite value (NaN with nan="raise", inf always) raises ValueError naming the column; nan="skipna" reproduces
    the former per-column pandas sum (a NaN contributes 0 to its own column). A draw whose resampled denominator total is 0 or non-finite is EXCLUDED and counted (n_draws_used < nb);
    if every draw is invalid the CI is [nan, nan]. The rng stream, estimator, seed and draw count are unchanged: finite data give the same CI as before."""
    if nan not in ("raise", "skipna"):
        raise ValueError("nan must be 'raise' or 'skipna'")
    if len(df) == 0:
        raise ValueError("ratio_boot_ci: empty frame (no days to resample)")
    nu, de = _col(df, num, nan == "skipna"), _col(df, den, nan == "skipna")
    for name, v in ((num, nu), (den, de)):
        if np.isinf(v).any():
            raise ValueError("ratio_boot_ci: infinite value in column %r" % (name,))
        if np.isnan(v).any():
            raise ValueError("ratio_boot_ci: non-finite (NaN) value in column %r (%d rows); pass nan='skipna' to reproduce the former pandas skip-NaN sum" % (name, int(np.isnan(v).sum())))
    days = df[day_col].unique()
    code = {d: i for i, d in enumerate(days)}
    di = df[day_col].map(code).to_numpy()
    nd = len(days)
    sn = np.bincount(di, weights=nu, minlength=nd)
    sd = np.bincount(di, weights=de, minlength=nd)
    rng = np.random.default_rng(seed)
    pick = np.stack([rng.choice(nd, nd) for _ in range(nb)])
    dtot = sd[pick].sum(axis=1)
    ok = (dtot != 0) & np.isfinite(dtot)
    if not ok.any():
        return [float("nan"), float("nan")], 0
    out = scale * sn[pick].sum(axis=1)[ok] / dtot[ok]
    return [float(np.percentile(out, q[0])), float(np.percentile(out, q[1]))], int(ok.sum())


def ratio_boot_ci(df, num, den, scale=1.0, nb=4000, seed=42, day_col="date", q=(2.5, 97.5), nan="raise"):
    """Percentile CI [lo, hi] of scale * sum(df[num]) / sum(df[den]) under day-clustered resampling. num / den: column name or (name, name) sum. See ratio_boot_ci_detail for the input semantics."""
    return ratio_boot_ci_detail(df, num, den, scale, nb, seed, day_col, q, nan)[0]


def _col(df, c, skipna=False):
    parts = [df[x].to_numpy(dtype=float) for x in (c if isinstance(c, (tuple, list)) else (c,))]
    if skipna:
        parts = [np.where(np.isnan(p), 0.0, p) for p in parts]
    return sum(parts[1:], parts[0].copy())
