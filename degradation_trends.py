"""degradation_trends.py  (M108)

Audit 4.3 / 4.4 remediation: upgrade the two null degradation trends
(cell-spread and V-regression resistance) from "no trend detected" to
statistically defensible statements, using

  (1) a HIERARCHICAL / MIXED-EFFECTS model with a calendar-day random intercept,
      plus a temperature covariate, so repeated drives within a day are not
      treated as independent (the audit's core methodological point);
  (2) a CLUSTER-ROBUST OLS (cluster = day) as a convergence-independent check;
  (3) a LAG-1 residual-autocorrelation diagnostic (does AR-aware modelling
      change the picture?); and
  (4) a TWO ONE-SIDED TESTS (TOST) equivalence test of each slope against a
      pre-registered smallest-effect-of-interest bound delta.

CRITICAL: the equivalence BOUND is a scientific pre-registration decision, not a
statistic to be discovered from the data. Released 2026-08-11 (Andrii, via
delegated selection from the candidate list below with rationale): cell-spread
uses `reach50mV_over14yr` (the only candidate anchored to a named, domain-
meaningful consequence -- the BMS cell-balancing-concern level -- rather than
an arbitrary round number or an unjustified "stricter" alternative); resistance
uses `oem75pct_over14yr` (the OEM's own EU Battery Regulation Article-10
disclosure, mapped over the longer of the two offered horizons, since that is
the stricter of the two OEM-anchored options). The 14-year figure used to
derive these MONTHLY-RATE bounds is a mathematical device only -- it is NOT a
calendar-life claim for this vehicle (that framing was deliberately retracted
elsewhere in this study, M113/M114, as scientifically unsupportable from a
warm-season-only corpus); TOST here tests monthly-rate equivalence to zero,
nothing about years-to-end-of-life. All three candidates per metric remain in
the output for transparency, with the released one flagged explicitly.
Non-released candidates are retained as a record of what was considered, not
as alternative "results."

A non-significant slope is NOT evidence of equivalence unless the equivalence
CI lies inside +/- delta. As of the current ~2.79-month observation window,
equivalence is NOT established under either released bound for either metric
-- the confidence intervals are still wider than the bounds. This is reported
as an honest "inconclusive, window too short" finding, not suppressed or
reframed as a null result by CI-includes-zero alone.

Everything here reads drive_master only (no raw), so it is independently
reproducible in this session.
"""
import numpy as np, pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats

MONTH_DAYS = 30.4375

# M207 (F-07/H-03): SESOI baseline FROZEN at the bound-lock date. These are the
# ens_outlier_v2-clean sample medians as of 2026-08-11 (the date the equivalence
# bounds were locked, per the module docstring). The TOST deltas are derived
# once from these constants and held immutable, so a growing corpus can never
# silently move a "locked" bound. To re-baseline (only with an explicit,
# documented decision), recompute the medians on the clean drives dated <=
# a new lock date and bump these with a new M-tag.
SESOI_BASELINE_DATE = '2026-08-11'
CS_MED_BASELINE_MV = 11.05        # cell_spread_mean_mv median, n=218, <= lockDate
VREG_MED_BASELINE_MOHM = 121.825  # vreg_R_pack_mohm median, n=124, <= lockDate


def _jround(x, nd=4):
    """round() that maps NaN/Inf to None -- bare NaN/Infinity are not valid
    JSON and Python's json.dump silently emits them anyway (allow_nan=True
    by default), which build_html.js's strict JSON.parse then rejects. The
    degenerate mixed-effects case (singular day random-effects covariance,
    e.g. the vreg resistance proxy) is exactly where this triggers."""
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(xf) else round(xf, nd)


def _as_bool(s):
    """NaN-safe boolean coercion (F-14 audit). A bare .astype(bool) maps NaN ->
    True and, on a CSV round-trip that yields the strings 'True'/'False', maps
    the string 'False' -> True as well (any non-empty string is truthy). Both
    would silently mishandle a missing/exported ens_outlier_v2 flag. Map only a
    real True or the literal 'true' (case-insensitive) to True; everything else,
    NaN included, to False -- so a missing exclusion flag is treated as
    not-excluded, matching the canonical exclusion policy."""
    return s.map(lambda x: x is True or str(x).strip().lower() == 'true').astype(bool)


