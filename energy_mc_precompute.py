"""energy_mc_precompute.py  (M163, 2026-08-22)

Tier 1 of the audit-section-5 remediation ("Add Monte Carlo or block-bootstrap
propagation for current offset, I/V alignment, assumed capacity, logger
quantization and missing-sample coverage"). This module reads each drive's RAW
current/voltage samples ONCE and derives, per drive, everything the Monte Carlo
(energy_uncertainty_mc.py) needs to run WITHOUT re-touching raw data on every
draw:

  1. gross_discharge/charge/throughput_kwh on a small I<->V alignment-tolerance
     grid (500/750/.../2000 ms) -- a real re-integration at each tolerance,
     using the EXACT algorithm in compute_drive_summary_v6.py (same COL_MAP,
     same artifact filters, same discharge-positive sign convention, same
     DT_CAP_S=5s integration-step cap, same merge_asof nearest-within-
     tolerance). Cross-validated against the shipped drive_master.csv columns
     at the nominal 1500 ms tolerance -- the pipeline's own working value --
     as a correctness check on this independent re-implementation.
  2. An ANALYTIC (delta-method) standard deviation of gross_throughput_kwh
     under ADC quantization noise on the raw current/voltage channels. Because
     the corpus has O(1e3-1e4) samples per drive, injecting literal per-sample
     quantization noise thousands of times per drive per Monte Carlo draw is
     wasteful; the standard linear-error-propagation result for a weighted sum
     of independent per-sample errors is used instead (see _quant_sd),
     computed once per drive here.
  3. Gap/coverage diagnostics: the total EXCESS time beyond the pipeline's
     DT_CAP_S=5s cap (time silently dropped from every logging gap longer than
     5s -- a one-sided, conservative truncation, never an over-count) and a
     per-drive characteristic |power| to bound how much energy that truncation
     could plausibly be hiding.
  4. Current-offset-on-GROSS-metrics sensitivity. offsetUncertainty.correction
     Scope (M13/M24) applies the fitted current-sensor offset to NET draw and
     residuals ONLY, explicitly noting: "GTC/FCE/gross throughput integrate
     |I| and are NOT offset-corrected in code -- a constant bias sums under
     the absolute value rather than cancelling, so its gross-metric effect is
     asymmetric and cannot be recovered from master aggregates; quantifying it
     requires a raw re-integration pass." This module IS that pass: it
     re-integrates once at offset=0 (current convention) and once at the
     released point-estimate offset (-0.4093 A, sample-level subtraction from
     raw current, not the coarser scalar V*h approximation used for net
     draw), giving a local per-drive sensitivity (d gross metric / d offset)
     for the Monte Carlo to project across the offset's bootstrap CI.

Output: one row per drive (dict), written to energy_mc_precompute.json. No
drive_master.csv or summary_arrays.json write here -- this is an intermediate,
inspectable artifact; energy_uncertainty_mc.py consumes it.

M220.1 (2026-09-04, P0.4 closure): added _integration_alt_estimators(), a
genuinely independent methodological cross-check (three alternative
re-integrations plus a coulomb-counting/SoC cross-check -- see its own
docstring) alongside the pre-existing same-algorithm validation above. The
same-algorithm check confirms this module is not a redrafted approximation
of compute_drive_summary_v6.py (a coding-bug check); it does not, by
itself, test the ALGORITHM's own accuracy, which is what M220.1 adds.
"""
import json
import numpy as np
import pandas as pd

# ---- constants, copied verbatim from compute_drive_summary_v6.py so this
# independent re-implementation exercises the SAME algorithm, not a redrafted
# approximation of it. ----
CAP_KWH = 2.1
DT_CAP_S = 5.0
V_ALIGN_TOL_MS = 1500          # released nominal tolerance
TOL_GRID_MS = [500, 750, 1000, 1250, 1500, 1750, 2000]  # audit's own sweep
COL_MAP = {
    '[BMS] HV Battery Current (A)': 'I',
    '[BMS] HV Battery voltage (V)': 'V',
    # M220.1 (P0.4 closure): SoC read alongside I/V in the SAME raw pass
    # (one extra usecols column, not a second file read) -- used only by
    # the new coulombCrossCheck estimator below, nowhere else in this
    # module.
    '[BMS] HV State of charge (%)': 'soc',
}
OFFSET_POINT_A = -0.4062       # released two-pass offset. FALLBACK DEFAULT only:
                                # __main__ sources the current value from
                                # summary_arrays.json (P1-02, audit 2026-08-27).

