#!/usr/bin/env python3
"""M458 (spec analyses/M458_spec.md Rev 1.1, audit F06 follow-up): the interval rule for the Car-OFF standby draw (Sen slope of the SoC drop of a parked gap on its duration), ONE implementation.

The point estimate (Sen slope of draw_pp on gap_h) and every point field are unchanged. The interval resamples WHOLE CLUSTERS (the calendar day of the START of the following drive, the arrival day) with replacement,
B = 4000, a fresh numpy.random.default_rng(42) per method (tools/soak_tau.boot_slopes); sensitivities: departure-day and ISO-week clusters and leave-one-arrival-day-out; the i.i.d. interval is kept as a REFERENCE
(never called day-clustered). `slope_fn` is injected (compute_summary_arrays._sen_slope). Pure functions; no I/O except the dataframe given."""
import math
import numpy as np
import pandas as pd

import soak_tau as ST

B_DEFAULT = ST.B_DEFAULT
SEED = ST.SEED
ODO_JUMP_KM = 0.5
DISAGREE_FRAC = 0.25
CAP_KWH_ASSUMED = 2.1


def gap_table(dm):
    """Consecutive-drive pairs with a positive parked gap: x = gap_h, y = SoC drop (pp), clusters, odometer step."""
    cols = ['date', 'time_start', 'time_end', 'soc_start', 'soc_end']
    dch = dm.dropna(subset=cols).copy().sort_values(['date', 'time_start']).reset_index(drop=True)
    n_dropped_drives = int(len(dm) - len(dch))                  # drives without a required SoC / time field, dropped BEFORE pairing
    ts_start = pd.to_datetime(dch['date'] + ' ' + dch['time_start'])
    ts_end = pd.to_datetime(dch['date'] + ' ' + dch['time_end'])
    gap_h = (ts_start.iloc[1:].values - ts_end.iloc[:-1].values) / np.timedelta64(1, 'h')
    y_all = dch['soc_end'].iloc[:-1].values - dch['soc_start'].iloc[1:].values
    m = gap_h > 0
    arr = ts_start.iloc[1:].dt.strftime('%Y-%m-%d').values
    dep = ts_end.iloc[:-1].dt.strftime('%Y-%m-%d').values
    wk = ts_start.iloc[1:].dt.strftime('%G-W%V').values
    odo = None
    if 'odo_start' in dch and 'odo_end' in dch:
        odo = dch['odo_start'].iloc[1:].values.astype(float) - dch['odo_end'].iloc[:-1].values.astype(float)
    return {'x': gap_h[m], 'y': y_all[m], 'arrival': arr[m], 'departure': dep[m], 'week': wk[m], 'odoStep': None if odo is None else odo[m], 'nPairsTotal': int(len(gap_h)), 'nPairsDropped': int((~m).sum()), 'nDrivesDroppedMissingSoc': n_dropped_drives}


def _interval(draws, cap_wh):
    d = np.asarray(draws, float)
    fin = np.isfinite(d)
    f = d[fin]
    lo, hi = np.percentile(f, [2.5, 97.5], method='linear')
    w = f / 100.0 * cap_wh
    return {'slopeCI': [float(lo), float(hi)], 'wattsCI': [float(lo) / 100.0 * cap_wh, float(hi) / 100.0 * cap_wh], 'pPositive': float((w > 0).mean()), 'nUndefined': int((~fin).sum())}


def method_block(x, y, cluster, slope_fn, cap_wh, b=B_DEFAULT, seed=SEED):
    draws = ST.boot_slopes(x, y, cluster, slope_fn, b=b, seed=seed)
    out = _interval(draws, cap_wh)
    out['nClusters'] = None if cluster is None else int(len(np.unique(cluster)))
    out['kishClusters'] = ST.kish_clusters(cluster)
    return out


def disagreement(primary, sens):
    """Pre-declared rule (Rev 1.1): a sensitivity bound differs from the primary bound by more than 25 % of the primary width, or the zero-containment of the interval differs."""
    lo, hi = primary['wattsCI']
    width = hi - lo
    contains0 = lo <= 0 <= hi
    reasons = []
    for name, s in sens.items():
        slo, shi = s['wattsCI']
        if width > 0 and (abs(slo - lo) > DISAGREE_FRAC * width or abs(shi - hi) > DISAGREE_FRAC * width):
            reasons.append('%s: a bound differs from the primary by more than %d %% of its width' % (name, int(100 * DISAGREE_FRAC)))
        if (slo <= 0 <= shi) != contains0:
            reasons.append('%s: disagrees with the primary on whether the interval contains 0' % name)
    return {'flag': bool(reasons), 'reasons': reasons, 'rule': 'a sensitivity bound differs from the primary by more than 25 % of the primary width, or the interval containment of 0 differs'}


def leave_one_day_out(x, y, cluster, slope_fn, cap_wh):
    days = np.unique(cluster)
    w = []
    for d in days:
        keep = cluster != d
        w.append(slope_fn(x[keep], y[keep]) / 100.0 * cap_wh)
    w = np.asarray(w)
    return {'nDays': int(len(days)), 'wattsMin': round(float(w.min()), 2), 'wattsMax': round(float(w.max()), 2), 'dayAtMin': str(days[int(w.argmin())]), 'dayAtMax': str(days[int(w.argmax())])}