def _prep(dm, ycol, tcol='T_pack_mean_avg', icol=None):
    d = dm[~_as_bool(dm['ens_outlier_v2'])].copy()
    d['date'] = pd.to_datetime(d['date'])
    d = d.dropna(subset=[ycol, 'date'])
    if d.empty:
        return d
    t0 = d['date'].min()
    d['months'] = (d['date'] - t0).dt.total_seconds() / (MONTH_DAYS * 86400)
    d['day'] = d['date'].dt.date.astype(str)
    d['y'] = d[ycol].astype(float)
    d['T'] = d[tcol].astype(float) if tcol in d.columns else np.nan
    # M157 (2026-08-22): optional current covariate, so the loaded cell-spread
    # trend can be estimated in a SINGLE stage on the raw outcome with the same
    # T and peak-current controls that M15 used, instead of the double-count of
    # regressing an already-T-adjusted outcome on T again (audit section 6).
    d['I'] = d[icol].astype(float) if (icol and icol in d.columns) else np.nan
    d = d.dropna(subset=['y', 'months'])
    return d


def _covars_present(d, covars):
    """M157: keep the requested covariates that are majority-present, and report
    the complete-case row set for exactly those. Cell-spread uses ('T','I');
    the resistance proxy uses ('T',). All rows of both metrics carry T, so this
    reproduces the prior ('T',)-only behaviour for the resistance proxy while
    enabling the single-stage T+I model for cell-spread."""
    use = [c for c in covars if c in d.columns and d[c].notna().mean() > 0.5]
    return use


def _mixedlm(d, covars=('T',)):
    """Random-intercept-by-day mixed model. Returns slope on months + 95% CI."""
    use = _covars_present(d, covars)
    formula = 'y ~ months' + ''.join(' + ' + c for c in use)
    dd = d.dropna(subset=list(use)) if use else d
    try:
        md = smf.mixedlm(formula, dd, groups=dd['day'])
        r = md.fit(method='lbfgs', reml=True, disp=False)
        b = float(r.fe_params['months'])
        se = float(r.bse_fe['months'])
        ci = r.conf_int().loc['months'].tolist()
        # M155 (2026-08-22): expose the day random-intercept variance. A value
        # at the boundary (~0) is the mechanistic signature of the singular RE
        # covariance that inflates the fixed-effect SE; recorded for the gate's
        # transparency, not gated on directly (the SE-blowup check is).
        try:
            gvar = float(np.asarray(r.cov_re)[0, 0])
        except Exception:
            gvar = None
        return {'slope': _jround(b), 'se': _jround(se),
                'ci95': [_jround(ci[0]), _jround(ci[1])],
                'nObs': int(dd.shape[0]), 'nDays': int(dd['day'].nunique()),
                'groupVar': _jround(gvar, 6),
                'formula': formula, 'converged': bool(r.converged)}
    except Exception as e:
        return {'error': repr(e), 'formula': formula}


def _cluster_ols(d, covars=('T',)):
    """OLS with cluster-robust (day) SE -- convergence-free check on the slope.
    This is the released estimator for both degradation metrics (the day
    random-intercept mixed model is unidentifiable here -- cell-spread has too
    little within-day variance to separate the random intercept, so its RE
    covariance collapses to the boundary; see the M155/M156 gate)."""
    use = _covars_present(d, covars)
    dd = d.dropna(subset=list(use)) if use else d
    X = sm.add_constant(dd[['months'] + list(use)])
    res = sm.OLS(dd['y'].values, X).fit(cov_type='cluster',
                                        cov_kwds={'groups': dd['day'].values})
    b = float(res.params['months']); se = float(res.bse['months'])
    lo, hi = res.conf_int().loc['months'].tolist()
    # lag-1 residual autocorrelation on day-ordered residuals
    order = dd.sort_values(['day', 'months']).index
    resid = pd.Series(res.resid.values, index=dd.index).loc[order].values
    ac1 = float(np.corrcoef(resid[:-1], resid[1:])[0, 1]) if len(resid) > 3 else np.nan
    return {'slope': _jround(b), 'se': _jround(se),
            'ci95': [_jround(lo), _jround(hi)],
            'nObs': int(dd.shape[0]), 'nDays': int(dd['day'].nunique()),
            'residAutocorrLag1': _jround(ac1, 3),
            'formula': 'y ~ months' + ''.join(' + ' + c for c in use)}