# ADC quantization half-steps. Empirically estimated as the minimum nonzero
# gap between distinct raw values pooled across the corpus (see M163
# CHANGELOG for the pooled estimation run); a uniform quantization bin of
# width q has variance q^2/12.
Q_I_A = 0.05      # current LSB, amps
Q_V_V = 0.02      # voltage LSB, volts (see note in build(): 0.16 V min-gap
                  # on a single short file was a coarse polling-rate artifact,
                  # not the true ADC step; the pooled corpus-wide estimate is
                  # used instead -- see build()'s _estimate_lsb call)


def _series(df, t, col, lo=None, hi=None):
    """Verbatim port of compute_drive_summary_v6.py's _series."""
    if col not in df.columns:
        return None
    m = df[col].notna()
    if not m.any():
        return None
    s = pd.DataFrame({'t': t[m].values, 'v': df.loc[m, col].astype(float).values})
    if lo is not None:
        s = s[s['v'] >= lo]
    if hi is not None:
        s = s[s['v'] <= hi]
    return s.sort_values('t').reset_index(drop=True)


def _integrate(I, V, tol_ms, offset_a=0.0):
    """One trapezoidal re-integration pass at a given I<->V tolerance and an
    optional constant current-offset subtraction (sample-level, applied to
    the discharge-positive current before the +/- split -- this is the
    'raw re-integration pass' offsetUncertainty.correctionScope calls for).
    Returns (discharge_kwh, charge_kwh, throughput_kwh, e) where e is the
    aligned working frame (reused by the quantization/gap diagnostics so
    those don't re-merge).

    Faithful to compute_drive_summary_v6.py's own convention: if NO current
    sample finds a voltage match within tolerance (e.g. a drive whose V
    channel polls too sparsely relative to a tight tolerance -- two real
    drives in this corpus, ~4s V-polling, hit exactly this at 500-1500ms),
    the released pipeline's eE[eE>0].sum() over an empty frame silently
    returns 0.0, not NaN -- both drives show literal 0.0/-0.0 in
    drive_master.csv, not a missing value. Returning 0.0 here (rather than
    None) for e too short to trust reproduces that behaviour exactly, and
    correctly lets these drives show LARGE relative tolerance-sensitivity in
    the grid (their V coverage genuinely does improve as tolerance widens) --
    real uncertainty the Monte Carlo should carry, not hide."""
    e = pd.merge_asof(I, V.rename(columns={'v': 'V'}), on='t',
                      direction='nearest',
                      tolerance=pd.Timedelta(f'{tol_ms}ms')).dropna(subset=['V'])
    e = e.reset_index(drop=True)
    if len(e) < 2:
        return 0.0, 0.0, 0.0, e
    e['Id'] = -e['v'] - offset_a   # discharge-positive, offset subtracted
    e['P'] = e['Id'] * e['V'] / 1000.0
    gap_s = e['t'].diff().dt.total_seconds()
    dt_h = gap_s.clip(lower=0, upper=DT_CAP_S).fillna(0) / 3600.0
    # F11 (M229): zero-crossing-aware directional integration, byte-for-byte the
    # same construction as compute_drive_summary_v6.py's F01 repair. Forming the
    # trapezoidal mid-power before the +/- split let within-interval
    # discharge<->charge crossings cancel in the gross metrics; splitting the
    # piecewise-linear power at its zero crossing removes that cancellation while
    # leaving non-crossing intervals byte-identical to the released trapezoid.
    _P = e['P'].to_numpy()
    _dt = dt_h.to_numpy()
    _p0 = np.nan_to_num(np.concatenate([[np.nan], _P[:-1]]), nan=0.0)
    _cross = (_p0 * _P) < 0
    _absum = np.abs(_p0) + np.abs(_P)
    _den = np.where(_absum > 0, 2.0 * _absum, 1.0)
    _disc_c = _dt * ((_p0 > 0) * _p0**2 + (_P > 0) * _P**2) / _den
    _chg_c = _dt * ((_p0 < 0) * _p0**2 + (_P < 0) * _P**2) / _den
    _signed = _dt * (_p0 + _P) / 2.0
    _disc = np.where(_cross, _disc_c, np.where(_signed > 0, _signed, 0.0))
    _chg = np.where(_cross, _chg_c, np.where(_signed < 0, -_signed, 0.0))
    dis = float(_disc.sum())
    chg = float(_chg.sum())
    e['gap_s'] = gap_s
    e['dt_h'] = dt_h
    return dis, chg, dis + chg, e


