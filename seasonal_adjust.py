"""
seasonal_adjust.py  (v2, M284)  --  composition-adjusted seasonal contrast
==========================================================================
Purpose
-------
Season-associated metrics show raw warm/shoulder/cold differences that are largely
mediated by duty/route composition.  This module estimates the B-minus-A difference
of a per-drive outcome AFTER standardising to a common covariate population, so a raw
overlay is not mistaken for a thermal effect -- and it REFUSES to present a contrast
when the two cohorts do not share enough covariate support to justify one.

Why v2 (audit #7, "seasonal_adjust.py rewrite")
-----------------------------------------------
v1 defects, each closed here:
  * mutated the caller's drive dicts (wrote "_y")                  -> inputs are never written
  * NaN / inf slipped through the `is None` checks                 -> finite-value validation, counted
  * "common support" = per-covariate [min,max] range of ONE cohort -> categorical-stratum support +
    (marginal boxes cannot see joint / categorical non-overlap;       propensity overlap (min-max rule),
     e.g. an all-urban cohort vs a mixed cohort passed at 0.98)       overlap-weight effective sample size,
                                                                      standardised-mean-difference balance
  * "standardised" additive OLS returned the cohort coefficient,   -> per-cohort outcome models
    i.e. the standardisation step was vacuous and the estimate        (g-computation) predicted on the
    extrapolated the linear fit to covariate regions one cohort       trimmed common-support population;
    never visits                                                      overlap-weighted estimator reported
                                                                      alongside as a model-free sensitivity
  * day bootstrap resampled days uniformly, so replicates could    -> day-cluster bootstrap STRATIFIED by
    contain a single cohort (arbitrary min-norm lstsq output) and     day composition (A-only / B-only / both)
    failed replicates were dropped silently                           with a FULL refit (overlap uncertainty
                                                                      propagates) and validity accounting;
                                                                      unstable bootstrap => unavailable
  * no multiplicity control, no practical-equivalence decision     -> BH-FDR family wrapper, optional SESOI
                                                                      equivalence decision (90% CI in +/-margin)

Estimand
--------
Average B-minus-A difference in the outcome over the COMMON-SUPPORT population (drives in
covariate strata and propensity range occupied by both cohorts).  It is NOT the pooled-corpus
ATE: the pooled corpus contains regions one cohort never visits, where any estimate is
extrapolation.  Without HVAC telemetry the contrast is a "seasonal operating difference that may
include unmeasured cabin-heating/defrost demand", not a chemistry effect.

Deterministic (fixed seed; no global RNG state).  Dependencies: numpy, scikit-learn (both pinned in
requirements.txt).  Returns {status: available|unavailable, reasonCode, reason} -- never a silent zero.
"""
from __future__ import annotations

import hashlib
import math

import numpy as np
from sklearn.linear_model import LogisticRegression

SEASONAL_ADJUST_VERSION = "seasonal_adjust_v2.0.0"
BOOT_SEED = 42
DEFAULT_COVARIATES = ["speed_mean_moving", "stationary_pct", "pct_highway", "distance_km"]
PS_CLIP = 1e-3
SMD_TOL = 0.10          # |standardised mean difference| after overlap weighting
MIN_CAT_ROWS = 2        # rows per cohort required for a categorical stratum to count as shared


# --------------------------------------------------------------------------- #
# input handling
# --------------------------------------------------------------------------- #
def _finite(x):
    """float(x) if it is a finite real number, else None (None / '' / NaN / +-inf -> None)."""
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _prepare(drives, outcome_key, cohort_key, cohort_a, cohort_b, covariates,
             cluster_key, categorical_key):
    """Read-only extraction of the analysis arrays.  Never writes to `drives`.

    Rows are dropped (and COUNTED) when the outcome or any covariate is not a finite number.
    A missing cluster id is not silently pooled: each such row becomes its own singleton cluster and
    is counted in `nSingletonClusters`."""
    y, Z, g, cl, cat = [], [], [], [], []
    n_in_cohorts = n_nonfinite = n_singleton = 0
    for i, d in enumerate(drives):
        c = d.get(cohort_key)
        if c != cohort_a and c != cohort_b:
            continue
        n_in_cohorts += 1
        yv = _finite(d.get(outcome_key))
        zs = [_finite(d.get(cv)) for cv in covariates]
        if yv is None or any(z is None for z in zs):
            n_nonfinite += 1
            continue
        cid = d.get(cluster_key)
        if cid is None or (isinstance(cid, float) and math.isnan(cid)) or cid == "":
            cid = f"__row{i}"
            n_singleton += 1
        y.append(yv); Z.append(zs); g.append(1 if c == cohort_b else 0)
        cl.append(str(cid))
        ct = d.get(categorical_key) if categorical_key else None
        cat.append("NA" if ct is None or ct == "" else str(ct))
    return {
        "y": np.asarray(y, float), "Z": np.asarray(Z, float).reshape(len(y), len(covariates)),
        "g": np.asarray(g, int), "cl": np.asarray(cl, object), "cat": np.asarray(cat, object),
        "counts": {"nInCohorts": n_in_cohorts, "nDroppedNonFinite": n_nonfinite,
                   "nSingletonClusters": n_singleton},
    }