def _tost(slope, se, delta, alpha=0.05, df=None):
    """Two one-sided tests of |slope| < delta. Equivalence declared iff the
    (1-2*alpha) CI is inside (-delta, +delta) AND both one-sided tests reject.

    M158 (2026-08-22): the released estimator is a cluster-robust OLS on day
    clusters, so the reference distribution is a t with the cluster degree of
    freedom (G-1, G = number of day-clusters), NOT the normal. With only 52-60
    day-clusters the normal-z understates the tails; using t(G-1) is the
    conservative, cluster-correct choice the audit asked for (section 6). When
    df is None the normal limit is used (backward-compatible)."""
    if se <= 0 or not np.isfinite(se):
        return {'delta': delta, 'equivalent': None, 'reason': 'invalid SE'}
    dist = stats.norm if (df is None or not np.isfinite(df) or df <= 0) else stats.t(df)
    t_lower = (slope - (-delta)) / se     # H0: slope <= -delta
    t_upper = (slope - delta) / se        # H0: slope >= +delta
    p_lower = 1 - dist.cdf(t_lower)        # reject if slope > -delta
    p_upper = dist.cdf(t_upper)            # reject if slope < +delta
    p_tost = max(p_lower, p_upper)
    crit = dist.ppf(1 - alpha)
    ci = [slope - crit * se, slope + crit * se]  # 90% CI at alpha=0.05
    equiv = (ci[0] > -delta) and (ci[1] < delta)
    return {'delta': round(delta, 4), 'pTOST': round(float(p_tost), 4),
            'equivCI90': [round(float(ci[0]), 4), round(float(ci[1]), 4)],
            'equivalent': bool(equiv),
            'refDist': 'normal' if dist is stats.norm else f't(df={int(df)})'}