def standby_block(dm, slope_fn, cap_kwh=CAP_KWH_ASSUMED, n_boot=B_DEFAULT):
    t = gap_table(dm)
    x, y = t['x'], t['y']
    n = len(x)
    cap_wh = cap_kwh * 1000.0
    slope = slope_fn(x, y)
    watts = slope / 100.0 * cap_wh
    jump_pp = float(np.median(y - slope * x))
    prim = method_block(x, y, t['arrival'], slope_fn, cap_wh, n_boot)
    iid = method_block(x, y, None, slope_fn, cap_wh, n_boot)
    sens = {'departureDay': method_block(x, y, t['departure'], slope_fn, cap_wh, n_boot), 'isoWeek': method_block(x, y, t['week'], slope_fn, cap_wh, n_boot)}
    r2 = lambda v: round(float(v), 2)
    r4 = lambda v: round(float(v), 4)
    lo, hi = prim['wattsCI']
    odo_jump = None if t['odoStep'] is None else int(np.nansum(np.abs(t['odoStep']) > ODO_JUMP_KM))
    return {
        'n_gaps': int(n), 'watts': r2(watts), 'ci95_watts': [r2(lo), r2(hi)], 'p_draw_gt0': round(prim['pPositive'], 3),
        'kwh_per_day': r4(watts * 24 / 1000), 'ci95_kwh_per_day': [r4(lo * 24 / 1000), r4(hi * 24 / 1000)],
        'jump_pp_per_keycycle': r2(jump_pp), 'corr_gap_vs_draw': round(float(np.corrcoef(x, y)[0, 1]), 3),
        'estimator': 'sen_slope', 'n_boot': int(n_boot),
        'slope_pp_per_h': round(float(slope), 5), 'ci95_slope_pp_per_h': [round(prim['slopeCI'][0], 5), round(prim['slopeCI'][1], 5)],
        'ciMethod': 'whole-cluster percentile bootstrap, cluster = calendar day of the start of the following drive (arrival day), B=%d, default_rng(42), percentile method linear on the finite draws (spec M458 Rev 1.1)' % n_boot,
        'nClusters': prim['nClusters'], 'kishClusters': round(prim['kishClusters'], 2), 'nUndefinedDraws': prim['nUndefined'],
        'ci95WattsIid': [r2(iid['wattsCI'][0]), r2(iid['wattsCI'][1])], 'ci95KwhPerDayIid': [r4(iid['wattsCI'][0] * 24 / 1000), r4(iid['wattsCI'][1] * 24 / 1000)], 'pDrawGt0Iid': round(iid['pPositive'], 3),
        'pairCountNote': 'nPairsDropped counts pairs with a non-positive gap AFTER the drives with a missing SoC or time field (nDrivesDroppedMissingSoc) were dropped before pairing',
        'ciIidNote': 'reference only: the gaps are resampled one by one, which assumes independent gaps; it is not a day-clustered interval',
        'sensitivities': {'departureDay': {'nClusters': sens['departureDay']['nClusters'], 'ci95Watts': [r2(v) for v in sens['departureDay']['wattsCI']], 'pPositive': round(sens['departureDay']['pPositive'], 3)},
                          'isoWeek': {'nClusters': sens['isoWeek']['nClusters'], 'ci95Watts': [r2(v) for v in sens['isoWeek']['wattsCI']], 'pPositive': round(sens['isoWeek']['pPositive'], 3)},
                          'leaveOneArrivalDay': leave_one_day_out(x, y, t['arrival'], slope_fn, cap_wh)},
        'methodDisagreement': disagreement(prim, sens),
        'nPairsTotal': t['nPairsTotal'], 'nPairsDropped': t['nPairsDropped'], 'nDrivesDroppedMissingSoc': t['nDrivesDroppedMissingSoc'], 'gapsSpanningMidnight': int((t['arrival'] != t['departure']).sum()), 'gapsWithOdoJump': odo_jump,
        'capacityAssumption': 'watts and kWh per day use the assumed capacity CAP_KWH = %.1f kWh (verified: false); the primary quantity is the SoC drift rate in pp per hour' % cap_kwh,
        'limits': ['pairs assume no unlogged drive inside a gap (gapsWithOdoJump counts gaps whose absolute odometer step exceeds %.1f km, a backwards step included; reported, not corrected)' % ODO_JUMP_KM,
                   'drives with a missing SoC are dropped before pairing, so one pair spans a dropped drive and counts its driving time as parked time; pairing first and dropping the pair gives 574 gaps, 2.20 W [1.45, 3.10] (blind-audit sensitivity)',
                   'gap hours come from naive local timestamps; daylight-saving shifts of 1 h are not corrected',
                   'a few long gaps drive the slope (see leaveOneArrivalDay)',
                   'cross-day dependence (shared drives, multi-day re-anchoring regimes) may leave the arrival-day interval too narrow',
                   'weakly identified from the SoC ledger alone (re-anchoring jump noise floor); the attribution of the drift (BMS, telematics, ledger) is not identified'],
    }
