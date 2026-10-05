#!/usr/bin/env python3
"""Day-clustered percentile bootstrap of a ratio of sums, from per-day sufficient statistics (M383, audit F22).

The former loop rebuilt a DataFrame per draw (pd.concat of the sampled days) and re-summed it. For an additive ratio  sum(num) / sum(den)  the
resample only needs the per-day totals: draw the same day indices, add the per-day sums, divide. The estimator, the resampling unit (calendar
day), the percentile CI, the seed and the draw count are unchanged; the per-draw rng.choice calls are kept (same stream as the former loop).
Only valid for additive ratios; medians, refits and event reconstruction need their own algorithms.
Day order = order of first appearance (DataFrame.date.unique()), exactly as the former dayboot()."""
import numpy as np


def ratio_boot_ci(df, num, den, scale=1.0, nb=4000, seed=42, day_col="date", q=(2.5, 97.5)):
    """Percentile CI [lo, hi] of scale * sum(df[num]) / sum(df[den]) under day-clustered resampling. num / den: column name or (name, name) sum."""
    days = df[day_col].unique()
    code = {d: i for i, d in enumerate(days)}
    di = df[day_col].map(code).to_numpy()
    nd = len(days)
    sn = np.bincount(di, weights=_col(df, num), minlength=nd)
    sd = np.bincount(di, weights=_col(df, den), minlength=nd)
    rng = np.random.default_rng(seed)
    pick = np.stack([rng.choice(nd, nd) for _ in range(nb)])
    out = scale * sn[pick].sum(axis=1) / sd[pick].sum(axis=1)
    return [float(np.percentile(out, q[0])), float(np.percentile(out, q[1]))]


def _col(df, c):
    if isinstance(c, (tuple, list)):
        return sum(df[x].to_numpy(dtype=float) for x in c)
    return df[c].to_numpy(dtype=float)