def _analyse(dm, ycol, unit, bounds, released_label, covars=('T',), icol=None):
    d = _prep(dm, ycol, icol=icol)
    if d.empty or d.shape[0] < 8:
        return {'ycol': ycol, 'n': int(d.shape[0]), 'error': 'insufficient data'}
    mm = _mixedlm(d, covars=covars)
    co = _cluster_ols(d, covars=covars)
    # TOST uses the cluster-robust slope/SE (correct day-level inference,
    # convergence-independent). Candidate bounds only.
    # Pick the reliable estimator: prefer the mixed model, but fall back to the
    # cluster-robust OLS when the day random-effects covariance is singular
    # (happens when a metric has too few drives/day to separate within-day
    # variance, e.g. the load-excited vreg proxy).
    # M155 (2026-08-22): harden the mixed-model acceptance gate. A finite,
    # positive fixed-effect SE is NOT sufficient. statsmodels can report
    # converged==True on a SINGULAR day random-effects covariance and still
    # return a fixed-effect SE inflated by ~9 orders of magnitude (cellSpread:
    # se=5.23e8 mV/mo, 95% CI +/-1.03e9) -- a numerical artifact, not an
    # estimate, that the old finite-and-positive test admitted as PRIMARY and
    # then fed into the TOST (tostSeUsed=5.23e8, equivCI90=+/-8.6e8). The mixed
    # model is now accepted as primary only if it (a) returned a finite,
    # positive SE, (b) converged, and (c) that SE is not blown up relative to
    # the convergence-free cluster-robust OLS SE -- the boundary/singular tell.
    # Otherwise the cluster-robust OLS is authoritative and the released slope
    # inherits its slope/SE via the (b, se) selection below. (Post-P0-05 the TOST
    # ALWAYS uses the cluster-robust OLS regardless of this selection -- see the
    # equivalence-test block below -- so a mixed-primary metric no longer feeds a
    # mixed slope/SE into a cluster-derived df.) This fits no new model; it stops
    # publishing an already-computed singular one. Audit remediation, section 6
    # "Critical released-model failure".
    SE_BLOWUP_FACTOR = 25.0    # order-of-magnitude guard: the singular case
                               # exceeds it by ~1e8, any valid fit is far under.
    mm_se = mm.get('se')
    co_se = co.get('se')
    se_finite_pos = (mm_se is not None and np.isfinite(mm_se) and mm_se > 0)
    se_not_blownup = (se_finite_pos and co_se is not None and co_se > 0
                      and mm_se <= SE_BLOWUP_FACTOR * co_se)
    me_ok = ('slope' in mm and se_finite_pos
             and bool(mm.get('converged', False)) and se_not_blownup)
    primary = 'mixedEffects' if me_ok else 'clusterRobustOLS'
    if not me_ok:
        mm['degenerate'] = True
        if 'slope' not in mm:
            reason = ('mixed model failed to fit (' + str(mm.get('error', 'unknown'))
                      + ')')
        elif not bool(mm.get('converged', False)):
            reason = 'mixed-model optimiser did not converge'
        elif not se_finite_pos:
            reason = 'fixed-effect SE non-finite or non-positive'
        else:
            reason = ('singular day random-effects covariance: fixed-effect SE '
                      f'({mm_se:.3g}) exceeds {SE_BLOWUP_FACTOR:g}x the '
                      f'convergence-free cluster-robust OLS SE ({co_se:.3g})')
        mm['degenerateNote'] = (
            reason + '. Cluster-robust OLS is authoritative for this metric; '
            'both the released slope and the TOST use its slope/SE. The '
            'mixed-effects block is retained for transparency only '
            '(M155, 2026-08-22).')
        if mm.get('groupVar') is not None:
            mm['reCovarianceSingular'] = bool(mm['groupVar'] <= 1e-8)
    # Headline point estimate: prefer the mixed model when it is a valid,
    # non-singular fit; otherwise the cluster-robust OLS (see `primary` above).
    b, se = (mm['slope'], mm['se']) if me_ok else (co['slope'], co['se'])
    # --- Equivalence test (TOST) estimator basis --------------------------
    # P0-05 (audit 2026-08-27): a TOST is only valid if slope, SE, AND the
    # reference distribution come from ONE coherent inferential model. The
    # previous code paired the *mixed-model* slope/SE (when me_ok) with a t(G-1)
    # reference whose df is the *cluster-OLS* day-clustering degree of freedom --
    # an invalid hybrid. The M158 note asserted the mixed-primary branch was
    # "not reachable ... both are OLS"; at 289 drives that is FALSE: resistanceVreg
    # now fits a non-singular mixed model and is primary, so its slope/SE were
    # being tested against a cluster-derived df. The guard's own assumption went
    # stale as the corpus grew -- exactly the failure mode the audit warns about.
    #
    # Resolution (audit option "use cluster OLS throughout"): the TOST is, by
    # construction (module docstring / M158), the day-clustered equivalence test,
    # and the cluster-robust OLS is the convergence-independent estimator whose
    # small-sample reference t(G-1) is valid. So the equivalence test ALWAYS uses
    # the cluster-robust OLS slope/SE/df, regardless of which estimator is the
    # headline primaryEstimator. This makes slope, SE, and reference distribution
    # mutually consistent and flips no scientific conclusion (cluster and mixed
    # slopes agree to <0.01 units on both metrics). A mixed-model equivalence test
    # with a proper Kenward-Roger / Satterthwaite df is a separate, larger task
    # and is deliberately NOT attempted here.
    tost_b, tost_se = co['slope'], co['se']
    tost_df = (co.get('nDays') - 1) if co.get('nDays') else None
    tost = [{**{'label': lab, 'rationale': rat},
             **_tost(tost_b, tost_se, dlt, df=tost_df)}
            for lab, dlt, rat in bounds]
    released = next((t for t in tost if t['label'] == released_label), None)
    return {
        'ycol': ycol, 'unit': unit, 'nObs': int(d.shape[0]),
        'nDays': int(d['day'].nunique()),
        'windowMonths': round(float(d['months'].max()), 2),
        'primaryEstimator': primary,
        # P0-05: the equivalence test is always the day-clustered cluster-robust
        # OLS (slope/SE/df from one model); the headline primaryEstimator above
        # may differ (it is the point-estimate preference). Both fits are exposed
        # below (mixedEffects / clusterRobustOLS) for full transparency.
        'tostEstimatorBasis': 'clusterRobustOLS',
        'tostSlopeUsed': round(float(tost_b), 4),
        'tostSeUsed': round(float(tost_se), 4),
        'mixedEffects': mm, 'clusterRobustOLS': co,
        'releasedBoundLabel': released_label,
        'releasedEquivalence': released,
        'tostCandidates': tost,
        'equivalenceBoundStatus': (
            'LOCKED 2026-08-11 -- released bound is releasedEquivalence '
            f'({released_label}); other candidates retained for transparency, '
            'not as alternative results. See module docstring for the '
            'pre-registration rationale.')}


