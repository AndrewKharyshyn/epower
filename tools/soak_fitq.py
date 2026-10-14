#!/usr/bin/env python3
"""M430 (spec analyses/M430_spec.md Rev 2, audit F05): held-out fit quality of the parked-soak time-constant fits (pack, coolant, oil). ONE implementation.

Model M = the existing single exponential through the origin (y_hat = Sen slope refit on the training days * gap) for y = ln(resid excess / init excess).
Held out by calendar day: k = 10 contiguous arrival-day blocks (whole days never split; each fold trains on all other blocks, so this is blocked k-fold CV, not forward-only).
References, scored under their own loss: B0 persistence (y_hat = 0); B1 one level (training MEDIAN for the MAE / MedAE family, training MEAN for the log-MSE family);
B2 the same statistic inside the gap bins (0-1, 1-3, 3-6, 6-12, 12-24, 24+ h; a bin with < 5 training pairs falls back to B1); B3 (diagnostic only) Theil-Sen with a free intercept.
PRIMARY metric: skill_MAE = 1 - MAE_M / MAE_B on the retained fraction exp(y). SECONDARY: log-scale MSE skill and log MedAE. Calendar day is the resampling cluster:
paired percentile bootstrap over held-out days (B = 4000, a fresh default_rng(42) per cell). Statements only for pooled, gap < 1 h, gap >= 1 h with >= 20 held-out pairs and >= 10 days.
`slope_fn` is injected (compute_summary_arrays._sen_slope). Pure functions; no I/O."""
import numpy as np

CAPTURE = None          # evidence hook (tools/m430_fitq.py): a list that fit_quality appends each fit's pre-filter pair table to; None in production
BLOCK_DAYS = 5          # post-hoc sensitivity: moving blocks of 5 consecutive held-out days
K_FOLDS = 10
B_DEFAULT = 4000
SEED = 42
BIN_EDGES = (0.0, 1.0, 3.0, 6.0, 12.0, 24.0, np.inf)
MIN_BIN = 5
MIN_TRAIN, MIN_DISTINCT = 8, 3
MIN_PAIRS, MIN_DAYS = 20, 10
SPLIT_H = 1.0


def _bin_index(x):
    return np.clip(np.searchsorted(np.asarray(BIN_EDGES[1:-1]), x, side="right"), 0, len(BIN_EDGES) - 2)


def fold_of_days(days, k=K_FOLDS):
    """Contiguous blocks of the sorted distinct days (k = None: leave-one-day-out)."""
    uniq = sorted(set(days))
    if k is None:
        return {d: i for i, d in enumerate(uniq)}
    edges = np.linspace(0, len(uniq), k + 1).astype(int)
    out = {}
    for f in range(k):
        for d in uniq[edges[f]:edges[f + 1]]:
            out[d] = f
    return out


def cv_predictions(x, y, days, slope_fn, fold_of_day):
    """Held-out predictions of M, B0, B1 (median / mean), B2 (median / mean), B3. NaN where the fold could not be scored (counted)."""
    x, y, days = np.asarray(x, float), np.asarray(y, float), np.asarray(days)
    n = len(x)
    names = ("M", "B0", "B1med", "B1mean", "B2med", "B2mean", "B3")
    P = {m: np.full(n, np.nan) for m in names}
    fold = np.array([fold_of_day[d] for d in days])
    skipped = 0
    for f in sorted(set(fold)):
        te, tr = fold == f, fold != f
        if tr.sum() < MIN_TRAIN or len(np.unique(x[tr])) < MIN_DISTINCT:
            skipped += 1
            continue
        xt, yt = x[tr], y[tr]
        s = slope_fn(xt, yt)
        P["M"][te] = s * x[te]
        P["B0"][te] = 0.0
        med, mean = float(np.median(yt)), float(np.mean(yt))
        P["B1med"][te], P["B1mean"][te] = med, mean
        bt, be = _bin_index(xt), _bin_index(x[te])
        b2med = np.full(len(BIN_EDGES) - 1, med)
        b2mean = np.full(len(BIN_EDGES) - 1, mean)
        for b in range(len(BIN_EDGES) - 1):
            m = bt == b
            if m.sum() >= MIN_BIN:
                b2med[b], b2mean[b] = float(np.median(yt[m])), float(np.mean(yt[m]))
        P["B2med"][te], P["B2mean"][te] = b2med[be], b2mean[be]
        P["B3"][te] = s * x[te] + float(np.median(yt - s * xt))
    return P, skipped


