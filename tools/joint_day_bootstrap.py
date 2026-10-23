#!/usr/bin/env python3
"""M491 (spec analyses/M491_spec.md Rev 2, audit Update 7 A08): joint calendar-day bootstrap for the difference of two ratio-of-sums statistics (Shoulder minus Warm energy intensity, kWh per 100 km) when the two cohorts share calendar dates.
The former interval resampled the days of each cohort INDEPENDENTLY, which drops the covariance created by dates on which both cohorts drove (shared weather, traffic and route mix). The joint design resamples the UNION of dates and
applies each drawn date to both cohorts (zero for a cohort with no drive that date). The stratified sensitivity resamples within date types (warm-only, shoulder-only, shared dates); with disjoint dates it reduces to the independent design.
Pure functions of the per-day sums and a generator: no I/O. `days_a` / `days_b` are DataFrames indexed by date with columns num (kWh) and den (km)."""
import numpy as np
import pandas as pd

DROP_CAP = 0.005          # spec A2: more than 0.5 % of the draws discarded in a band STOPS the milestone


def _align(days_a, days_b):
    u = days_a.index.union(days_b.index)
    a = days_a.reindex(u).fillna(0.0)
    b = days_b.reindex(u).fillna(0.0)
    shared = days_a.index.intersection(days_b.index)
    return u, a["num"].to_numpy(float), a["den"].to_numpy(float), b["num"].to_numpy(float), b["den"].to_numpy(float), shared


def joint_difference(days_a, days_b, rng, n_draws):
    """(diff draws b - a in kWh/100 km, ratio draws a, ratio draws b, n dropped, n union dates, n shared dates). A draw with a zero distance denominator in either cohort is discarded and counted."""
    u, na, ka, nb, kb, shared = _align(days_a, days_b)
    G = len(u)
    idx = rng.integers(0, G, size=(n_draws, G))
    sa, ska, sb, skb = na[idx].sum(1), ka[idx].sum(1), nb[idx].sum(1), kb[idx].sum(1)
    ok = (ska > 0) & (skb > 0)
    ra, rb = 100.0 * sa[ok] / ska[ok], 100.0 * sb[ok] / skb[ok]
    return rb - ra, ra, rb, int((~ok).sum()), int(G), int(len(shared))


def stratified_difference(days_a, days_b, rng, n_draws):
    """Sensitivity: strata = a-only dates, b-only dates, shared dates; each resampled with replacement within itself (draws per stratum = stratum size). Returns (diff draws, n dropped)."""
    u, na, ka, nb, kb, shared = _align(days_a, days_b)
    in_a, in_b = u.isin(days_a.index), u.isin(days_b.index)
    strata = [np.where(in_a & ~in_b)[0], np.where(~in_a & in_b)[0], np.where(in_a & in_b)[0]]
    sa = np.zeros(n_draws); ska = np.zeros(n_draws); sb = np.zeros(n_draws); skb = np.zeros(n_draws)
    for ix in strata:
        if len(ix) == 0:
            continue
        pick = ix[rng.integers(0, len(ix), size=(n_draws, len(ix)))]
        sa += na[pick].sum(1); ska += ka[pick].sum(1); sb += nb[pick].sum(1); skb += kb[pick].sum(1)
    ok = (ska > 0) & (skb > 0)
    return 100.0 * sb[ok] / skb[ok] - 100.0 * sa[ok] / ska[ok], int((~ok).sum())


def independent_difference(days_a, days_b, rng, n_draws):
    """The former design, for tests and the stored sensitivity: each cohort's days resampled on their own (B*2 draws of each, as in m297_comparison_cube.cohort_ratio)."""
    def one(d):
        n, k = d["num"].to_numpy(float), d["den"].to_numpy(float)
        idx = rng.integers(0, len(d), size=(n_draws, len(d)))
        return 100 * n[idx].sum(1) / k[idx].sum(1)
    ra = one(days_a)
    rb = one(days_b)
    return rb - ra


def interval(draws, q=(0.025, 0.975), dp=2):
    return [round(float(x), dp) for x in np.quantile(draws, q)]
