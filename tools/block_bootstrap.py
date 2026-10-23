#!/usr/bin/env python3
"""M494 (spec analyses/M494_spec.md Rev 2): block bootstraps of the DIFFERENCE of two ratio-of-sums statistics (Shoulder minus Warm energy intensity, kWh per 100 km) with both cohorts resampled together.
Inputs are per-date sums: `days_a` / `days_b` = DataFrames indexed by ISO date string with columns num (kWh) and den (km). A date without a drive of a cohort is zero for that cohort.
  * week_difference        ISO-calendar-week blocks, multinomial weights (the construction of dependence_sensitivity.boot_weights: rng.multinomial(nb, 1/nb, B)), all weeks of the union of dates;
  * stratified_weeks       the same within strata of weeks: a-only, b-only, mixed (both cohorts present), draws per stratum = stratum size (the M491 stratified analogue);
  * circular_moving_block  overlapping moving blocks of L consecutive calendar days on the axis from the first to the last date, CIRCULAR (starts uniform over all D positions, blocks wrap), ceil(D / L) blocks per draw,
                           per-day weights = block coverage. The released serial_dependence.moving_block draws starts in [0, D - L], which under-weights the first and last L - 1 days; for two season-defined cohorts that sit at
                           the two ends of the axis the bootstrap distribution would be off-centre, so this construction is circular (stated in the spec; the released one is unchanged).
A draw with a zero distance denominator in either cohort is discarded and counted. Pure functions of the data and a seed: no I/O."""
import numpy as np
import pandas as pd

DROP_CAP = 0.005


def iso_week(dates):
    iso = pd.to_datetime(pd.Series(list(dates))).dt.isocalendar()
    return (iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)).to_numpy()


def _per_unit(days_a, days_b, unit_of):
    """Aligned per-unit sums for the union of dates: (units, na, ka, nb, kb)."""
    u = days_a.index.union(days_b.index)
    a, b = days_a.reindex(u).fillna(0.0), days_b.reindex(u).fillna(0.0)
    lab = unit_of(list(u))
    codes, inv = np.unique(lab, return_inverse=True)
    f = lambda col, df: np.bincount(inv, weights=df[col].to_numpy(float), minlength=len(codes))
    return codes, f("num", a), f("den", a), f("num", b), f("den", b), inv, u


def _finish(sa, ska, sb, skb):
    ok = (ska > 0) & (skb > 0)
    ra, rb = 100.0 * sa[ok] / ska[ok], 100.0 * sb[ok] / skb[ok]
    return rb - ra, ra, rb, int((~ok).sum())


def week_difference(days_a, days_b, rng, n_draws):
    """(diff draws, ratio draws a, ratio draws b, n dropped, n weeks, n weeks with a, n weeks with b, n mixed weeks)."""
    codes, na, ka, nb, kb, inv, u = _per_unit(days_a, days_b, iso_week)
    nbk = len(codes)
    W = rng.multinomial(nbk, np.ones(nbk) / nbk, size=n_draws).astype(float)
    d, ra, rb, drop = _finish(W @ na, W @ ka, W @ nb, W @ kb)
    has_a, has_b = ka > 0, kb > 0
    return d, ra, rb, drop, nbk, int(has_a.sum()), int(has_b.sum()), int((has_a & has_b).sum())


def stratified_weeks(days_a, days_b, rng, n_draws):
    """Stratified sensitivity WS. Returns (diff draws, n dropped, stratum sizes {a_only, b_only, mixed})."""
    codes, na, ka, nb, kb, inv, u = _per_unit(days_a, days_b, iso_week)
    has_a, has_b = ka > 0, kb > 0
    strata = {"a_only": np.where(has_a & ~has_b)[0], "b_only": np.where(~has_a & has_b)[0], "mixed": np.where(has_a & has_b)[0]}
    sa = np.zeros(n_draws); ska = np.zeros(n_draws); sb = np.zeros(n_draws); skb = np.zeros(n_draws)
    for ix in strata.values():
        if len(ix) == 0:
            continue
        w = rng.multinomial(len(ix), np.ones(len(ix)) / len(ix), size=n_draws).astype(float)
        sa += w @ na[ix]; ska += w @ ka[ix]; sb += w @ nb[ix]; skb += w @ kb[ix]
    d, ra, rb, drop = _finish(sa, ska, sb, skb)
    return d, drop, {k: int(len(v)) for k, v in strata.items()}


def _calendar_axis(days_a, days_b):
    u = days_a.index.union(days_b.index)
    t0, t1 = pd.to_datetime(u.min()), pd.to_datetime(u.max())
    axis = pd.date_range(t0, t1, freq="D").strftime("%Y-%m-%d")
    a, b = days_a.reindex(axis).fillna(0.0), days_b.reindex(axis).fillna(0.0)
    return axis, a["num"].to_numpy(float), a["den"].to_numpy(float), b["num"].to_numpy(float), b["den"].to_numpy(float)


def circular_moving_block(days_a, days_b, L, rng, n_draws, circular=True):
    """(diff draws, ratio draws a, ratio draws b, n dropped, D, blocks per draw). circular=False reproduces the released start rule (starts in [0, D - L]) for the negative control only."""
    axis, na, ka, nb, kb = _calendar_axis(days_a, days_b)
    D = len(axis)
    nbk = int(np.ceil(D / L))
    starts = rng.integers(0, D if circular else D - L + 1, size=(n_draws, nbk))
    cov = np.zeros((n_draws, D))
    rows = np.repeat(np.arange(n_draws), nbk)
    for j in range(L):
        idx = (starts + j) % D if circular else np.minimum(starts + j, D - 1)
        np.add.at(cov, (rows, idx.ravel()), 1.0)
    d, ra, rb, drop = _finish(cov @ na, cov @ ka, cov @ nb, cov @ kb)
    return d, ra, rb, drop, D, nbk


def interval(draws, dp=2):
    return [round(float(x), dp) for x in np.percentile(draws, [2.5, 97.5])]
