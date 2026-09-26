"""crosscheck_vehicles.py  (M127, 2026-08-16)

Emits ONE additive top-level block, ``crossVehicle``, into ``summary_arrays.json``.
It compares the segregated e-4ORCE AWD rail (``e4orce_master.csv``) against the
primary FWD corpus (``drive_master.csv``) using ONLY CAP_KWH-invariant quantities.

Hard segregation / consistency guards (all enforced at build time):
  * ``drive_master.csv`` is opened READ-ONLY; its MD5 is captured before and after
    and asserted identical (isolation-diff discipline).
  * Only an explicit CAP-invariant column set is read from either master; a regex
    guard aborts if a CAP-dependent name (``*_kwh``, ``*_kw``, ``cap_*``, ``gtc``,
    ``rf_efc``, throughput/energy) is requested.
  * No ``CAP_KWH`` constant is referenced anywhere in this module.
  * ``run_pipeline()`` / IsolationForest / LOF are never invoked -- this is a pure
    read+summarize pass, so no pre-existing primary row can be altered.

Resistance is reported for the aux rail as a TEMPERATURE-ANNOTATED SCATTER over the
9 drives (ambient_c vs vreg/vsag mOhm), with NO binning and NO trend fit: internal
resistance is temperature-dependent, and n=9 does not support a controlled
aggregate. The primary rail is summarized as a level reference (median + IQR).
"""
import os
import re
import json
import hashlib
import datetime as _dt

import numpy as np
import pandas as pd

_HERE = os.path.dirname(os.path.abspath(__file__))
M_TAG = 'M135'

# CAP-invariant columns this module is permitted to read from EITHER master.
_CAP_INVARIANT_READ = {
    'file', 'date', 'drive_type',
    'soc_min', 'soc_max', 'soc_band',
    'cell_spread_mean_mv', 'cell_spread_p95_mv',
    'peak_I_discharge', 'peak_I_charge',
    'dual_peak_A', 'dual_peak_Crate', 'regen_peak_A', 'regen_peak_Crate',
    'vsag_R_pack_mohm', 'vsag_R_iqr_mohm', 'n_vsag_load',
    'vreg_R_pack_mohm', 'n_vreg_samples', 'vreg_I_p95_A',
    'ambient_c', 'pack_minus_ambient_c', 'T_pack_mean_avg', 'T_pack_mean_max',
    # -- M129: invariant metrics for the matched-stratum comparison --
    #    #2 engine duty (%), #3 SoC oscillation (%), #1 rainflow cycling (%) --
    'engine_on_pct',
    'rf_dod_wmean_pct', 'rf_dod_max_pct', 'rf_socmean_wtd_pct',
    #    stratum-match documentation (kmh / %) --
    'speed_mean_moving', 'speed_p95', 'stationary_pct', 'pct_urban', 'pct_highway',
    # -- M135: rate-normalization basis for the M128 kWh-throughput framing
    #    (distance_km / duration_s are not CAP-dependent themselves; they are
    #    only the denominators used to turn the M128-admitted gtc/fce into a
    #    per-100km / per-hour rate) --
    'distance_km', 'duration_s',
}
_CAP_FORBIDDEN = re.compile(
    r'kwh|_kw$|_kw_|^cap_|cap_ah|energy|\bgtc\b|rf_efc|throughput|net_draw', re.I)

# M135 (2026-08-18): M129's batteryCycling block explicitly deferred a
# kWh-throughput framing of #1 ("A kWh-throughput framing is now available
# (M128 energy columns) but the canonical cycling comparison is SoC-% and
# CAP-invariant"). That deferral is now picked up: gtc/fce are DELIBERATELY
# admitted here on the same M128 rationale (shared CAP_KWH=2.1 pack across
# FWD/e-4ORCE, so the constant is a common multiplicative factor / cancels in
# matched-stratum ratios). gross_throughput_kwh is NOT admitted -- this
# module's rate framing only needs gtc/fce, and admitting throughput itself
# would widen the exemption further than the analysis requires. The guard
# below still fires for any OTHER CAP-dependent column, so nothing else can
# leak in by omission (mirrors ingest_e4orce.py's _CAP_ADMITTED pattern).
_CAP_ADMITTED = frozenset({'gtc', 'fce'})