# --------------------------------------------------------------------------- #
# overlap assessment + estimation on ONE dataset (also called per bootstrap replicate)
# --------------------------------------------------------------------------- #
class _Fail(Exception):
    def __init__(self, code, msg, extra=None):
        super().__init__(msg); self.code = code; self.msg = msg; self.extra = extra or {}


def _kish_ess(w):
    s = float(np.sum(w)); s2 = float(np.sum(w * w))
    return (s * s / s2) if s2 > 0 else 0.0


def _estimate(y, Z, g, cat, cfg, want_diagnostics=False):
    """Full pipeline on one (re)sample: categorical support -> propensity overlap -> estimators.
    Raises _Fail with a reason code when the sample cannot support a contrast."""
    n_a_tot = int((g == 0).sum()); n_b_tot = int((g == 1).sum())
    if n_a_tot < cfg["min_rows"] or n_b_tot < cfg["min_rows"]:
        raise _Fail("thin_cohort", f"too few rows (A={n_a_tot}, B={n_b_tot}; need {cfg['min_rows']})")

    # 1. categorical stratum support: strata with >= MIN_CAT_ROWS rows in BOTH cohorts
    cats = sorted(set(cat.tolist()))
    shared = [c for c in cats if int(((cat == c) & (g == 0)).sum()) >= MIN_CAT_ROWS
              and int(((cat == c) & (g == 1)).sum()) >= MIN_CAT_ROWS]
    if not shared:
        raise _Fail("no_shared_stratum", "no categorical stratum is occupied by both cohorts")
    keep = np.isin(cat, shared)
    y1, Z1, g1, cat1 = y[keep], Z[keep], g[keep], cat[keep]
    if int((g1 == 0).sum()) < cfg["min_rows"] or int((g1 == 1).sum()) < cfg["min_rows"]:
        raise _Fail("thin_after_stratum", "too few rows inside shared strata")

    # 2. standardise covariates on the retained rows; drop constant columns
    mu = Z1.mean(axis=0); sd = Z1.std(axis=0, ddof=0)
    live = sd > 1e-12
    if not live.any():
        raise _Fail("no_covariate_variation", "all covariates constant inside shared strata")
    X1 = (Z1[:, live] - mu[live]) / sd[live]

    # 3. propensity model P(B | x, stratum): mildly ridge-regularised logistic regression
    dm = [np.asarray([1.0 if c == s else 0.0 for c in cat1]) for s in shared[1:]]
    P = np.column_stack([X1] + dm) if dm else X1
    try:
        lr = LogisticRegression(C=1.0, max_iter=2000, solver="lbfgs")
        lr.fit(P, g1)
        e = np.clip(lr.predict_proba(P)[:, 1], PS_CLIP, 1 - PS_CLIP)
    except Exception as ex:  # noqa: BLE001 - surfaced, not swallowed
        raise _Fail("propensity_fit_failed", f"propensity model failed ({type(ex).__name__})")

    # 4. common-support trimming (min-max rule on the propensity, symmetric in A and B)
    eA, eB = e[g1 == 0], e[g1 == 1]
    lo = max(float(eA.min()), float(eB.min())); hi = min(float(eA.max()), float(eB.max()))
    if not lo < hi:
        raise _Fail("disjoint_propensity", "propensity ranges of the two cohorts do not overlap")
    on = (e >= lo) & (e <= hi)
    yS, XS, gS, eS, catS = y1[on], X1[on], g1[on], e[on], cat1[on]
    nA, nB = int((gS == 0).sum()), int((gS == 1).sum())
    frac_a, frac_b = nA / n_a_tot, nB / n_b_tot
    if nA < cfg["min_rows"] or nB < cfg["min_rows"]:
        raise _Fail("thin_on_support", f"too few rows on common support (A={nA}, B={nB})",
                    {"retainedFraction": {"A": round(frac_a, 3), "B": round(frac_b, 3)}})
    if min(frac_a, frac_b) < cfg["min_support"]:
        raise _Fail("insufficient_support",
                    f"common support retains A={frac_a:.2f}, B={frac_b:.2f} of rows "
                    f"(< {cfg['min_support']})",
                    {"retainedFraction": {"A": round(frac_a, 3), "B": round(frac_b, 3)}})

    # 5. overlap weights (ATO): B rows weight (1-e), A rows weight e  ->  ESS + weighted contrast
    wS = np.where(gS == 1, 1.0 - eS, eS)
    essA, essB = _kish_ess(wS[gS == 0]), _kish_ess(wS[gS == 1])
    if min(essA, essB) < cfg["min_ess"]:
        raise _Fail("low_ess", f"overlap-weight effective sample size too small (A={essA:.1f}, B={essB:.1f})")
    ow = (np.sum(wS[gS == 1] * yS[gS == 1]) / np.sum(wS[gS == 1])
          - np.sum(wS[gS == 0] * yS[gS == 0]) / np.sum(wS[gS == 0]))

    # 6. g-computation on the trimmed population: per-cohort OLS (== full cohort interactions)
    #    when each cohort can afford the parameters, additive OLS otherwise.
    dS = [np.asarray([1.0 if c == s else 0.0 for c in catS]) for s in shared[1:]
          if 0 < np.mean(catS == s) < 1]
    D = np.column_stack([XS] + dS) if dS else XS
    p = D.shape[1] + 1
    per_cohort_ok = min(nA, nB) >= 3 * p
    if per_cohort_ok:
        mus = []
        for grp in (0, 1):
            m = gS == grp
            Xg = np.column_stack([np.ones(int(m.sum())), D[m]])
            if np.linalg.matrix_rank(Xg) < Xg.shape[1]:
                per_cohort_ok = False; break
            b, *_ = np.linalg.lstsq(Xg, yS[m], rcond=None)
            mus.append(np.column_stack([np.ones(len(D)), D]) @ b)
        if per_cohort_ok:
            gcomp = float(np.mean(mus[1] - mus[0])); model = "per_cohort_ols"
    if not per_cohort_ok:
        Xa = np.column_stack([np.ones(len(D)), gS.astype(float), D])
        if np.linalg.matrix_rank(Xa) < Xa.shape[1]:
            raise _Fail("rank_deficient", "outcome-model design is rank deficient")
        b, *_ = np.linalg.lstsq(Xa, yS, rcond=None)
        gcomp = float(b[1]); model = "additive_ols"

    out = {"gcomp": gcomp, "overlapWeighted": float(ow), "model": model,
           "nA": nA, "nB": nB}
    if want_diagnostics:
        raw_all = float(y[g == 1].mean() - y[g == 0].mean())
        raw_sup = float(yS[gS == 1].mean() - yS[gS == 0].mean())
        # balance (unweighted on retained-strata rows vs overlap-weighted on support)
        names_live = np.where(live)[0]
        pooled_sd = XS.std(axis=0, ddof=0); pooled_sd = np.where(pooled_sd > 1e-12, pooled_sd, 1.0)
        smd_u = np.abs(X1[g1 == 1].mean(axis=0) - X1[g1 == 0].mean(axis=0)) / X1.std(axis=0, ddof=0).clip(1e-12)
        smd_w = np.abs(np.average(XS[gS == 1], axis=0, weights=wS[gS == 1])
                       - np.average(XS[gS == 0], axis=0, weights=wS[gS == 0])) / pooled_sd
        out.update({
            "rawDiffAll": raw_all, "rawDiffOnSupport": raw_sup,
            "sharedStrata": shared, "trimmedStrata": sorted(set(cats) - set(shared)),
            "nStratumTrimmed": int((~keep).sum()),
            "propensityRange": [round(lo, 4), round(hi, 4)],
            "retainedFraction": {"A": round(frac_a, 3), "B": round(frac_b, 3)},
            "ess": {"A": round(essA, 1), "B": round(essB, 1)},
            "liveCovariateIdx": names_live.tolist(),
            "smdUnweighted": smd_u.tolist(), "smdOverlapWeighted": smd_w.tolist(),
        })
    return out


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def assess_overlap(drives, cohort_key, cohort_a, cohort_b, covariates=None, *,
                   outcome_key=None, cluster_key="date", categorical_key="drive_type",
                   min_support=0.5, min_rows=8, min_ess=8.0):
    """Stand-alone common-support assessment (no outcome needed).  Returns a dict with `ok`."""
    covariates = list(covariates or DEFAULT_COVARIATES)
    okey = outcome_key or "__none__"
    rows = [dict(d, **{okey: 0.0}) for d in drives] if outcome_key is None else drives
    P = _prepare(rows, okey, cohort_key, cohort_a, cohort_b, covariates, cluster_key, categorical_key)
    cfg = {"min_rows": min_rows, "min_support": min_support, "min_ess": min_ess}
    try:
        r = _estimate(P["y"], P["Z"], P["g"], P["cat"], cfg, want_diagnostics=True)
    except _Fail as f:
        return {"ok": False, "reasonCode": f.code, "reason": f.msg, **f.extra}
    r["ok"] = True
    return r