class Cell:
    """Per-day sufficient statistics and arrays of one cell (pooled or a stratum) on the held-out pairs."""

    def __init__(self, x, y, days, P, mask):
        ok = mask & np.isfinite(P["M"])
        self.n = int(ok.sum())
        self.y = y[ok]
        self.P = {m: v[ok] for m, v in P.items()}
        d = np.asarray(days)[ok]
        self.days = list(dict.fromkeys(d.tolist()))
        code = {u: i for i, u in enumerate(self.days)}
        self.di = np.array([code[u] for u in d]) if self.n else np.array([], int)
        self.idx = [np.where(self.di == i)[0] for i in range(len(self.days))]
        ry = np.exp(self.y)
        self.ae = {m: np.abs(ry - np.exp(self.P[m])) for m in ("M", "B0", "B1med", "B2med", "B3")}
        self.se = {m: (self.y - self.P[m]) ** 2 for m in ("M", "B0", "B1mean", "B2mean", "B3")}
        self.lae = {m: np.abs(self.y - self.P[m]) for m in ("M", "B0", "B1med", "B2med")}

    def eligible(self):
        return self.n >= MIN_PAIRS and len(self.days) >= MIN_DAYS

    def stats(self, ii):
        """All metrics on the pairs `ii` (index array into this cell). Returns dict with NaN for a zero denominator."""
        out = {}
        mae_m = self.ae["M"][ii].mean()
        for lab, ref in (("B0", "B0"), ("B1", "B1med"), ("B2", "B2med")):
            den = self.ae[ref][ii].mean()
            out["skillMAE_" + lab] = (1.0 - mae_m / den) if den > 0 else np.nan
        mse_m = self.se["M"][ii].mean()
        for lab, ref in (("B0", "B0"), ("B1", "B1mean"), ("B2", "B2mean")):
            den = self.se[ref][ii].mean()
            out["skillMSElog_" + lab] = (1.0 - mse_m / den) if den > 0 else np.nan
        med_m = float(np.median(self.lae["M"][ii]))
        for lab, ref in (("B0", "B0"), ("B1", "B1med"), ("B2", "B2med")):
            den = float(np.median(self.lae[ref][ii]))
            out["skillMedAElog_" + lab] = (1.0 - med_m / den) if den > 0 else np.nan
        out["MAE_M"], out["MAE_B0"] = mae_m, self.ae["B0"][ii].mean()
        out["MedAElog_M"], out["MedAElog_B0"] = float(np.median(self.lae["M"][ii])), float(np.median(self.lae["B0"][ii]))
        out["skillMAE_B3"] = (1.0 - mae_m / self.ae["B3"][ii].mean()) if self.ae["B3"][ii].mean() > 0 else np.nan
        return out


def _stmt(lo, hi, which):
    if which == "S1":
        return "improvement over persistence established" if lo > 0 else "improvement over persistence not established"
    if which == "S2":
        return "gain over a constant level established" if lo > 0 else "gain over a constant level not established"
    return "worse than the empirical gap bins" if hi < 0 else "not shown to be worse than the empirical gap bins"


def _block_bootstrap(cell, stm, b, seed):
    """Post-hoc sensitivity (M430 blind audit, Director ruling; not pre-registered): the primary-skill statements under a moving-block bootstrap of BLOCK_DAYS consecutive held-out days.
    skill_MAE_B = 1 - sum(AE_M) / sum(AE_B) (the pair count cancels), so per-day sums are enough."""
    order = sorted(range(len(cell.days)), key=lambda i: cell.days[i])
    nd = len(order)
    sm = np.array([cell.ae["M"][cell.idx[i]].sum() for i in order])
    sref = {w: np.array([cell.ae[r][cell.idx[i]].sum() for i in order]) for w, r in (("S1", "B0"), ("S2", "B1med"), ("S3", "B2med"))}
    L = min(BLOCK_DAYS, nd)
    nb = int(np.ceil(nd / L))
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, nd - L + 1, (b, nb))
    picks = (starts[:, :, None] + np.arange(L)[None, None, :]).reshape(b, -1)[:, :nd]
    out, differs = {}, []
    for w in ("S1", "S2", "S3"):
        den = sref[w][picks].sum(axis=1)
        ok = den > 0
        sk = 1.0 - sm[picks].sum(axis=1)[ok] / den[ok]
        lo, hi = np.percentile(sk, [2.5, 97.5])
        out[w] = _stmt(lo, hi, w)
        if (stm.get(w) or {}).get("statement") not in (None, out[w]):
            differs.append(w)
    return {"blockDays": L, "statements": out, "differsFromDayBootstrap": differs, "label": "post-hoc, not pre-registered (M430 blind audit): moving-block bootstrap of %d consecutive held-out days" % L}


