# FROZEN REFERENCE (M383): energy_uncertainty_mc.py exactly as on main after M382 (71bd4af), kept ONLY for old/new parity tests. Do not edit; do not import from production code.
"""energy_uncertainty_mc.py  (M163, 2026-08-22)

Tier 2 of the audit-section-5 remediation: combines the per-drive uncertainty
sources precomputed once by energy_mc_precompute.py (I/V alignment tolerance
response grid, ADC-quantization SD, gap-truncation bound, offset-on-gross
sensitivity) into 95% Monte Carlo sensitivity intervals under the stated
input-tolerance distributions (not empirical confidence intervals or Bayesian
credible intervals). No raw CSVs are touched
here -- every draw operates on the cached per-drive numbers, which is what
makes B=20000 draws tractable (~seconds, not ~minutes-per-draw).

Three outputs, scoped deliberately to match what each metric's RELEASED
convention actually is (offsetUncertainty.correctionScope, M13/M24):

  1. grossThroughputMC -- gross_discharge/charge/throughput_kwh, GTC, FCE, at
     the CURRENT released convention (offset-UNCORRECTED). Propagates I/V
     alignment tolerance + ADC quantization + missing-sample/gap-truncation
     coverage. Does NOT randomly sample CAP_KWH (see offsetGrossSensitivity's
     docstring for why) or apply the offset (that would silently change the
     release convention, not just quantify its uncertainty).
  2. offsetGrossSensitivity -- a DETERMINISTIC (non-random) finding, not a
     Monte Carlo: how much gross throughput/GTC/FCE would shift if the
     current-sensor offset correction were extended from net draw to gross
     metrics too. This is the answer to offsetUncertainty.correctionScope's
     own open question ("quantifying it requires a raw re-integration pass")
     -- computed once per drive in Tier 1 by literal re-integration at the
     offset applied, not estimated. Reported as a labeled sensitivity
     alongside the released (uncorrected) values, not blended into them: the
     released convention is a project decision, this quantifies what's at
     stake in it.
  3. netDrawCorrMC -- net_draw_kwh_corr, the ONE gross-adjacent metric the
     offset actually corrects in the released pipeline. Propagates the same
     alignment/quantization/gap sources as (1) PLUS the offset's own already-
     characterized bootstrap uncertainty (offsetUncertainty.ci95A), reusing
     the master's own validated point correction magnitude
     (correctionScope.netCorrectionMagnitudeKwh) rather than re-deriving a
     parallel offset-application formula.

CAP_KWH is not treated as a continuous random variable: the corpus has
exactly one credible alternative reference point (the official 5.0 Ah
disclosure, ~1.80 kWh at this corpus's median pack voltage), not a
distribution shape to invent a prior for. GTC/FCE are reported at CAP_KWH=2.1
(current) with a deterministic rescale to 1.80 kWh alongside -- consistent
with the existing offsetUncertainty.capacitySensitivity table's own approach.

M220.1 (2026-09-04, P0.4 closure): build()'s returned dict now also carries
'independentIntegrationCheck' (passed through verbatim from
energy_mc_precompute.py's meta, computed there since only that module
touches raw I/V/SoC data), positioned alongside the pre-existing
'validation' block. The two answer different questions: 'validation' checks
that energy_mc_precompute.py's re-implementation of the released algorithm
is bug-free (same algorithm, should match); 'independentIntegrationCheck'
checks whether the released algorithm ITSELF is accurate, via three
alternative numerical methods and a structurally independent coulomb/SoC
cross-check.
"""
import json
import numpy as np

CAP_KWH_CURRENT = 2.1
CAP_KWH_ALT = 1.80          # 5.0 Ah x this corpus's V_pack_median (359.2 V)
                             # / 1000 -- the one officially-disclosure-
                             # consistent alternative; not a random draw.
TOL_GRID_MS = [500, 750, 1000, 1250, 1500, 1750, 2000]
# P1-02 (audit 2026-08-27): these three are FALLBACK DEFAULTS only. build()'s
# callers (see __main__) source the current released offset, its 95% CI, and the
# net-correction magnitude from summary_arrays.json's offsetUncertainty block, so
# a regeneration is self-currenting and these literals cannot silently go stale
# as the corpus grows (the failure the audit flagged: nominal throughput and
# offsetGrossSensitivity computed on an old corpus/offset and never refreshed).
OFFSET_POINT_A = -0.4062       # released two-pass offset (fallback default)
CI95A_DEFAULT = (-0.463, -0.329)   # offsetUncertainty.ci95A (fallback default)
NET_CORRECTION_POINT_KWH = 21.0    # correctionScope.netCorrectionMagnitudeKwh (fallback)
N_DRAWS = 20000
SEED = 20260822