def common_support(drives, covariates, cohort_key, cohort_a, cohort_b, min_overlap=0.5):
    """Backward-compatible wrapper (v1 signature).  Marginal per-covariate range overlap is still
    reported (symmetric: min of A-in-B and B-in-A) for continuity, but the GATE is the v2 assessment
    (categorical strata + propensity overlap + effective sample size)."""
    A = [d for d in drives if d.get(cohort_key) == cohort_a]
    B = [d for d in drives if d.get(cohort_key) == cohort_b]
    per = {}
    for cv in covariates:
        a = [v for v in (_finite(d.get(cv)) for d in A) if v is not None]
        b = [v for v in (_finite(d.get(cv)) for d in B) if v is not None]
        if not a or not b:
            per[cv] = 0.0; continue
        ab = sum(1 for x in a if min(b) <= x <= max(b)) / len(a)
        ba = sum(1 for x in b if min(a) <= x <= max(a)) / len(b)
        per[cv] = round(min(ab, ba), 3)
    v2 = assess_overlap(drives, cohort_key, cohort_a, cohort_b, covariates, min_support=min_overlap)
    mean_o = round(float(np.mean(list(per.values()))), 3) if per else 0.0
    return {"overlap": mean_o, "overlapMin": round(min(per.values()), 3) if per else 0.0,
            "perCovariate": per, "ok": bool(v2["ok"]),
            "reason": None if v2["ok"] else v2.get("reason"), "v2": v2}