def _integration_alt_estimators(I, V, soc, dis_ref, chg_ref,
                                tol_ms=V_ALIGN_TOL_MS, cap_kwh=CAP_KWH):
    """M220.1 (P0.4 closure, plan item 220.1): three alternative
    re-integrations plus a coulomb-counting cross-check, all operating on
    the SAME native (pre-resample) I/V/SoC series already loaded per drive
    for the tolerance grid above -- genuinely different numerical methods
    from _integrate()'s trapezoidal-on-nearest-match algorithm, which
    build()'s own 'validation' block already documents as literally the
    SAME algorithm as compute_drive_summary_v6.py (a coding-bug check on
    this independent re-implementation, not a methodologically independent
    cross-check). dis_ref/chg_ref: this drive's released gross_discharge/
    charge_kwh at the nominal tolerance (from the grid already computed
    above) -- used only as the comparison baseline, never re-derived here.

    1. trueTrapezoidal -- I and V linearly interpolated (NOT nearest-
       matched) onto the union of their own native timestamps, restricted
       to each channel's own coverage (no extrapolation), then trapezoidal
       integration of the reconstructed P=I*V. Differs from _integrate()
       in HOW the two asynchronous channels are combined (continuous
       interpolation vs. nearest-within-tolerance snap), the closest
       textbook ground truth available without inventing samples.
    2. midpointRule -- power at each interval's MIDPOINT time, looked up
       via sample-and-hold (last-known-value, zero-order-hold) from each
       channel's OWN native series, times the interval width. A genuinely
       different continuity assumption from trapezoidal's implicit
       piecewise-linear one -- re-evaluating trapezoidal's own linear
       reconstruction at the midpoint would be numerically identical to
       trapezoidal on a piecewise-linear function, so it would not test
       anything; sample-and-hold is the standard alternative assumption
       for how a real embedded logger's value persists between samples.
    3. downsampleComparison1Hz -- the production nearest-matched frame at
       the released tolerance, resampled onto a uniform 1 Hz grid (linear
       interpolation, gap-filling capped at DT_CAP_S so a genuine multi-
       second coverage gap is not silently bridged) and re-integrated
       trapezoidally. Bounds what the 1 Hz grid convention used elsewhere
       in this pipeline (engine-state classification, hazard models, etc.)
       would cost if applied to energy integration too -- the production
       energy metrics themselves never resample.
    4. coulombCrossCheck -- current ALONE (Ah) integrated over I's own
       native timeline (no V dependence in the integration step), converted
       through the assumed CAP_KWH and this drive's own time-averaged pack
       voltage to an expected SoC delta, compared against the OBSERVED SoC
       delta (BMS-reported) over the matched window. Structurally
       independent of the power-integration checks above (uses the SoC
       channel, not a re-integration of P) -- an indirect, corpus-wide read
       on CAP_KWH's internal consistency, not a capacity measurement
       (CAP_KWH remains constantProvenance.verified=false regardless of
       this check's outcome).

    Returns a dict; any sub-block that cannot be computed for this drive
    carries {'skipped': reason} rather than a fabricated value.
    """
    out = {}

    # ---- shared reconstruction for (1)/(2): union of I's and V's own
    # native timestamps, each channel interpolated onto that union,
    # restricted to its own coverage span. ----
    try:
        Is = I.drop_duplicates(subset='t').set_index('t')['v'].sort_index()
        Vs = V.drop_duplicates(subset='t').set_index('t')['v'].sort_index()
        ts = Is.index.union(Vs.index)
        if len(ts) < 3:
            raise ValueError('insufficient union timeline')
        I_i = Is.reindex(ts).interpolate(method='time', limit_area='inside')
        V_i = Vs.reindex(ts).interpolate(method='time', limit_area='inside')
        ok = I_i.notna().to_numpy() & V_i.notna().to_numpy()
        ts_ok = ts[ok]
        I_ok = I_i.to_numpy()[ok]
        V_ok = V_i.to_numpy()[ok]
        if len(ts_ok) < 3:
            raise ValueError('insufficient overlap after interpolation')
        Id_ok = -I_ok
        Pw = Id_ok * V_ok / 1000.0
        gap_s = np.diff(ts_ok.values).astype('timedelta64[ns]').astype(np.float64) / 1e9
        dt_h = np.clip(gap_s, 0, DT_CAP_S) / 3600.0

        # -- (1) true trapezoidal -- F11 (M229): zero-crossing-aware, matching
        # the primary _integrate and the F01 repair. As a same-convention
        # reproducibility cross-check this should now deviate from the reference
        # by ~0; leaving the old mid-power-before-split form here would have
        # manufactured a spurious ~2.5% "convention" spread that is really the
        # integration defect, inflating the Monte-Carlo band.
        p0 = Pw[:-1]
        p1 = Pw[1:]
        cross = (p0 * p1) < 0
        absum = np.abs(p0) + np.abs(p1)
        den = np.where(absum > 0, 2.0 * absum, 1.0)
        disc_c = dt_h * ((p0 > 0) * p0**2 + (p1 > 0) * p1**2) / den
        chg_c = dt_h * ((p0 < 0) * p0**2 + (p1 < 0) * p1**2) / den
        signed = dt_h * (p0 + p1) / 2.0
        disc_tt = np.where(cross, disc_c, np.where(signed > 0, signed, 0.0))
        chg_ttv = np.where(cross, chg_c, np.where(signed < 0, -signed, 0.0))
        dis_tt = float(disc_tt.sum()); chg_tt = float(chg_ttv.sum())
        out['trueTrapezoidal'] = {
            'dischargeKwh': round(dis_tt, 6), 'chargeKwh': round(chg_tt, 6),
            'throughputKwh': round(dis_tt + chg_tt, 6),
            'devDischargeKwh': round(dis_tt - dis_ref, 6),
            'devChargeKwh': round(chg_tt - chg_ref, 6),
            'devThroughputKwh': round((dis_tt + chg_tt) - (dis_ref + chg_ref), 6)}

        # -- (2) midpoint rule, sample-and-hold at each interval's midpoint --
        t_mid = ts_ok[:-1] + (ts_ok[1:] - ts_ok[:-1]) / 2
        I_mid = Is.reindex(Is.index.union(t_mid)).ffill().reindex(t_mid).to_numpy()
        V_mid = Vs.reindex(Vs.index.union(t_mid)).ffill().reindex(t_mid).to_numpy()
        mgood = ~(np.isnan(I_mid) | np.isnan(V_mid))
        Id_mid = -I_mid
        P_mid = Id_mid * V_mid / 1000.0
        eE2 = np.where(mgood, P_mid * dt_h, 0.0)
        dis_mp = float(eE2[eE2 > 0].sum()); chg_mp = float(-eE2[eE2 < 0].sum())
        out['midpointRule'] = {
            'dischargeKwh': round(dis_mp, 6), 'chargeKwh': round(chg_mp, 6),
            'throughputKwh': round(dis_mp + chg_mp, 6),
            'devDischargeKwh': round(dis_mp - dis_ref, 6),
            'devChargeKwh': round(chg_mp - chg_ref, 6),
            'devThroughputKwh': round((dis_mp + chg_mp) - (dis_ref + chg_ref), 6),
            'nMidpointsUnresolved': int((~mgood).sum())}
    except Exception as _e:
        out['trueTrapezoidal'] = {'skipped': f'error: {_e!r}'}
        out['midpointRule'] = {'skipped': f'error: {_e!r}'}

    # ---- (3) downsample comparison: production nearest-matched frame at
    # the released tolerance, resampled onto a uniform 1 Hz grid. ----
    try:
        dis_p, chg_p, thr_p, e_nom = _integrate(I, V, tol_ms)
        if e_nom is not None and len(e_nom) >= 3 and 'P' in e_nom.columns:
            s = e_nom.set_index('t')['P'].sort_index()
            s = s[~s.index.duplicated()]
            grid1hz = pd.date_range(s.index.min(), s.index.max(), freq='1s')
            s_rs = (s.reindex(s.index.union(grid1hz))
                     .interpolate(method='time', limit=int(DT_CAP_S))
                     .reindex(grid1hz))
            Pv = s_rs.to_numpy()
            good = ~np.isnan(Pv)
            P1 = np.where(good, Pv, 0.0)
            P_avg1 = (P1[1:] + P1[:-1]) / 2.0
            seg_ok = good[1:] & good[:-1]
            dt_h1 = np.full(len(grid1hz) - 1, 1.0 / 3600.0)
            eE1 = np.where(seg_ok, P_avg1 * dt_h1, 0.0)
            dis_1h = float(eE1[eE1 > 0].sum()); chg_1h = float(-eE1[eE1 < 0].sum())
            out['downsampleComparison1Hz'] = {
                'dischargeKwh': round(dis_1h, 6), 'chargeKwh': round(chg_1h, 6),
                'throughputKwh': round(dis_1h + chg_1h, 6),
                'devDischargeKwh': round(dis_1h - dis_ref, 6),
                'devChargeKwh': round(chg_1h - chg_ref, 6),
                'devThroughputKwh': round((dis_1h + chg_1h) - (dis_ref + chg_ref), 6),
                'nSegmentsDroppedForGap': int((~seg_ok).sum())}
        else:
            out['downsampleComparison1Hz'] = {'skipped': 'nominal-tolerance frame unavailable'}
    except Exception as _e:
        out['downsampleComparison1Hz'] = {'skipped': f'error: {_e!r}'}

    # ---- (4) coulomb-counting cross-check ----
    try:
        if soc is None or len(soc) < 2 or len(I) < 3 or len(V) < 3:
            out['coulombCrossCheck'] = {'skipped': 'soc/I/V unavailable'}
        else:
            Iv = I.sort_values('t')
            t_i = Iv['t'].values
            gap_s_i = np.diff(t_i).astype('timedelta64[ns]').astype(np.float64) / 1e9
            dt_h_i = np.clip(gap_s_i, 0, DT_CAP_S) / 3600.0
            Id_i = (-Iv['v']).to_numpy()
            Id_avg = (Id_i[1:] + Id_i[:-1]) / 2.0
            net_ah = float(np.sum(Id_avg * dt_h_i))       # +discharge, -charge
            v_nom = float(V['v'].mean())                  # this drive's own
                                                            # time-averaged pack V
            expected_kwh = net_ah * v_nom / 1000.0
            expected_soc_delta_pp = -100.0 * expected_kwh / cap_kwh
            t0, t1 = pd.Timestamp(t_i[0]), pd.Timestamp(t_i[-1])
            soc_sorted = soc.sort_values('t').rename(columns={'v': 'soc'})
            anchor = pd.DataFrame({'t': [t0, t1]})
            matched = pd.merge_asof(anchor, soc_sorted, on='t',
                                    direction='nearest',
                                    tolerance=pd.Timedelta('180s'))
            if matched['soc'].isna().any():
                out['coulombCrossCheck'] = {
                    'skipped': 'no SoC sample within 180s of window edge'}
            else:
                soc_start = float(matched['soc'].iloc[0])
                soc_end = float(matched['soc'].iloc[1])
                observed_soc_delta_pp = soc_end - soc_start
                out['coulombCrossCheck'] = {
                    'netCoulombAh': round(net_ah, 4),
                    'vNominalUsedV': round(v_nom, 2),
                    'expectedSocDeltaPp': round(expected_soc_delta_pp, 3),
                    'observedSocDeltaPp': round(observed_soc_delta_pp, 3),
                    'devSocDeltaPp': round(
                        expected_soc_delta_pp - observed_soc_delta_pp, 3)}
    except Exception as _e:
        out['coulombCrossCheck'] = {'skipped': f'error: {_e!r}'}

    return out