def analyse_cell(cell, b=B_DEFAULT, seed=SEED):
    """Point values, paired bootstrap intervals, statements and the metric-disagreement flag of one cell."""
    allidx = np.arange(cell.n)
    pt = cell.stats(allidx)
    res = {"nPairs": cell.n, "nDays": len(cell.days), "eligibleForStatements": cell.eligible(),
           "point": {k: (None if not np.isfinite(v) else round(float(v), 4)) for k, v in pt.items()}}
    if cell.n == 0 or len(cell.days) < 2:
        return res
    rng = np.random.default_rng(seed)
    keys = list(pt.keys())
    draws = {k: [] for k in keys}
    zero = {k: 0 for k in keys}
    nd = len(cell.days)
    for _ in range(b):
        pick = rng.integers(0, nd, nd)
        ii = np.concatenate([cell.idx[p] for p in pick])
        st = cell.stats(ii)
        for k in keys:
            if np.isfinite(st[k]):
                draws[k].append(st[k])
            else:
                zero[k] += 1
    ci = {}
    for k in keys:
        v = np.array(draws[k])
        ci[k] = [round(float(np.percentile(v, 2.5)), 4), round(float(np.percentile(v, 97.5)), 4)] if len(v) else None
    res["ci95"] = ci
    res["nZeroDenominatorDraws"] = {k: int(v) for k, v in zero.items() if k.startswith("skill") and v > 0}
    stm = {}
    if cell.eligible():
        for which, kp, secs in (("S1", "skillMAE_B0", ("skillMSElog_B0", "skillMedAElog_B0")), ("S2", "skillMAE_B1", ("skillMSElog_B1", "skillMedAElog_B1")),
                                ("S3", "skillMAE_B2", ("skillMSElog_B2", "skillMedAElog_B2"))):
            if zero[kp] > 0 or ci[kp] is None or not np.isfinite(pt[kp]):
                stm[which] = {"statement": None, "reason": "zero denominator in the reference (point or %d bootstrap draws): no statement" % zero[kp]}
                continue
            s_primary = _stmt(ci[kp][0], ci[kp][1], which)
            entry = {"statement": s_primary}
            for ks in secs:
                if ci[ks] is not None and zero[ks] == 0 and np.isfinite(pt[ks]):
                    s_sec = _stmt(ci[ks][0], ci[ks][1], which)
                    if s_sec != s_primary:
                        entry.setdefault("metricDisagreement", []).append("%s gives: %s" % (ks, s_sec))
            stm[which] = entry
    res["statements"] = stm
    res["b2EqualsB0AllFolds"] = bool(np.all(cell.P["B2med"] == cell.P["B0"]))
    if cell.eligible():
        res["blockBootstrap"] = _block_bootstrap(cell, stm, b, seed + 7)
    return res