def _stratified_cluster_resample(cl, g, rng):
    """Resample clusters with replacement WITHIN strata defined by day composition
    (A-only / B-only / both), so every replicate keeps the original number of clusters of each
    kind and can never lose a cohort by chance.  Returns the row-index array."""
    ids = {}
    for i, c in enumerate(cl):
        ids.setdefault(c, []).append(i)
    strata = {"A": [], "B": [], "AB": []}
    for c, rows in ids.items():
        gs = set(int(g[i]) for i in rows)
        strata["AB" if len(gs) == 2 else ("B" if 1 in gs else "A")].append(c)
    idx = []
    for members in strata.values():
        if not members:
            continue
        pick = rng.integers(0, len(members), size=len(members))
        for k in pick:
            idx.extend(ids[members[k]])
    return np.asarray(idx, int)


def adjusted_contrast(drives, outcome_key, cohort_key, cohort_a, cohort_b,
                      covariates=None, n_boot=2000, min_support=0.5, *,
                      cluster_key="date", categorical_key="drive_type", seed=BOOT_SEED,
                      min_days_per_cohort=5, min_rows_per_cohort=8, min_ess=8.0,
                      max_boot_failure=0.20, equivalence_margin=None):
    """Composition-adjusted B-minus-A contrast in `outcome_key` on the common-support population,
    with a stratified day-cluster bootstrap CI.  See module docstring for the estimand and gates.

    Compatible with the v1 return shape (status, outcome, cohortA/B, adjustedDiff, rawDiff, ci95,
    nA, nB, nDays, covariates, commonSupport, nBoot, interpretation) and adds diagnostics."""
    covariates = list(covariates or DEFAULT_COVARIATES)
    base = {"outcome": outcome_key, "cohortA": cohort_a, "cohortB": cohort_b,
            "estimatorVersion": SEASONAL_ADJUST_VERSION}
    P = _prepare(drives, outcome_key, cohort_key, cohort_a, cohort_b, covariates,
                 cluster_key, categorical_key)
    y, Z, g, cl, cat = P["y"], P["Z"], P["g"], P["cl"], P["cat"]
    nA_all, nB_all = int((g == 0).sum()), int((g == 1).sum())
    daysA = len(set(cl[g == 0].tolist())); daysB = len(set(cl[g == 1].tolist()))
    base.update({"nA": nA_all, "nB": nB_all, "nDaysA": daysA, "nDaysB": daysB,
                 "nDays": len(set(cl.tolist())), "covariates": covariates,
                 "inputAudit": P["counts"]})
    if nA_all == 0 or nB_all == 0:
        return {**base, "status": "unavailable", "reasonCode": "empty_cohort",
                "reason": f"empty cohort (A={nA_all}, B={nB_all})"}
    if min(daysA, daysB) < min_days_per_cohort:
        return {**base, "status": "unavailable", "reasonCode": "too_few_days",
                "reason": f"too few independent days for a cluster bootstrap "
                          f"(A={daysA}, B={daysB}; need {min_days_per_cohort} per cohort)"}

    cfg = {"min_rows": min_rows_per_cohort, "min_support": min_support, "min_ess": min_ess}
    try:
        pt = _estimate(y, Z, g, cat, cfg, want_diagnostics=True)
    except _Fail as f:
        return {**base, "status": "unavailable", "reasonCode": f.code, "reason": f.msg,
                "commonSupport": {"ok": False, "reason": f.msg, **f.extra}}

    live = pt.pop("liveCovariateIdx")
    smd_w = dict(zip([covariates[i] for i in live], [round(v, 3) for v in pt.pop("smdOverlapWeighted")]))
    smd_u = dict(zip([covariates[i] for i in live], [round(v, 3) for v in pt.pop("smdUnweighted")]))
    max_smd_w = max(smd_w.values()) if smd_w else 0.0
    warnings = []
    if max_smd_w > SMD_TOL:
        warnings.append(f"residual_imbalance: max |SMD| after overlap weighting = {max_smd_w:.2f} (> {SMD_TOL})")
    if pt["trimmedStrata"]:
        warnings.append("estimand_restricted_to_shared_strata: " + ",".join(pt["trimmedStrata"])
                        + f" rows excluded ({pt['nStratumTrimmed']})")
    if min(pt["retainedFraction"].values()) < 0.75:
        warnings.append("substantial_trimming: contrast describes a subset of each cohort")

    # ---- stratified full-refit day-cluster bootstrap ----
    seed_i = int(seed) & 0xFFFFFFFF
    rng = np.random.default_rng(seed_i)
    boots, ows, fails = [], [], {}
    for _ in range(int(n_boot)):
        ix = _stratified_cluster_resample(cl, g, rng)
        try:
            r = _estimate(y[ix], Z[ix], g[ix], cat[ix], cfg)
            boots.append(r["gcomp"]); ows.append(r["overlapWeighted"])
        except _Fail as f:
            fails[f.code] = fails.get(f.code, 0) + 1
    n_fail = sum(fails.values()); fail_rate = n_fail / max(1, int(n_boot))
    boot_info = {"nBootRequested": int(n_boot), "nBootValid": len(boots),
                 "bootFailureRate": round(fail_rate, 4), "bootFailureReasons": fails, "seed": seed_i}
    if fail_rate > max_boot_failure or len(boots) < 50:
        return {**base, **boot_info, "status": "unavailable", "reasonCode": "unstable_bootstrap",
                "reason": f"{100*fail_rate:.0f}% of bootstrap replicates could not support the estimator "
                          f"({fails}); no interval is reported",
                "pointEstimateWithheld": True,
                "commonSupport": {"ok": True, "unstable": True}}

    b = np.asarray(boots)
    ci95 = (float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5)))
    ci90 = (float(np.percentile(b, 5.0)), float(np.percentile(b, 95.0)))
    se = float(b.std(ddof=1))
    p_two = float(min(1.0, 2 * min(np.mean(b <= 0), np.mean(b >= 0))))
    p_two = max(p_two, 1.0 / (len(b) + 1))
    bias = float(b.mean() - pt["gcomp"])
    if se > 0 and abs(bias) > 0.25 * se:
        warnings.append(f"bootstrap_bias: mean(boot)-point = {bias:.3g} (> 0.25 SE)")
    gap = pt["overlapWeighted"] - pt["gcomp"]
    half = 0.5 * (ci95[1] - ci95[0])
    model_dependent = bool(half > 0 and abs(gap) > 0.5 * half)
    if model_dependent:
        warnings.append("estimator_disagreement: g-computation and overlap-weighted estimates differ by "
                        f"{gap:.3g} (> half the 95% CI width) -- result is outcome-model dependent")

    res = {
        **base, **boot_info,
        "status": "available",
        "adjustedDiff": round(pt["gcomp"], 4),
        "rawDiff": round(pt["rawDiffAll"], 4),
        "rawDiffOnSupport": round(pt["rawDiffOnSupport"], 4),
        "overlapWeightedDiff": round(pt["overlapWeighted"], 4),
        "estimatorGap": round(gap, 4), "modelDependent": model_dependent,
        "ci95": [round(ci95[0], 4), round(ci95[1], 4)],
        "ci90": [round(ci90[0], 4), round(ci90[1], 4)],
        "bootSe": round(se, 4), "pBoot": round(p_two, 4), "bootBias": round(bias, 4),
        "nOnSupport": {"A": pt["nA"], "B": pt["nB"]},
        "outcomeModel": pt["model"],
        "commonSupport": {
            "ok": True, "method": "categorical strata + propensity min-max overlap + overlap-weight ESS",
            "overlap": round(float(np.mean(list(pt["retainedFraction"].values()))), 3),
            "overlapMin": round(float(min(pt["retainedFraction"].values())), 3),
            "retainedFraction": pt["retainedFraction"], "propensityRange": pt["propensityRange"],
            "sharedStrata": pt["sharedStrata"], "trimmedStrata": pt["trimmedStrata"],
            "ess": pt["ess"], "smdUnweighted": smd_u, "smdOverlapWeighted": smd_w,
            "balanceOk": bool(max_smd_w <= SMD_TOL), "reason": None,
        },
        "warnings": warnings,
        "estimand": "average B-minus-A difference over the common-support population "
                    "(shared strata and propensity overlap); not the pooled-corpus ATE",
        "interpretation": "seasonal operating difference standardized to the common-support "
                          "composition; may include unmeasured cabin-heating/defrost demand "
                          "(no HVAC telemetry)",
    }
    if equivalence_margin is not None:
        m = abs(float(equivalence_margin))
        if ci90[0] > -m and ci90[1] < m:
            dec = "practically_equivalent"
        elif ci95[0] > m or ci95[1] < -m:
            dec = "difference_exceeds_margin"
        else:
            dec = "inconclusive"
        res["equivalence"] = {"margin": m, "rule": "90% bootstrap CI within +/-margin (TOST-equivalent)",
                              "decision": dec}
    return res