def _aggregate_independent_integration_check(rows, tol_ms=V_ALIGN_TOL_MS):
    """M220.1: pool per-drive independentIntegrationCheck results into
    corpus-wide deviation stats (maxAbsDev/meanAbsDev/p95AbsDev, in Wh and
    as % of that drive's own released throughput) for each of the three
    alternative integration estimators, plus pooled coulomb cross-check
    stats (percentage points of SoC)."""
    methods = ['trueTrapezoidal', 'midpointRule', 'downsampleComparison1Hz']
    agg = {}
    for m in methods:
        devs_wh, devs_pct = [], []
        n_skipped = 0
        for r in rows:
            blk = (r.get('independentIntegrationCheck') or {}).get(m)
            if not blk or 'devThroughputKwh' not in blk:
                n_skipped += 1
                continue
            dev_wh = abs(blk['devThroughputKwh']) * 1000.0
            devs_wh.append(dev_wh)
            ref_thr = (r.get('grid') or {}).get(tol_ms, {}).get('throughput')
            if ref_thr:
                devs_pct.append(100.0 * abs(blk['devThroughputKwh']) / ref_thr)
        if not devs_wh:
            agg[m] = {'n': 0, 'nSkipped': n_skipped,
                      'note': 'no drives produced a valid result for this estimator'}
            continue
        a = np.array(devs_wh)
        p = np.array(devs_pct) if devs_pct else None
        agg[m] = {
            'n': len(devs_wh), 'nSkipped': n_skipped,
            'maxAbsDevWh': round(float(a.max()), 2),
            'meanAbsDevWh': round(float(a.mean()), 2),
            'p95AbsDevWh': round(float(np.percentile(a, 95)), 2),
            'maxAbsDevPctThroughput': round(float(p.max()), 4) if p is not None else None,
            'meanAbsDevPctThroughput': round(float(p.mean()), 4) if p is not None else None,
            'p95AbsDevPctThroughput': round(float(np.percentile(p, 95)), 4) if p is not None else None}
    cc_devs = []
    n_cc_skipped = 0
    for r in rows:
        cc = (r.get('independentIntegrationCheck') or {}).get('coulombCrossCheck') or {}
        if 'devSocDeltaPp' in cc:
            cc_devs.append(abs(cc['devSocDeltaPp']))
        else:
            n_cc_skipped += 1
    if cc_devs:
        c = np.array(cc_devs)
        agg['coulombCrossCheck'] = {
            'n': len(cc_devs), 'nSkipped': n_cc_skipped,
            'maxAbsDevPp': round(float(c.max()), 3),
            'meanAbsDevPp': round(float(c.mean()), 3),
            'p95AbsDevPp': round(float(np.percentile(c, 95)), 3)}
    else:
        agg['coulombCrossCheck'] = {'n': 0, 'nSkipped': n_cc_skipped}
    # M220.1 data-quality transparency: identify the top absolute-Wh
    # contributors for trueTrapezoidal (the primary/ground-truth estimator
    # of the three), matching the existing top-contributors convention in
    # energy_uncertainty_mc.py's gross_mc block, so a reader sees WHERE the
    # deviation concentrates rather than only a pooled percentile.
    tt_devs = []
    for r in rows:
        tt = (r.get('independentIntegrationCheck') or {}).get('trueTrapezoidal') or {}
        if 'devThroughputKwh' in tt:
            tt_devs.append((abs(tt['devThroughputKwh']), r['file'],
                            r.get('nISamples'), r.get('nVSamples')))
    tt_devs.sort(reverse=True)
    top = [{'file': f, 'absDevWh': round(d * 1000, 1),
           'nISamples': ni, 'nVSamples': nv}
          for d, f, ni, nv in tt_devs[:5]]
    agg['dataQualityNote'] = {
        'topContributorsTrueTrapezoidal': top,
        'finding': (
            'Deviation concentrates in two distinct patterns, not one: (a) '
            'low-sample-count drives (tens of I/V samples) where linear '
            'interpolation across a real multi-minute coverage gap '
            'fabricates intermediate current/voltage values, and the '
            'per-union-interval DT_CAP_S cap does not recognize that '
            'several such fabricated sub-intervals sit inside what is '
            'actually ONE real gap -- over-crediting energy there, unlike '
            'production\'s per-original-channel gap handling; and (b) a '
            'smaller number of HIGH-sample-count drives (thousands of I/V '
            'samples, nI==nV) that still show substantial absolute '
            'deviation, indicating a genuine, non-gap-driven sensitivity '
            'of the alignment method itself (interpolation vs. nearest-'
            'match) on those particular drives -- not yet root-caused '
            'further within this milestone\'s scope.')}
    agg['method'] = (
        'M220.1 (P0.4 closure): three alternative re-integrations '
        '(true trapezoidal on linearly-interpolated native-union '
        'timestamps; midpoint/sample-and-hold rule; production frame '
        'downsampled to a uniform 1 Hz grid) plus a coulomb-counting '
        'cross-check (current-only integration -> expected SoC delta via '
        'assumed CAP_KWH and this drive\'s own mean pack voltage, vs. '
        'BMS-observed SoC delta), each run on the SAME native (I, V, SoC) '
        'series already loaded for the tolerance grid above -- genuinely '
        'independent numerical methods from _integrate() (documented '
        'elsewhere as literally the same algorithm as '
        'compute_drive_summary_v6.py, i.e. a coding-bug check, not a '
        'methodological cross-check). Wh/%% deviations are vs. the '
        'released gross_discharge/charge/throughput_kwh at the nominal '
        '1500ms tolerance; pp deviations are percentage points of SoC.')
    return agg