def build(master_csv_or_df='drive_master.csv'):
    """master_csv_or_df: a path (standalone CLI use) or an already-loaded
    DataFrame (in-process call from compute_summary_arrays.py, guaranteeing
    the exact same drive_master snapshot as the rest of the pipeline rather
    than a possibly-stale re-read)."""
    dm = (master_csv_or_df if isinstance(master_csv_or_df, pd.DataFrame)
          else pd.read_csv(master_csv_or_df))
    # Candidate equivalence bounds (delta, per month) -- rationale-labelled.
    # RELEASED bound is fixed per the module docstring; other candidates are
    # retained for transparency only, not offered as alternative results.
    life_mo = 14 * 12  # mathematical horizon for deriving a monthly rate only
    # M207 (F-07/H-03): the TOST deltas MUST NOT recompute from the current
    # sample median each run -- a data-dependent moving bound is not a locked
    # pre-registration (audit F-07). They are frozen at the pre-registration
    # baseline-window medians (SESOI_BASELINE_*), computed once on the
    # ens_outlier_v2-clean drives dated <= the 2026-08-11 bound-lock date. Live
    # medians below (cs_med_cur / vr_med_cur) are used ONLY for the displayed
    # current-level reference fields, never for the equivalence bounds.
    cs_med = CS_MED_BASELINE_MV
    vr_med = VREG_MED_BASELINE_MOHM
    cs_med_cur = float(dm.loc[~_as_bool(dm['ens_outlier_v2']),
                              'cell_spread_mean_mv'].median())
    vr_med_cur = float(dm.loc[~_as_bool(dm['ens_outlier_v2']),
                             'vreg_R_pack_mohm'].median())
    cell_bounds = [
        ('reach50mV_over14yr', (50 - cs_med) / life_mo,
         f'unloaded spread grows from {cs_med:.1f} mV to a 50 mV balancing-'
         f'concern level over the ~14 yr horizon'),
        ('reach30mV_over14yr', (30 - cs_med) / life_mo,
         f'stricter: reach 30 mV over 14 yr'),
        ('round_0p10', 0.10, 'round 0.10 mV/month reference'),
    ]
    vreg_bounds = [
        ('oem75pct_over14yr', 0.75 * vr_med / life_mo,
         f'OEM-disclosed +75% internal-resistance rise mapped FRACTIONALLY onto '
         f'the proxy median ({vr_med:.1f} mOhm) over 14 yr; not an absolute-level '
         f'comparison to the 0.21 Ohm figure'),
        ('oem75pct_over10yr', 0.75 * vr_med / (10 * 12),
         'same fractional rise over a stricter 10 yr horizon'),
        ('round_0p5', 0.5, 'round 0.5 mOhm/month reference'),
    ]
    out = {
        # M157 (2026-08-22): SINGLE-STAGE model on the RAW loaded cell-spread,
        # controlling for pack temperature and peak discharge current ONCE each
        # -- the same covariates M15 used to build the *_adj_mv column, but in
        # one stage. Replaces the prior double-count (regressing the already
        # T/I-adjusted outcome on T again). Reproduces the audit's own
        # "Raw spread, linear T + I" reference exactly (slope -0.331 mV/mo,
        # cluster-robust OLS, CI [-0.850, 0.188]). The mixed model is
        # unidentifiable for this outcome (day RE variance at the boundary), so
        # the M155/M156 gate keeps cluster-robust OLS as the released estimator.
        'cellSpread': _analyse(dm, 'cell_spread_loaded_p95_mv',
                               'mV/month', cell_bounds, 'reach50mV_over14yr',
                               covars=('T', 'I'), icol='peak_I_discharge'),
        'resistanceVreg': _analyse(dm, 'vreg_R_pack_mohm',
                                   'mOhm/month', vreg_bounds, 'oem75pct_over14yr',
                                   covars=('T', 'I'), icol='vreg_I_p95_A'),
        # M161 (2026-08-22): the resistance proxy is now controlled for the load
        # current present during the measurement (vreg_I_p95_A), matching the
        # dashboard powerFade block's spec (months + T + current). This
        # reconciles the two resistance trends the audit flagged as divergent:
        # the under-specified months+T model gave 1.432 mOhm/mo, this gives
        # 1.186 mOhm/mo -- one estimate, reproducing the audit's own "V-reg
        # resistance, linear T + I" reference (1.186, CI [-0.517, 2.890]).
        # M207 (C-04/F-08): the resistance proxy here is controlled for load
        # current (vreg_I_p95_A) but NOT for HV-current logging cadence, which
        # this module (no raw access) cannot measure. Logging density ~doubled
        # mid-corpus (M126) and biases the load-excited proxy upward, so this
        # cadence-UNCONTROLLED months+T+I fit returns ~+1.16 to +1.19 mOhm/mo
        # depending on estimator/window (clusterRobustOLS on the current
        # 315-drive corpus: +1.1617, CI [-0.2908, 2.6141]) -- an
        # instrumentation artifact, NOT pack aging. It is retained as a labelled
        # SENSITIVITY. The PRIMARY resistance estimand is the powerFade block
        # (M170 cadence-controlled). The prior claim that this block gives "one
        # reconciled resistance estimate" matching powerFade was FALSE (powerFade
        # is +0.013 mOhm/mo, p=0.497, once cadence is held constant) and is
        # withdrawn; see
        # compute_summary_arrays._reconcile_resistance_models / the
        # resistanceReconciliation block for the empirical decomposition.
        'note': ('M108. Mixed-effects (day random intercept) + cluster-robust '
                 'OLS + TOST equivalence. Replaces "no trend detected" with '
                 'day-correct inference and an explicit equivalence test. '
                 'Absence of a significant slope is NOT equivalence unless the '
                 'equivalence CI lies inside +/- delta. Equivalence bounds '
                 'were locked 2026-08-11 before this result was inspected; see '
                 'releasedBoundLabel/releasedEquivalence in each metric block. '
                 'M155-M158: singular cell-spread mixed model removed as the '
                 'released estimator (cluster-robust OLS is authoritative for '
                 'both metrics; the day random intercept is unidentifiable '
                 'here); cell-spread fit single-stage on the raw loaded-p95 '
                 'outcome with T + peak-current controls (no double temperature '
                 'adjustment); TOST reference distribution is t(G-1), G = '
                 'day-clusters. M207 (C-04/F-08): resistanceVreg is the '
                 'sensitivity without the HV-current-density covariates (months + T + load current); '
                 'the PRIMARY resistance estimand is powerFade (M170 '
                 'HV-current-density adjusted, a partial adjustment). Logging density raises the proxy '
                 '(M393 emulation), so this slope is not read as a fade rate -- see '
                 'powerFade.cadenceSensitivity.')}
    out['cellSpread']['restingSpreadMedianMv'] = round(cs_med_cur, 1)
    out['resistanceVreg']['proxyMedianMohm'] = round(vr_med_cur, 1)
    out['sesoiBasis'] = {
        'lockDate': SESOI_BASELINE_DATE,
        'note': ('Equivalence deltas are FROZEN at the pre-registration '
                 'baseline-window medians (ens_outlier_v2-clean, date <= '
                 'lockDate); they do NOT recompute from the current sample '
                 'median (audit F-07/H-03). Current live medians are reported '
                 'as restingSpreadMedianMv / proxyMedianMohm for reference only.'),
        'cellSpreadMedianMvBaseline': CS_MED_BASELINE_MV,
        'cellSpreadMedianMvCurrent': round(cs_med_cur, 2),
        'vregMedianMohmBaseline': VREG_MED_BASELINE_MOHM,
        'vregMedianMohmCurrent': round(vr_med_cur, 2)}
    # M207 (C-04/F-08): mark this block's inferential role explicitly so the
    # dashboard cannot present it as a competing authoritative resistance trend.
    out['resistanceVreg']['role'] = 'sensitivity_cadence_uncontrolled'
    out['resistanceVreg']['cadenceControlled'] = False
    out['resistanceVreg']['primaryEstimandRef'] = 'powerFade'
    return out


if __name__ == '__main__':
    import json
    r = build()
    print(json.dumps(r, indent=1))