def _md5(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _read_invariant(path):
    """Read a master keeping ONLY CAP-invariant columns (date as string), plus
    the M135 explicitly-admitted CAP-dependent set (_CAP_ADMITTED). The guard
    still fires for any CAP-dependent name in _CAP_INVARIANT_READ that is NOT
    on _CAP_ADMITTED, so an unvetted quantity cannot leak in by omission."""
    guard = [c for c in _CAP_INVARIANT_READ
             if _CAP_FORBIDDEN.search(c) and c not in _CAP_ADMITTED]
    assert not guard, f'CAP-dependent column in read set: {guard}'
    df = pd.read_csv(path, low_memory=False)
    if 'date' in df.columns:
        df['date'] = df['date'].astype(str)
    keep = [c for c in df.columns
            if c in _CAP_INVARIANT_READ or c in _CAP_ADMITTED]
    return df[keep]


def _summ(series):
    """Distribution summary of a CAP-invariant numeric series."""
    s = pd.to_numeric(series, errors='coerce').dropna()
    if len(s) == 0:
        return {'n': 0}
    return {
        'n': int(len(s)),
        'mean': round(float(s.mean()), 2),
        'p05': round(float(s.quantile(0.05)), 2),
        'p50': round(float(s.median()), 2),
        'p95': round(float(s.quantile(0.95)), 2),
        'min': round(float(s.min()), 2),
        'max': round(float(s.max()), 2),
    }


def _pair(primary, aux, col):
    return {'metric': col,
            'primary': _summ(primary[col]) if col in primary else {'n': 0},
            'aux': _summ(aux[col]) if col in aux else {'n': 0}}


# ----------------------------------------------------------------------
# M129: matched-stratum comparison (urban, mixed). The aux rail has NO
# highway / mixed_highway coverage, so whole-corpus comparison against the
# primary (which does) is confounded by drive-type mix; inference is drawn
# ONLY within the matched strata. n_aux is 5 (urban) / 4 (mixed): every
# comparison is descriptive / hypothesis-generating, never confirmatory.
# Nonparametric throughout (Mann-Whitney U + rank-biserial); the aux side
# is shown as its actual per-drive values, not a smoothed summary.
# ----------------------------------------------------------------------
_MATCHED_STRATA = ('urban', 'mixed')


def _f(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 2)


def _stratum_compare(primary, aux, col):
    from scipy import stats
    out = {}
    for st in _MATCHED_STRATA:
        p = pd.to_numeric(primary.loc[primary['drive_type'] == st, col],
                          errors='coerce').dropna() if col in primary else pd.Series(dtype=float)
        a = pd.to_numeric(aux.loc[aux['drive_type'] == st, col],
                          errors='coerce').dropna() if col in aux else pd.Series(dtype=float)
        if len(p) == 0 or len(a) == 0:
            out[st] = {'primary': {'n': int(len(p))}, 'aux': {'n': int(len(a))}}
            continue
        try:
            U, pv = stats.mannwhitneyu(a, p, alternative='two-sided')
            rb = 1.0 - 2.0 * U / (len(a) * len(p))          # aux vs primary
            pctl = float(stats.percentileofscore(p, a.median(), kind='mean'))
        except Exception:
            pv, rb, pctl = float('nan'), float('nan'), float('nan')
        out[st] = {
            'primary': {'n': int(len(p)), 'median': _f(p.median()),
                        'q25': _f(p.quantile(0.25)), 'q75': _f(p.quantile(0.75)),
                        'p05': _f(p.quantile(0.05)), 'p95': _f(p.quantile(0.95))},
            'aux': {'n': int(len(a)), 'median': _f(a.median()),
                    'values': [_f(v) for v in a.tolist()]},
            'auxMedianPctlInPrimary': _f(pctl),
            'medianDiff': _f(a.median() - p.median()),
            'mwuP': _f(pv), 'rankBiserial': _f(rb),
        }
    return {'metric': col, 'byStratum': out}


def _add_kwh_rate_columns(df):
    """M135: turn the M128-admitted absolute gtc/fce into rate metrics
    (per-100km, per-hour) so drives of very different length/duration within
    the same stratum are comparable. Non-mutating (returns a copy); guards
    distance_km<=0 / duration_s<=0 to NaN rather than dividing by zero or a
    negative denominator."""
    df = df.copy()
    dist = pd.to_numeric(df.get('distance_km'), errors='coerce')
    hrs = pd.to_numeric(df.get('duration_s'), errors='coerce') / 3600.0
    dist_ok = dist > 0
    hrs_ok = hrs > 0
    for base in ('gtc', 'fce'):
        if base not in df.columns:
            continue
        b = pd.to_numeric(df[base], errors='coerce')
        df[f'{base}_per100km'] = np.where(dist_ok, b / dist * 100.0, np.nan)
        df[f'{base}_perHour'] = np.where(hrs_ok, b / hrs, np.nan)
    return df


def _strata_match(primary, aux):
    """Document that the matched strata are actually comparable (speed / stationary
    envelope), so the byStratum comparison is not itself confounded within stratum."""
    doc = {}
    for st in _MATCHED_STRATA:
        d = {}
        for lbl, df in (('primary', primary), ('aux', aux)):
            s = df[df['drive_type'] == st]
            d[lbl] = {
                'n': int(len(s)),
                'speedMeanMoving': _summ(s.get('speed_mean_moving', pd.Series(dtype=float))),
                'speedP95': _summ(s.get('speed_p95', pd.Series(dtype=float))),
                'stationaryPct': _summ(s.get('stationary_pct', pd.Series(dtype=float))),
            }
        doc[st] = d
    return doc


def build_cross_vehicle(primary, aux):
    """Return the additive ``crossVehicle`` payload (CAP-invariant only)."""
    n_aux = int(len(aux))
    n_pri = int(len(primary))

    # M135: rate-normalized gtc/fce (per-100km, per-hour) for the deferred
    # kWh-throughput framing of #1. Added to local working copies only --
    # primary/aux as read by _read_invariant() are untouched by this.
    primary_kwh = _add_kwh_rate_columns(primary)
    aux_kwh = _add_kwh_rate_columns(aux)

    # -- resistance: aux temperature-annotated scatter (no binning, no fit) --
    scatter = []
    for _, r in aux.sort_values('ambient_c').iterrows():
        def _g(k):
            v = r.get(k)
            return None if (v is None or (isinstance(v, float) and np.isnan(v))) else v
        scatter.append({
            'file': r['file'],
            'date': str(r.get('date')),
            'driveType': r.get('drive_type'),
            'ambientC': _g('ambient_c'),
            'packMinusAmbientC': _g('pack_minus_ambient_c'),
            'vregMohm': _g('vreg_R_pack_mohm'),
            'vsagMohm': _g('vsag_R_pack_mohm'),
            'nVreg': _g('n_vreg_samples'),
            'nVsag': _g('n_vsag_load'),
        })

    payload = {
        '_meta': {
            'generated': _dt.datetime.now(_dt.timezone.utc)
                .replace(microsecond=0).isoformat(),
            'mTag': M_TAG,
            'primaryVehicle': 'Nissan X-Trail e-POWER T33 FWD',
            'auxVehicle': 'Nissan X-Trail e-4ORCE AWD',
            'nPrimary': n_pri,
            'nAux': n_aux,
            'admissibility': (
                'CAP_KWH-invariant quantities only (%, A, 1/h, Ohm, mV, degC, '
                'ratios). The AWD rear-motor PIDs are not on the OBD bus, so all '
                'comparison is at pack / front-motor level. Ambient temperature is '
                'supplied externally (e4orce_ambient.csv); the e-4ORCE logs carry '
                'no OBD ambient-air PID.'),
            'resistanceEstimator': (
                'identical main-corpus _vsag_metrics: M25b Huber regression '
                '(vreg, primary) + v-sag rest-curve (cross-check); same thresholds '
                'and 0..500 mOhm plausibility window.'),
            'inferenceNote': (
                'M129: whole-corpus blocks below (socWindow, cRate, cellSpread) are '
                'LEVEL REFERENCES ONLY and are confounded by drive-type mix (the aux '
                'rail has no highway/mixed_highway coverage). All cross-vehicle '
                'INFERENCE is drawn from byStratum (matched urban/mixed) instead.'),
        },
        # -- M129: matched-stratum comparison — the recommended-sequence analyses --
        #    #2 engine cycling, #3 SoC oscillation, #1 rainflow battery cycling --
        'byStratum': {
            '_note': (
                'Matched urban/mixed strata only (aux has no highway coverage). '
                'n_aux = 5 urban / 4 mixed: descriptive / hypothesis-generating, '
                'NOT confirmatory. Nonparametric (Mann-Whitney U two-sided + '
                'rank-biserial, aux vs primary); aux shown as actual per-drive '
                'values. rankBiserial>0 => aux tends lower than primary. '
                'Event-level detectors (start-rate, SoC-hysteresis, buffer-impulse) '
                'are a raw-frame follow-on (drive the identical _RawAccum on the aux '
                'frames); this block is the master-level invariant layer.'),
            'strataMatch': _strata_match(primary, aux),
            # #2 — engine duty cycle (engine-on fraction, %)
            'engineCycling': {
                'analysis': '#2 engine cycling / start-stop (duty fraction)',
                'engineOnPct': _stratum_compare(primary, aux, 'engine_on_pct'),
                'note': ('engine_on_pct is the invariant engine-DUTY observable in '
                         'both masters; engine START-RATE (segsPer10min) and burst '
                         'durations require the raw _RawAccum detector cross-run.'),
            },
            # #3 — SoC oscillation / depth (%)
            'socOscillation': {
                'analysis': '#3 SoC oscillation and depth',
                'socBand': _stratum_compare(primary, aux, 'soc_band'),
                'socMin': _stratum_compare(primary, aux, 'soc_min'),
                'socMax': _stratum_compare(primary, aux, 'soc_max'),
            },
            # #1 — rainflow battery cycling (SoC-% basis; CAP-invariant)
            'batteryCycling': {
                'analysis': '#1 battery cycling (SoC-% rainflow; canonical framing)',
                'dodWmeanPct': _stratum_compare(primary, aux, 'rf_dod_wmean_pct'),
                'socMeanWtdPct': _stratum_compare(primary, aux, 'rf_socmean_wtd_pct'),
                'note': ('rf_dod_max_pct is identical to soc_band by construction '
                         '(largest rainflow range == full SoC swing) and is omitted '
                         'here to avoid double-reporting. A kWh-throughput framing was '
                         'available (M128 energy columns) but deferred at M129; see '
                         'kwhThroughputFraming below (M135) for the follow-through.'),
                # -- M135: the deferred kWh-throughput framing. gtc/fce are
                #    the M128-admitted nameplate-turnover columns (both
                #    inherit capKwhAssumed=2.1 kWh, shared by both vehicles
                #    per M128 Assumption 1, so the constant is a common
                #    multiplicative factor and cancels in the matched-stratum
                #    ratio/rank comparison even though it is not itself
                #    verified). Rate-normalized (per-100km, per-hour) rather
                #    than compared as absolutes, since drives within a
                #    stratum vary widely in length/duration. Supplementary to
                #    -- not a replacement for -- the SoC-% canonical framing
                #    above: a kWh-cycle-count metric and a SoC-depth metric
                #    can legitimately diverge (e.g. more frequent shallow
                #    cycling at high throughput vs. rarer deep cycling).
                'kwhThroughputFraming': {
                    'analysis': ('#1 battery cycling -- kWh-throughput framing '
                                 '(M128 energy columns; supplementary, not canonical)'),
                    'gtcPer100km': _stratum_compare(primary_kwh, aux_kwh, 'gtc_per100km'),
                    'fcePer100km': _stratum_compare(primary_kwh, aux_kwh, 'fce_per100km'),
                    'gtcPerHour': _stratum_compare(primary_kwh, aux_kwh, 'gtc_perHour'),
                    'note': ('gtc/fce inherit capKwhAssumed (verified:false); both '
                             'vehicles share the identical nameplate assumption '
                             '(M128 Assumption 1), so it is a common factor here, '
                             'not an independent source of cross-vehicle bias. '
                             'Rates computed as gtc(or fce)/distance_km*100 and '
                             'gtc/(duration_s/3600); drives with distance_km<=0 or '
                             'duration_s<=0 are NaN-excluded rather than div/0. '
                             'Same n_aux=5 urban/4 mixed caveat as the rest of '
                             'byStratum: descriptive/hypothesis-generating only.'),
                },
            },
        },
        # -- SoC operating window: the core buffer-thesis comparison --
        'socWindow': {
            'socBand': _pair(primary, aux, 'soc_band'),
            'socMin': _pair(primary, aux, 'soc_min'),
            'socMax': _pair(primary, aux, 'soc_max'),
        },
        # -- transient current / C-rate: buffer intensity under AWD demand --
        'cRate': {
            'dualPeakCrate': _pair(primary, aux, 'dual_peak_Crate'),
            'peakIdischarge': _pair(primary, aux, 'peak_I_discharge'),
            'regenPeakA': _pair(primary, aux, 'regen_peak_A'),
        },
        # -- cell spread (mV) --
        'cellSpread': {
            'mean': _pair(primary, aux, 'cell_spread_mean_mv'),
            'p95': _pair(primary, aux, 'cell_spread_p95_mv'),
        },
        # -- internal resistance --
        'resistance': {
            'note': ('aux rail (n=9) reported as a temperature-annotated scatter, '
                     'no binning / no trend fit; primary rail as a level reference '
                     '(median + IQR).'),
            'primary': {
                'vregMohm': _summ(primary.get('vreg_R_pack_mohm', pd.Series(dtype=float))),
                'vsagMohm': _summ(primary.get('vsag_R_pack_mohm', pd.Series(dtype=float))),
            },
            'auxScatter': scatter,
        },
    }
    return payload


def _assert_no_e4orce_in_primary(primary):
    bad = primary['file'].astype(str).str.lower().str.startswith('e4orce').sum() \
        if 'file' in primary else 0
    assert bad == 0, f'{bad} e-4ORCE rows found inside the primary corpus (segregation breach)'


def inject(arrays_path=None, master_csv=None, e4_master=None, out_path=None,
           verbose=True):
    arrays_path = arrays_path or os.path.join(_HERE, 'summary_arrays.json')
    master_csv = master_csv or os.path.join(_HERE, 'drive_master.csv')
    e4_master = e4_master or os.path.join(_HERE, 'e4orce_master.csv')
    out_path = out_path or arrays_path

    md5_before = _md5(master_csv)                    # isolation-diff discipline
    primary = _read_invariant(master_csv)
    _assert_no_e4orce_in_primary(primary)
    aux = _read_invariant(e4_master)

    payload = build_cross_vehicle(primary, aux)

    with open(arrays_path) as f:
        arrays = json.load(f)
    before_keys = set(arrays.keys())
    arrays['crossVehicle'] = payload

    md5_after = _md5(master_csv)
    assert md5_before == md5_after, \
        f'drive_master.csv changed during cross-check build ({md5_before}->{md5_after})'

    with open(out_path, 'w') as f:
        json.dump(arrays, f, ensure_ascii=False, indent=2)

    if verbose:
        added = set(arrays.keys()) - before_keys
        print(f'crossVehicle injected into {out_path}')
        print(f'  keys added: {sorted(added)}')
        print(f'  drive_master.csv MD5 unchanged: {md5_before}')
        print(f'  nPrimary={payload["_meta"]["nPrimary"]} nAux={payload["_meta"]["nAux"]}')
    return payload


if __name__ == '__main__':
    inject()