def _quant_sd(e):
    """Delta-method SD of gross throughput under independent per-sample ADC
    quantization noise on I and V (uniform, half-width Q_I_A/2, Q_V_V/2).

    Rewrite total signed energy as a weighted sum of per-sample power values:
    E = sum_k P_mid_k * dt_h_k = sum_i w_i * P_i, where interior sample i
    carries weight w_i = 0.5*(dt_h_i + dt_h_{i+1}) (edge samples get the
    single adjacent half-weight only) -- the standard trapezoidal weight.
    Quantization noise on DIFFERENT raw samples is independent, so
    Var(E) = sum_i w_i^2 * Var(P_i), with
    Var(P_i) = (V_i/1000)^2 * Var(I) + (I_i/1000)^2 * Var(V),
    Var(I) = Q_I_A^2/12, Var(V) = Q_V_V^2/12 (uniform quantization variance).

    This targets NET signed energy exactly; it is used here as the SD for
    GROSS throughput too (dis+chg) -- a standard, transparent approximation
    that is exact away from sign-crossings (the dominant source of gross
    throughput's quantization sensitivity is magnitude jitter on already-
    signed steps, not sign flips, given the sample-to-sample current swings
    in this corpus are almost always many multiples of Q_I_A)."""
    n = len(e)
    if n < 3:
        return 0.0
    dt_h = e['dt_h'].to_numpy()
    w = np.zeros(n)
    w[:-1] += 0.5 * dt_h[1:]
    w[1:] += 0.5 * dt_h[1:]
    varI = (Q_I_A ** 2) / 12.0
    varV = (Q_V_V ** 2) / 12.0
    Vv = e['V'].to_numpy()
    Iv = e['Id'].to_numpy()
    var_p = (Vv / 1000.0) ** 2 * varI + (Iv / 1000.0) ** 2 * varV
    var_e = float(np.sum((w ** 2) * var_p))
    return float(np.sqrt(max(var_e, 0.0)))


