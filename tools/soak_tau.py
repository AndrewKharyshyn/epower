#!/usr/bin/env python3
"""M429 (spec analyses/M429_spec.md Rev 2, audit F06): the interval rule for the parked-soak Newtonian-cooling time constants (pack, coolant, oil), ONE implementation.

The point estimate is unchanged (Sen's slope of ln(resid excess / init excess) on the parking gap, tau = -1/slope for slope < 0). Only the interval changes:
  * draws are whole clusters (calendar days) with replacement, all fitted pairs of a drawn cluster taken with multiplicity, B = 4000, a FRESH default_rng(42) per method;
  * the interval is the percentile of the draw slopes (np.percentile, method "linear") and is mapped to k = -slope (1/h) and to tau = -1/slope;
  * a draw with slope >= 0 is NOT dropped: its tau is +infinity; the upper tau bound is "unbounded" (None) iff the 97.5th slope percentile is >= 0; the share of such draws is reported
    separately; if the POINT slope is >= 0 tau is None and k with its interval is still reported.
`slope_fn` is injected (compute_summary_arrays._sen_slope) so the estimator stays single-sourced. Pure functions; no I/O."""
import math
import numpy as np

B_DEFAULT = 4000
CAPTURE = None          # evidence hook (tools/m429_soak.py): a list that soak_block appends each fit's pair table to; None in production
SEED = 42
LN2 = math.log(2.0)


def _tau(s):
    return (-1.0 / s) if (s is not None and np.isfinite(s) and s < 0) else None        # None = unbounded / undefined


def kish_clusters(cluster):
    """Kish effective number of clusters from the number of pairs per cluster (cluster = None: pairs are the units)."""
    if cluster is None:
        return None
    _, c = np.unique(cluster, return_counts=True)
    return float(c.sum() ** 2 / (c ** 2).sum())