def fit_quality(x, y, arrival_day, slope_fn, r2_insample=None, n_removed=None, n_before_filter=None, b=B_DEFAULT, seed=SEED, prefilter=None):
    """The payload block for one fit. See the module docstring and the spec."""
    x, y, days = np.asarray(x, float), np.asarray(y, float), np.asarray([str(d) for d in arrival_day])
    if CAPTURE is not None and prefilter is not None:
        CAPTURE.append({k: (np.asarray(v).tolist() if k != "arrivalDay" else [str(d) for d in v]) for k, v in prefilter.items()})
    fm = fold_of_days(days.tolist(), K_FOLDS)
    P, skipped = cv_predictions(x, y, days, slope_fn, fm)
    cells = {"pooled": np.ones(len(x), bool), "gapLt1h": x < SPLIT_H, "gapGe1h": x >= SPLIT_H}
    out_cells = {name: analyse_cell(Cell(x, y, days, P, m), b, seed) for name, m in cells.items()}
    # descriptive bins on the same held-out predictions
    ok = np.isfinite(P["M"])
    bi = _bin_index(x)
    bins = []
    for bb in range(len(BIN_EDGES) - 1):
        m = ok & (bi == bb)
        lab = "%g-%s h" % (BIN_EDGES[bb], "inf" if np.isinf(BIN_EDGES[bb + 1]) else "%g" % BIN_EDGES[bb + 1])
        if m.sum() == 0:
            bins.append({"bin": lab, "nPairs": 0})
            continue
        bins.append({"bin": lab, "nPairs": int(m.sum()), "nDays": int(len(set(days[m]))), "medianObservedRetained": round(float(np.median(np.exp(y[m]))), 4),
                     "medianPredictedRetained": round(float(np.median(np.exp(P["M"][m]))), 4), "medianResidualLog": round(float(np.median(y[m] - P["M"][m])), 4)})
    # post-hoc descriptive additions (M430 blind audit, Director ruling; not pre-registered)
    se_all = (y[ok] - P["M"][ok]) ** 2
    ge12 = x[ok] >= 12.0
    post_hoc = {"label": "post-hoc, not pre-registered (M430 blind audit)",
                "logSqErrShareGapGe12h": (round(float(se_all[ge12].sum() / se_all.sum()), 4) if se_all.sum() > 0 else None),
                "shareOfScoredPairsGapGe12h": round(float(ge12.mean()), 4) if ok.any() else None,
                "reading": "share of the line's held-out log squared error that comes from pairs parked 12 h or longer; with the outcome-selection floor and shape misfit confounded there, the negative log-scale R2 and the log-MSE skill are driven by that tail"}
    # leave-one-day-out sensitivity: do the pooled / stratum statements change?
    flm = fold_of_days(days.tolist(), None)
    PL, skl = cv_predictions(x, y, days, slope_fn, flm)
    lodo = {}
    for name, m in cells.items():
        a = analyse_cell(Cell(x, y, days, PL, m), b, seed + 1)
        base = out_cells[name].get("statements", {})
        cur = a.get("statements", {})
        lodo[name] = {"nPairs": a["nPairs"], "statements": {k: (v.get("statement")) for k, v in cur.items()},
                      "differsFromK10": sorted(k for k in set(base) | set(cur) if (base.get(k) or {}).get("statement") != (cur.get(k) or {}).get("statement"))}
    return {
        "label": "held-out, blocked-day cross-validated (k = 10 arrival-day blocks); model-derived; conditional on the pairing, the fold assignment and the manual driving-time ambient field",
        "inSample": {"rSquared": r2_insample, "reading": "in-sample R2 of the through-origin Sen line against a free-level mean of y = ln(resid/init excess); negative means the line is worse than a constant mean on the log scale; the held-out errors say whether it still improves on no decay"},
        "selection": {"nBeforeResidualFilter": n_before_filter, "nRemovedByResidualFilter": n_removed, "note": "pairs with residual excess <= 0.5 C (and initial excess <= the minimum) are excluded: selection on the outcome; long-gap pairs are floored while the through-origin line keeps falling"},
        "cv": {"k": K_FOLDS, "nPairs": int(len(x)), "nScoredHeldOut": int(ok.sum()), "nSkippedFolds": int(skipped), "bootstrap": {"B": b, "seed": seed, "unit": "calendar day (arrival), paired over models"},
               "primaryMetric": "skill_MAE = 1 - MAE_M / MAE_B on the retained fraction exp(y); secondary: log-scale MSE skill, log MedAE",
               "references": "B0 persistence (y_hat = 0); B1 one level (median for MAE / MedAE, mean for log MSE); B2 gap-bin statistic with the pack gapBins edges 0-1-3-6-12-24 h (coolant and oil use the same edges)",
               "multiplicity": "intervals are per comparison and are not adjusted (27 per metric)", "eligibility": "statements need >= %d held-out pairs and >= %d held-out days" % (MIN_PAIRS, MIN_DAYS)},
        "cells": out_cells, "bins": bins, "leaveOneDayOut": {"nSkippedFolds": int(skl), "cells": lodo}, "postHoc": post_hoc,
    }