def bh_adjust(pvals):
    """Benjamini-Hochberg q-values (monotone) for a list of p-values."""
    m = len(pvals)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [0.0] * m; prev = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        prev = min(prev, pvals[i] * m / rank)
        q[i] = prev
    return q


def adjusted_contrast_family(drives, outcomes, cohort_key, cohort_a, cohort_b, covariates=None,
                             n_boot=2000, alpha=0.05, **kw):
    """Screen several outcomes at once with false-discovery-rate control.

    `outcomes` = {outcome_key: {"margin": optional SESOI}}.  Each outcome uses a seed derived from
    (base seed, outcome key) so results do not depend on evaluation order.  BH q-values are computed
    over the outcomes that reached status 'available'."""
    base_seed = int(kw.pop("seed", BOOT_SEED))
    results = {}
    for k, spec in outcomes.items():
        sd = int(hashlib.sha256(f"{base_seed}:{k}".encode()).hexdigest()[:8], 16)
        results[k] = adjusted_contrast(drives, k, cohort_key, cohort_a, cohort_b, covariates,
                                       n_boot=n_boot, seed=sd,
                                       equivalence_margin=(spec or {}).get("margin"), **kw)
    avail = [k for k, r in results.items() if r["status"] == "available"]
    q = bh_adjust([results[k]["pBoot"] for k in avail])
    for k, qi in zip(avail, q):
        results[k]["qBH"] = round(qi, 4); results[k]["fdrSignificant"] = bool(qi <= alpha)
    return {"results": results,
            "fdr": {"method": "Benjamini-Hochberg", "alpha": alpha, "nTested": len(avail),
                    "nUnavailable": len(results) - len(avail)}}