def _gap_diagnostics(e):
    """Total excess time beyond DT_CAP_S (silently dropped by the pipeline's
    own integration-step cap) and the corpus-standard bound on how much
    energy that could plausibly represent: excess time x this drive's own
    median |P| (a same-drive characteristic magnitude, not borrowed from
    elsewhere)."""
    if len(e) < 2 or 'gap_s' not in e.columns:
        return 0.0, 0, 0.0, 0.0
    gap_s = e['gap_s'].dropna().to_numpy()
    excess_s = float(np.clip(gap_s - DT_CAP_S, 0, None).sum())
    med_abs_p_kw = float(e['P'].abs().median()) if len(e) else 0.0
    possible_missing_kwh = med_abs_p_kw * excess_s / 3600.0
    n_capped_gaps = int((gap_s > DT_CAP_S).sum())
    return excess_s, n_capped_gaps, med_abs_p_kw, possible_missing_kwh


def _estimate_lsb(raw_dir, files, col, n_files=40, seed=7):
    """Pool distinct raw values across a random subset of files and take the
    MODE of the smallest nonzero gaps between them -- a corpus-wide ADC LSB
    estimate, robust to any single file's low sample count giving a
    misleadingly coarse single-file estimate (a 44-sample file can only ever
    show gaps as fine as its own sparse coverage allows)."""
    rng = np.random.default_rng(seed)
    pick = rng.choice(files, size=min(n_files, len(files)), replace=False)
    steps = []
    for f in pick:
        try:
            df = pd.read_csv(f'{raw_dir}/{f}', usecols=[col])
        except Exception:
            continue
        u = np.sort(df[col].dropna().unique())
        if len(u) < 2:
            continue
        d = np.diff(u)
        d = d[d > 1e-6]
        if len(d):
            steps.append(np.min(d))
    if not steps:
        return None
    # round to a plausible CAN-scaling grid (multiples of 0.01) and take the
    # most common rounded step across files -- more robust than a raw median.
    rsteps = [round(s, 2) for s in steps]
    vals, counts = np.unique(rsteps, return_counts=True)
    return float(vals[np.argmax(counts)])