def _interp_grid(grid, tol_grid_ms, key):
    """Piecewise-linear interpolation of a per-drive grid metric ('discharge'/
    'charge'/'throughput') across the tolerance grid, vectorized over a whole
    array of drawn tolerances at once."""
    xs = np.array(tol_grid_ms, dtype=float)
    ys = np.array([grid[str(t)][key] if str(t) in grid else grid[t][key]
                  for t in tol_grid_ms], dtype=float)
    return xs, ys


def data_quality_finding(total_delta_2000, top_contributors):
    """M382 (audit F03): the data-quality note is GENERATED from the current per-drive nominal energy and tolerance-widening delta. The
    earlier fixed text (two named files 'contribute literal 0.0 kWh') described a pre-M366 state and contradicted the live master."""
    top = top_contributors[:2]
    if not top or not total_delta_2000:
        return 'No drive contributes a measurable 1500->2000 ms tolerance-widening effect.'
    share = top[-1]['cumulativePctOfTotalWidening']
    parts = []
    for c in top:
        nom = c.get('nominalKwh_1500ms')
        parts.append('%s: nominal %s kWh at 1500 ms, +%s kWh (%s%%) at 2000 ms' % (
            c['file'], nom, c['deltaKwh_1500to2000ms'],
            ('%.2f' % (100 * c['deltaKwh_1500to2000ms'] / nom)) if nom else 'n/a'))
    return ('The 1500->2000 ms tolerance-widening effect (%s kWh corpus-wide) is concentrated in a few drives rather than spread evenly: '
            'the top %d contributor(s) account for %s%% of it. Per drive (current master): %s. These are tolerance sensitivities of '
            'drives that carry non-zero released energy, not zero-energy files; the cause (voltage-sample interval relative to the '
            'tolerance) is not tested here. The remaining contributors are listed below.' % (
                round(total_delta_2000, 3), len(top), share, '; '.join(parts)))