def boot_slopes(x, y, cluster, slope_fn, b=B_DEFAULT, seed=SEED):
    """Bootstrap Sen slopes. cluster None -> resample pairs i.i.d. (reference only); else whole clusters."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    rng = np.random.default_rng(seed)
    out = np.empty(b)
    if cluster is None:
        n = len(x)
        for i in range(b):
            ii = rng.integers(0, n, n)
            out[i] = slope_fn(x[ii], y[ii])
        return out
    cl = np.asarray(cluster)
    uniq = np.unique(cl)
    by = {u: np.where(cl == u)[0] for u in uniq}
    for i in range(b):
        picks = rng.choice(uniq, size=len(uniq), replace=True)
        ii = np.concatenate([by[u] for u in picks])
        out[i] = slope_fn(x[ii], y[ii])
    return out


def interval_from_slopes(slopes):
    s = np.asarray(slopes, float)
    und = int((~np.isfinite(s)).sum())
    s = s[np.isfinite(s)]
    lo, hi = np.percentile(s, [2.5, 97.5], method="linear")
    t_lo, t_hi = _tau(lo), _tau(hi)
    r2 = lambda v: None if v is None else round(float(v), 2)
    return {"slopeCI": [float(lo), float(hi)], "decayRateKCI": [round(float(-hi), 5) + 0.0, round(float(-lo), 5) + 0.0],
            "tauCI": [r2(t_lo), r2(t_hi)], "halfLifeCI": [r2(None if t_lo is None else t_lo * LN2), r2(None if t_hi is None else t_hi * LN2)],
            "upperUnbounded": bool(hi >= 0), "lowerUnbounded": bool(lo >= 0),
            "nonDecayingDrawShare": round(float((s >= 0).mean()), 4), "nUndefinedDraws": und, "nDraws": int(len(s) + und)}


def old_rule_interval(x, y, slope_fn, cluster=None, b=1000, seed=SEED):
    """The PUBLISHED rule, reproduced for the method table: B = 1000, draws with slope >= 0 dropped, percentiles of tau over the retained draws."""
    s = boot_slopes(x, y, cluster, slope_fn, b, seed)
    taus = [-1.0 / v for v in s if v < 0]
    return ([round(float(np.percentile(taus, 2.5)), 2), round(float(np.percentile(taus, 97.5)), 2)] if taus else None), int((s >= 0).sum())


def leave_one_cluster_out(x, y, cluster, slope_fn):
    """Leave-one-cluster-out decay rates k = -slope (finite); a leave-out slope >= 0 (k <= 0) is an unbounded tau and is counted."""
    x, y, cl = np.asarray(x, float), np.asarray(y, float), np.asarray(cluster)
    ks = np.array([-slope_fn(x[cl != u], y[cl != u]) for u in np.unique(cl)])
    pos = ks[ks > 0]
    return {"decayRateKRange": [round(float(np.nanmin(ks)), 5), round(float(np.nanmax(ks)), 5)],
            "tauRange": [round(float(1.0 / np.nanmax(pos)), 2) if len(pos) else None, round(float(1.0 / np.nanmin(pos)), 2) if len(pos) and not (ks <= 0).any() else None],
            "nLeaveOutNonDecaying": int((ks <= 0).sum()), "nClusters": int(len(ks))}


GAP_SPLIT_H = 1.0     # an existing gapBins edge of the pack block


def gap_split(x, y, arrival_day, slope_fn, threshold=GAP_SPLIT_H, b=B_DEFAULT, seed=SEED):
    """Post-hoc descriptive disclosure (M429 blind audit, Director ruling 2026-10-14; NOT pre-registered): the same Sen fit and arrival-day interval inside the pairs parked
    for less than `threshold` hours and for at least that long. A single exponential does not have to fit all gaps; the pooled tau is a gap-mix-dependent summary."""
    x, y, cl = np.asarray(x, float), np.asarray(y, float), np.asarray(arrival_day)
    strata = []
    for lab, m in (("gap < %g h" % threshold, x < threshold), ("gap >= %g h" % threshold, x >= threshold)):
        n = int(m.sum())
        row = {"label": lab, "nPairs": n, "nDays": int(len(np.unique(cl[m]))) if n else 0}
        if n >= 8 and len(np.unique(cl[m])) >= 3 and len(np.unique(x[m])) >= 3:
            s = slope_fn(x[m], y[m])
            iv = interval_from_slopes(boot_slopes(x[m], y[m], cl[m], slope_fn, b, seed))
            row.update({"decayRateK": round(float(-s), 5) + 0.0, "decayRateKCI": iv["decayRateKCI"], "tau": (None if _tau(s) is None else round(float(_tau(s)), 2)), "tauCI": iv["tauCI"],
                        "nonDecayingDrawShare": iv["nonDecayingDrawShare"]})
        else:
            row.update({"decayRateK": None, "decayRateKCI": None, "tau": None, "tauCI": None, "note": "too few pairs, days or distinct gaps for a fit"})
        strata.append(row)
    return {"thresholdH": threshold, "strata": strata, "label": "post-hoc descriptive (M429 audit), not pre-registered",
            "reading": "decay rate k = -slope (1/h) per stratum with the arrival-day interval; tau = null when the stratum slope is not negative. The pooled tau is a gap-mix-dependent summary of a single-exponential fit."}


def soak_block(x, y, arrival_day, departure_day, iso_week, slope_fn, point_slope, published_row=None, b=B_DEFAULT, seed=SEED):
    """All M429 leaves for one fit. Returns dict(tauCI, tauCiMethod, decayRateK, decayRateKCI, halfLifeCI, methodTable, leaveOneDay)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if CAPTURE is not None:
        CAPTURE.append({"gapH": x.tolist(), "y": y.tolist(), "arrivalDay": [str(v) for v in arrival_day], "departureDay": [str(v) for v in departure_day], "pointSlope": float(point_slope)})
    methods = [("iidPairsB4000", "pairs resampled i.i.d. (reference; ignores same-day dependence)", None),
               ("arrivalDay", "calendar day of the following drive (PRIMARY)", arrival_day),
               ("departureDay", "calendar day of the previous drive's end", departure_day),
               ("isoWeek", "non-overlapping ISO-week blocks", iso_week)]
    rows, prim = [], None
    for mid, label, cl in methods:
        sl = boot_slopes(x, y, cl, slope_fn, b, seed)
        iv = interval_from_slopes(sl)
        nc = None if cl is None else int(len(np.unique(cl)))
        row = {"id": mid, "label": label, "nClusters": nc, "essClusters": (None if cl is None else round(kish_clusters(cl), 1)), **{k: iv[k] for k in ("tauCI", "decayRateKCI", "halfLifeCI", "nonDecayingDrawShare", "upperUnbounded", "lowerUnbounded", "nUndefinedDraws")}}
        if mid == "isoWeek" and nc is not None and nc < 25:
            row["note"] = "fewer than about 25 blocks: coarse sensitivity"
        rows.append(row)
        if mid == "arrivalDay":
            prim = iv
    if published_row:                  # historical row, frozen at M429 (analyses/M429_published_rule.json); never recomputed at ingestion
        rows.insert(0, dict(published_row))
    k_point = round(float(-point_slope), 5) + 0.0
    tau_pt = _tau(point_slope)
    loo = leave_one_cluster_out(x, y, arrival_day, slope_fn)
    return {
        "tauCI": prim["tauCI"],
        "tauCiMethod": {"cluster": "calendar day of the following drive's start", "B": b, "seed": seed, "percentile": "np.percentile linear on the slope scale, mapped by tau = -1/slope",
                        "nonDecayingDraws": "slope >= 0 counted, tau = +infinity; upper bound unbounded (null) iff the 97.5th slope percentile >= 0",
                        "nClusters": int(len(np.unique(arrival_day))), "essClusters": round(kish_clusters(arrival_day), 1), "nPairs": int(len(x)),
                        "nonDecayingDrawShare": prim["nonDecayingDrawShare"], "upperUnbounded": prim["upperUnbounded"], "nUndefinedDraws": prim["nUndefinedDraws"],
                        "pointTauDefined": tau_pt is not None, "label": "model-derived; conditional on the pairing and the manual driving-time ambient field"},
        "decayRateK": k_point, "decayRateKCI": prim["decayRateKCI"], "halfLifeCI": prim["halfLifeCI"],
        "methodTable": rows, "leaveOneDay": loo, "gapSplit": gap_split(x, y, arrival_day, slope_fn, b=b, seed=seed),
    }