def build(raw_dir, dm, tol_grid_ms=TOL_GRID_MS, offset_point_a=OFFSET_POINT_A):
    """dm: drive_master.csv already loaded (pd.DataFrame). Returns
    (rows, corpus_meta) where rows is a list of per-drive dicts and
    corpus_meta carries the pooled LSB estimates and validation summary."""
    d = dm[dm['gross_discharge_kwh'].notna() & dm['file'].notna()].copy()
    files = d['file'].tolist()

    global Q_I_A, Q_V_V
    lsb_i = _estimate_lsb(raw_dir, files, '[BMS] HV Battery Current (A)') or Q_I_A
    lsb_v = _estimate_lsb(raw_dir, files, '[BMS] HV Battery voltage (V)') or Q_V_V
    Q_I_A, Q_V_V = lsb_i, lsb_v

    rows = []
    val_dev_dis, val_dev_chg = [], []
    for _, r in d.iterrows():
        fpath = f"{raw_dir}/{r['file']}"
        try:
            raw = pd.read_csv(fpath, usecols=['time'] + list(COL_MAP.keys()),
                              low_memory=False)
        except Exception as e:
            rows.append({'file': r['file'], 'error': repr(e)})
            continue
        raw = raw.rename(columns=COL_MAP)
        t = pd.to_datetime(raw['time'], format='mixed', errors='coerce')
        I = _series(raw, t, 'I')
        I = I[I['v'].abs() < 900] if I is not None else None
        V = _series(raw, t, 'V', lo=200, hi=450)
        soc = _series(raw, t, 'soc', lo=0, hi=100)   # M220.1
        if I is None or V is None or len(I) < 3:
            rows.append({'file': r['file'], 'error': 'insufficient I/V samples'})
            continue

        grid = {}
        e_nom = None
        for tol in tol_grid_ms:
            dis, chg, thr, e = _integrate(I, V, tol)
            if dis is None:
                continue
            grid[tol] = {'discharge': round(dis, 6), 'charge': round(chg, 6),
                        'throughput': round(thr, 6)}
            if tol == V_ALIGN_TOL_MS:
                e_nom = e
        if V_ALIGN_TOL_MS not in grid or e_nom is None:
            rows.append({'file': r['file'], 'error': 'nominal tolerance failed'})
            continue

        # validation vs shipped master at nominal tolerance
        dev_dis = grid[V_ALIGN_TOL_MS]['discharge'] - float(r['gross_discharge_kwh'])
        dev_chg = grid[V_ALIGN_TOL_MS]['charge'] - float(r['gross_charge_kwh'])
        val_dev_dis.append(dev_dis); val_dev_chg.append(dev_chg)

        quant_sd = _quant_sd(e_nom)
        excess_s, n_capped, med_abs_p, poss_missing = _gap_diagnostics(e_nom)

        # offset-on-gross sensitivity: one extra re-integration at the
        # released point-estimate offset, sample-level subtraction.
        # dis_o is never None post-fix (see _integrate docstring); guard kept
        # defensively for offset_point_a==0 (undefined slope denominator).
        dis_o, chg_o, thr_o, _ = _integrate(I, V, V_ALIGN_TOL_MS,
                                            offset_a=offset_point_a)
        if dis_o is not None and offset_point_a != 0:
            slope_dis = (dis_o - grid[V_ALIGN_TOL_MS]['discharge']) / offset_point_a
            slope_chg = (chg_o - grid[V_ALIGN_TOL_MS]['charge']) / offset_point_a
            slope_thr = (thr_o - grid[V_ALIGN_TOL_MS]['throughput']) / offset_point_a
        else:
            slope_dis = slope_chg = slope_thr = 0.0

        # M220.1: alternative-estimator cross-check, reusing the same
        # native I/V/soc series already loaded above -- no second raw pass.
        alt_check = _integration_alt_estimators(
            I, V, soc, grid[V_ALIGN_TOL_MS]['discharge'],
            grid[V_ALIGN_TOL_MS]['charge'])

        rows.append({
            'file': r['file'], 'nISamples': int(len(I)), 'nVSamples': int(len(V)),
            'grid': grid,
            'quantSdThroughputKwh': round(quant_sd, 6),
            'gapExcessS': round(excess_s, 1), 'nCappedGaps': n_capped,
            'medAbsPowerKw': round(med_abs_p, 4),
            'possibleMissingKwh': round(poss_missing, 6),
            'offsetSensitivity': {
                'dDischargePerA': round(slope_dis, 6),
                'dChargePerA': round(slope_chg, 6),
                'dThroughputPerA': round(slope_thr, 6)},
            'independentIntegrationCheck': alt_check})

    dd = np.array(val_dev_dis); dc = np.array(val_dev_chg)
    corpus_meta = {
        'nDrives': len(rows), 'nValidated': len(dd),
        'lsbCurrentA': Q_I_A, 'lsbVoltageV': Q_V_V,
        'independentIntegrationCheck':
            _aggregate_independent_integration_check(rows),
        'validation': {
            'maxAbsDevDischargeKwh': round(float(np.abs(dd).max()), 6) if len(dd) else None,
            'maxAbsDevChargeKwh': round(float(np.abs(dc).max()), 6) if len(dc) else None,
            'meanAbsDevDischargeKwh': round(float(np.abs(dd).mean()), 6) if len(dd) else None,
            'note': ('Deviation of this independent re-implementation from the '
                     'shipped drive_master.csv gross_discharge/charge_kwh columns '
                     'at the nominal 1500ms tolerance. Should be ~0 (same '
                     'algorithm); confirms this module is not a redrafted '
                     'approximation.')}}
    return rows, corpus_meta


if __name__ == '__main__':
    dm = pd.read_csv('drive_master.csv')
    # P1-02: use the current released two-pass offset rather than the module
    # literal, so the per-drive offset-on-gross sensitivity tracks the corpus.
    try:
        _ou = json.load(open('summary_arrays.json'))['offsetUncertainty']
        _off = float(_ou['pointEstimateA'])
        print(f'[P1-02] sourced released offset from summary_arrays.json: {_off}')
    except Exception as _e:
        _off = OFFSET_POINT_A
        print(f'[P1-02] summary_arrays.json unavailable ({_e}); offset fallback {_off}')
    rows, meta = build('/mnt/project', dm, offset_point_a=_off)
    out = {'meta': meta, 'drives': rows}
    json.dump(out, open('energy_mc_precompute.json', 'w'), indent=1)
    print(json.dumps(meta, indent=1))