def build(precompute, rng=None, offset_point_a=OFFSET_POINT_A,
          ci95a=CI95A_DEFAULT, net_correction_kwh=NET_CORRECTION_POINT_KWH):
    """precompute: the dict loaded from energy_mc_precompute.json
    ({'meta':..., 'drives':[...]})."""
    rng = rng or np.random.default_rng(SEED)
    drives = [r for r in precompute['drives'] if 'grid' in r]
    n_drives = len(drives)

    # Stack per-drive tolerance-response curves into (n_drives, n_grid)
    # arrays for vectorized interpolation across all B draws at once.
    tol_arr = np.array(TOL_GRID_MS, dtype=float)
    dis_curve = np.array([[d['grid'][str(t)]['discharge'] for t in TOL_GRID_MS]
                          for d in drives])
    chg_curve = np.array([[d['grid'][str(t)]['charge'] for t in TOL_GRID_MS]
                          for d in drives])
    thr_curve = np.array([[d['grid'][str(t)]['throughput'] for t in TOL_GRID_MS]
                          for d in drives])
    quant_sd = np.array([d['quantSdThroughputKwh'] for d in drives])
    poss_missing = np.array([d['possibleMissingKwh'] for d in drives])
    d_thr_per_a = np.array([d['offsetSensitivity']['dThroughputPerA']
                            for d in drives])
    d_dis_per_a = np.array([d['offsetSensitivity']['dDischargePerA']
                            for d in drives])
    d_chg_per_a = np.array([d['offsetSensitivity']['dChargePerA']
                            for d in drives])

    nominal_idx = TOL_GRID_MS.index(1500)
    thr_nominal_total = float(thr_curve[:, nominal_idx].sum())
    dis_nominal_total = float(dis_curve[:, nominal_idx].sum())
    chg_nominal_total = float(chg_curve[:, nominal_idx].sum())
    net_nominal_total = dis_nominal_total - chg_nominal_total

    # ---------------- (1) grossThroughputMC ----------------
    B = N_DRAWS
    tau = rng.uniform(500, 2000, size=B)                    # ms, per-draw
    # interpolate throughput for every drive at every drawn tolerance:
    # np.interp over the per-drive curve, vectorized via apply-along style
    # loop kept O(n_drives) not O(n_drives*B) by interpolating the SUM curve
    # only where possible -- but interpolation is not linear in the sum
    # unless each drive's curve is used individually first, so we interpolate
    # per-drive-per-draw with a single vectorized call using searchsorted.
    idx = np.clip(np.searchsorted(tol_arr, tau) - 1, 0, len(tol_arr) - 2)
    x0 = tol_arr[idx]; x1 = tol_arr[idx + 1]
    frac = (tau - x0) / (x1 - x0)                             # (B,)
    # thr_curve: (n_drives, n_grid) -> gather the two bracketing columns per
    # draw, shape (n_drives, B)
    y0 = thr_curve[:, idx]; y1 = thr_curve[:, idx + 1]
    thr_interp = y0 + frac[None, :] * (y1 - y0)               # (n_drives, B)
    thr_total_tol = thr_interp.sum(axis=0)                    # (B,)

    quant_draw = rng.normal(0.0, quant_sd[:, None], size=(n_drives, B)).sum(axis=0)
    w = rng.uniform(0.0, 1.0, size=B)                         # shared per-draw
                                                               # coverage severity
    gap_draw = w * poss_missing.sum()                         # (B,)

    thr_mc = thr_total_tol + quant_draw + gap_draw
    gtc_mc = thr_mc / CAP_KWH_CURRENT
    fce_mc = thr_mc / (2 * CAP_KWH_CURRENT)

    def pct(a, ps=(2.5, 16, 50, 84, 97.5)):
        return {('p' + str(p).replace('.', '_')): round(float(np.percentile(a, p)), 4)
               for p in ps}

    # M163 data-quality transparency: identify any drive(s) disproportionately
    # driving the upper tolerance tail, so the combined interval isn't read as
    # diffuse corpus-wide alignment noise when it may be concentrated in a
    # small number of files with unusually sparse voltage polling.
    per_drive_delta_2000 = thr_curve[:, TOL_GRID_MS.index(2000)] - thr_curve[:, nominal_idx]
    total_delta_2000 = float(per_drive_delta_2000.sum())
    order = np.argsort(-per_drive_delta_2000)
    top_contributors = []
    running = 0.0
    for j in order[:5]:
        if per_drive_delta_2000[j] <= 1e-6:
            break
        running += float(per_drive_delta_2000[j])
        top_contributors.append({
            'file': drives[j]['file'],
            'nominalKwh_1500ms': round(float(thr_curve[j, nominal_idx]), 4),
            'deltaKwh_1500to2000ms': round(float(per_drive_delta_2000[j]), 4),
            'cumulativePctOfTotalWidening':
                round(100 * running / total_delta_2000, 1) if total_delta_2000 else None})

    gross_mc = {
        'nDraws': B, 'seed': SEED,
        'nominalReleasedThroughputKwh': round(thr_nominal_total, 4),
        'throughputKwh': {**pct(thr_mc),
                          'meanShiftFromNominalPct':
                              round(100 * (float(np.mean(thr_mc)) - thr_nominal_total)
                                    / thr_nominal_total, 4)},
        'gtc': {**pct(gtc_mc), 'nominal': round(thr_nominal_total / CAP_KWH_CURRENT, 3)},
        'fce': {**pct(fce_mc), 'nominal': round(thr_nominal_total / (2 * CAP_KWH_CURRENT), 3)},
        'sourceBudget': {
            # single-source-only marginal spreads (each vs the nominal point),
            # for the article's uncertainty-budget table -- run with only one
            # source active at a time, others held at their nominal/zero value.
            'ivAlignmentToleranceOnlyPct':
                round(100 * (float(np.percentile(thr_total_tol, 97.5))
                            - float(np.percentile(thr_total_tol, 2.5)))
                      / thr_nominal_total / 2, 4),
            'quantizationOnlySdPct':
                round(100 * float(np.std(quant_draw)) / thr_nominal_total, 5),
            'gapTruncationOnlyMaxPct':
                round(100 * float(poss_missing.sum()) / thr_nominal_total, 4)},
        'dataQualityNote': {
            'finding': data_quality_finding(total_delta_2000, top_contributors),
            'topContributors': top_contributors},
        'method': ('Monte Carlo over cached per-drive Tier-1 diagnostics '
                   '(energy_mc_precompute.py): I/V alignment tolerance drawn '
                   'Uniform(500,2000 ms) per draw, per-drive throughput '
                   'piecewise-linearly interpolated from a real 7-point '
                   'tolerance-grid re-integration (not extrapolated); ADC '
                   'quantization drawn per-drive Normal(0, delta-method SD); '
                   'missing-sample/gap-truncation coverage drawn as a single '
                   'per-draw severity weight in [0,1] applied to each drive\'s '
                   'own possible-missing-energy bound (excess time beyond the '
                   'pipeline\'s 5s integration-step cap, times that drive\'s own '
                   'median |power|) -- always additive, since DT_CAP_S '
                   'truncation is a one-sided conservative-low bias, never an '
                   'over-count. Offset-UNCORRECTED, matching the released '
                   'convention (offsetUncertainty.correctionScope): see '
                   'offsetGrossSensitivity for what applying it would cost.')}

    # ---------------- (2) offsetGrossSensitivity (deterministic) ----------------
    ci_lo, ci_hi = ci95a             # offsetUncertainty.ci95A (current, sourced
                                     # by __main__ from summary_arrays.json)
    offset_sens = {
        'basis': ('Literal raw re-integration at the released point-estimate '
                  'offset (sample-level subtraction from raw current before '
                  'the discharge/charge split), one extra pass per drive in '
                  'Tier 1 -- not an estimate. Answers '
                  'offsetUncertainty.correctionScope\'s own open question: '
                  '"quantifying it requires a raw re-integration pass."'),
        'dThroughputKwhPerOffsetA': round(float(d_thr_per_a.sum()), 4),
        'atPointEstimateOffsetA': offset_point_a,
        'throughputShiftKwh': round(float(d_thr_per_a.sum()) * offset_point_a, 4),
        'throughputShiftPct': round(100 * float(d_thr_per_a.sum()) * offset_point_a
                                    / thr_nominal_total, 4),
        'throughputShiftAcrossCi95Kwh': [
            round(float(d_thr_per_a.sum()) * ci_lo, 4),
            round(float(d_thr_per_a.sum()) * ci_hi, 4)],
        'dDischargeKwhPerOffsetA': round(float(d_dis_per_a.sum()), 4),
        'dChargeKwhPerOffsetA': round(float(d_chg_per_a.sum()), 4),
        'note': ('A constant current-sensor bias does NOT cancel in a |I| '
                 'integral the way it cancels in signed net draw -- shifting '
                 f'raw current by the released offset ({offset_point_a} A) '
                 'INCREASES gross throughput here, it does not leave it '
                 'unchanged. This is reported as a sensitivity alongside the '
                 'released (offset-uncorrected) values, not applied to them: '
                 'whether to extend the offset correction to gross metrics is a '
                 'convention decision, not a data question.')}

    # ---------------- (3) netDrawCorrMC ----------------
    y0n = dis_curve[:, idx] - chg_curve[:, idx]
    y1n = dis_curve[:, idx + 1] - chg_curve[:, idx + 1]
    net_interp = y0n + frac[None, :] * (y1n - y0n)
    net_total_tol = net_interp.sum(axis=0)
    # quantization/gap on NET: same magnitude budget as gross but genuinely
    # unsigned in direction for net (a capped gap could plausibly have been
    # net-discharging OR net-charging) -- drawn as a signed contribution.
    quant_draw_net = rng.normal(0.0, quant_sd[:, None], size=(n_drives, B)).sum(axis=0)
    gap_sign = rng.uniform(-1.0, 1.0, size=B)
    gap_draw_net = w * gap_sign * poss_missing.sum()
    offset_draw = rng.normal(offset_point_a, (ci_hi - ci_lo) / (2 * 1.959964), size=B)
    net_correction_point_kwh = net_correction_kwh   # correctionScope
                                       # .netCorrectionMagnitudeKwh: a MAGNITUDE
                                       # (positive), sourced by __main__ from
                                       # summary_arrays.json. The pipeline's own
                                       # formula is off_kwh = i_off*V*h (i_off<0,
                                       # off_kwh<0) and net_draw_kwh_corr =
                                       # net_draw_kwh - off_kwh, i.e. the
                                       # correction ADDS +netCorrectionMagnitudeKwh
                                       # at the released offset. off_kwh scales
                                       # linearly in the offset (V, h fixed per
                                       # drive), so the correction at any drawn
                                       # offset is this magnitude rescaled by
                                       # (offset_draw / offset_point_a) and ADDED.
    net_corr_from_offset = net_correction_point_kwh * (offset_draw / offset_point_a)
    net_mc = net_total_tol + quant_draw_net + gap_draw_net + net_corr_from_offset

    net_mc_block = {
        'nDraws': B, 'seed': SEED,
        'nominalReleasedNetDrawCorrKwh': round(net_nominal_total
                                              + net_correction_point_kwh, 3),
        'netDrawKwhCorr': pct(net_mc),
        'method': ('Same tolerance/quantization/gap draws as grossThroughputMC '
                   '(gap contribution signed, not additive-only, for net -- a '
                   'capped gap\'s true net direction is genuinely unknown) '
                   'PLUS the offset draw from its own characterized bootstrap '
                   '(offsetUncertainty: Normal approximation to ci95A '
                   f'[{ci_lo},{ci_hi}]), applied via the master\'s own validated '
                   'point correction magnitude '
                   f'(correctionScope.netCorrectionMagnitudeKwh={net_correction_point_kwh} kWh) '
                   'linearly rescaled by the drawn offset -- reusing the '
                   'released correction formula rather than re-deriving a '
                   'parallel one.')}

    return {
        'grossThroughputMC': gross_mc,
        'offsetGrossSensitivity': offset_sens,
        'netDrawCorrMC': net_mc_block,
        'capacityNote': (
            f'GTC/FCE above use CAP_KWH={CAP_KWH_CURRENT} (current, '
            f'verified:false convention). Deterministic rescale to the '
            f'officially-disclosure-consistent {CAP_KWH_ALT} kWh (5.0 Ah x '
            f'this corpus\'s median pack voltage): multiply gtc/fce by '
            f'{round(CAP_KWH_CURRENT / CAP_KWH_ALT, 4)}. Not drawn randomly: '
            f'CAP_KWH has exactly one credible alternative reference point, '
            f'not a distribution to assume a shape for.'),
        'validation': precompute['meta']['validation'],
        # M220.1 (P0.4 closure): genuinely independent methodological
        # cross-check (three alternative re-integrations + coulomb/SoC
        # cross-check), sourced from energy_mc_precompute.py's raw pass and
        # surfaced here alongside 'validation' above -- both visible side
        # by side. 'validation' confirms this module's re-implementation is
        # not a redrafted approximation of the SAME algorithm (a coding-bug
        # check); 'independentIntegrationCheck' tests the algorithm's own
        # accuracy against genuinely different numerical methods, which
        # 'validation' cannot do by construction.
        'independentIntegrationCheck': precompute['meta'].get(
            'independentIntegrationCheck'),
        'lsbEstimates': {'currentA': precompute['meta']['lsbCurrentA'],
                         'voltageV': precompute['meta']['lsbVoltageV']}}


if __name__ == '__main__':
    pre = json.load(open('energy_mc_precompute.json'))
    # P1-02: source the released offset, its 95% CI, and the net-correction
    # magnitude from the live payload so this regeneration is self-currenting.
    try:
        _S = json.load(open('summary_arrays.json'))
        _ou = _S['offsetUncertainty']
        _off = float(_ou['pointEstimateA'])
        _ci = tuple(float(x) for x in _ou['ci95A'])
        _ncorr = float(_ou['correctionScope']['netCorrectionMagnitudeKwh'])
        print(f'[P1-02] sourced from summary_arrays.json: offset={_off} '
              f'ci95A={list(_ci)} netCorrKwh={_ncorr}')
    except Exception as _e:
        _off, _ci, _ncorr = OFFSET_POINT_A, CI95A_DEFAULT, NET_CORRECTION_POINT_KWH
        print(f'[P1-02] summary_arrays.json unavailable ({_e}); using fallback '
              f'defaults offset={_off} ci95A={list(_ci)} netCorrKwh={_ncorr}')
    out = build(pre, offset_point_a=_off, ci95a=_ci, net_correction_kwh=_ncorr)
    json.dump(out, open('energy_uncertainty_mc.json', 'w'), indent=1)
    print(json.dumps({k: v for k, v in out.items()
                      if k in ('grossThroughputMC', 'offsetGrossSensitivity',
                              'netDrawCorrMC', 'capacityNote')}, indent=1)[:4000])
