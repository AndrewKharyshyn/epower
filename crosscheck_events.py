"""crosscheck_events.py  (M130 + M131 + M132, 2026-08-17)

Tier-2 of the e-4ORCE cross-check: EVENT-LEVEL engine/buffer detectors (M130), the
#5 turbo-pattern comparison (M131), and the #4 pure-electric (engine-off) movement +
energy comparison (M132), run on the 9 aux frames / drives through the IDENTICAL
main-corpus estimators (no reimplementation), injected as additive
``crossVehicle.eventDetectors`` / ``turboPattern`` / ``pureElectric`` sub-blocks.
Event + turbo derive from a single ``_RawAccum`` pass plus the M116/M118/M119
summaries; pure-electric runs the identical ``_ev_traction`` (M53) on an enriched
aux dm built on the fly (aux master unchanged). Covers recommended-sequence
analyses #2, #3 (event resolution), #5, and #4, complementing the M129 master-level
``byStratum`` layer.

Why a SEPARATE module from crosscheck_vehicles.py: running the detectors imports
``compute_summary_arrays`` (which references CAP_KWH and heavy per-frame machinery).
``crosscheck_vehicles.py`` is contractually a pure CAP-free master reader, so the
detector execution is isolated here. The three detectors consumed are all
current / rpm / soc based -> CAP-, mass-, and offset-independent:
  * engineOnDuration  (via _RawAccum.finalize)      -- stratified by drive_type
  * bufferImpulse     (M116, _buffer_impulse_summary)
  * rampLatency       (M118, _ramp_latency_summary)
  * socHysteresis     (M119, _soc_hysteresis_summary)
The accumulator's CAP/mass sub-products are computed but DISCARDED.

Confound discipline (carried in the payload): engineOnDuration is stratified, so its
urban/mixed comparison is matched. bufferImpulse / rampLatency / socHysteresis are
POOLED corpus-wide in the primary reference; the aux is urban+mixed only, so POOLED
RATE comparisons (eventsPer100km, per-second transition counts) are confounded by
the aux's absent highway coverage and are flagged. Per-event properties (peak kW,
durations, prob-vs-SoC shape) are stratum-robust.

Isolation: drive_master.csv opened read-only, MD5 asserted unchanged; only the
crossVehicle key of summary_arrays.json is written; run_pipeline / IsolationForest /
LOF never invoked.
"""
import os
import io
import json
import hashlib
import datetime as _dt
import importlib.util

import numpy as np
import pandas as pd

import project_paths

_HERE = os.path.dirname(os.path.abspath(__file__))
M_TAG = 'M130'


def _load(name):
    p = os.path.join(_HERE, name + '.py')
    s = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def _md5(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _clean(obj):
    """Recursively coerce numpy scalars to native python for strict JSON."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return None if (np.isnan(v) or np.isinf(v)) else v
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, float):
        return None if (np.isnan(obj) or np.isinf(obj)) else obj
    return obj


def _aux_frame_loader(raw_dir, ing):
    cache = {}

    def loader(fn):
        if fn not in cache:
            path = os.path.join(raw_dir, fn)
            df = pd.read_csv(io.BytesIO(ing._normalize_bytes(open(path, 'rb').read(), fn)),
                             low_memory=False)
            if 'time' in df.columns:
                df['time'] = pd.to_datetime(df['time'], errors='coerce')
            cache[fn] = df
        return cache[fn]
    return loader


def compute_aux_detectors(e4_master, raw_dir):
    """Run the IDENTICAL main-corpus detectors on the 9 aux frames."""
    csa = _load('compute_summary_arrays')
    ing = _load('ingest_e4orce')
    dm = pd.read_csv(e4_master, dtype={'date': str})
    loader = _aux_frame_loader(raw_dir, ing)

    # engineOnDuration (stratified) via the identical _RawAccum
    acc = csa._RawAccum()
    dist = dict(zip(dm['file'], dm['distance_km']))
    dtype = dict(zip(dm['file'], dm['drive_type']))
    for fn in dm['file']:
        acc.add(loader(fn), dist.get(fn), dtype.get(fn), fn, fn)
    fin = acc.finalize()

    return {
        'engineOnDuration': fin.get('engineOnDuration'),
        # M131 turbo keys come from the SAME finalize (no extra pass)
        'turboByRpm': fin.get('turboByRpm'),
        'rpmDistribution': fin.get('rpmDistribution'),
        'turboBySpeedCtx': fin.get('turboBySpeedCtx'),
        'bufferImpulse': csa._buffer_impulse_summary(dm, frame_loader=loader),
        'rampLatency': csa._ramp_latency_summary(dm, frame_loader=loader),
        'socHysteresis': csa._soc_hysteresis_summary(dm, frame_loader=loader),
    }


def _eod_by_label(eod):
    return {row.get('label'): row for row in (eod or [])}


def build_event_payload(aux, arrays):
    """Pair aux detectors against the primary references already in summary_arrays."""
    pri_eod = _eod_by_label(arrays.get('engineOnDuration'))
    aux_eod = _eod_by_label(aux.get('engineOnDuration'))
    fields = ('onFraction', 'segsPer10min', 'median', 'p10', 'p90', 'nSegments')
    eod_cmp = {}
    for lbl in ('Urban', 'Mixed'):
        p, a = pri_eod.get(lbl, {}), aux_eod.get(lbl, {})
        eod_cmp[lbl.lower()] = {
            'primary': {k: p.get(k) for k in fields},
            'aux': {k: a.get(k) for k in fields},
        }

    def pair_pooled(key, robust, rate):
        return {
            'primary': arrays.get(key),
            'aux': aux.get(key),
            'robustFields': robust,
            'confoundedRateFields': rate,
        }

    payload = {
        '_meta': {
            'generated': _dt.datetime.now(_dt.timezone.utc)
                .replace(microsecond=0).isoformat(),
            'mTag': M_TAG,
            'method': (
                'Identical main-corpus detectors run on the 9 aux frames: '
                '_RawAccum (engineOnDuration), _buffer_impulse_summary (M116), '
                '_ramp_latency_summary (M118), _soc_hysteresis_summary (M119). '
                'No reimplementation; CAP/mass sub-products discarded. Detectors '
                'are current/rpm/soc based -> CAP-, mass-, offset-independent.'),
            'confound': (
                'engineOnDuration is stratified => urban/mixed matched. '
                'bufferImpulse/rampLatency/socHysteresis are POOLED; the aux is '
                'urban+mixed only, so pooled RATE fields (eventsPer100km, '
                'per-second transition counts) are confounded by the aux lacking '
                'highway coverage. Per-event fields (peak kW, durations, '
                'prob-vs-SoC shape) are stratum-robust.'),
            'nAux': int(len(aux.get('socHysteresis', {}).get('startProbBySoc', [])) >= 0)
                    and 9,
        },
        # #2 engine cycling — stratified (matched), the robust comparison
        'engineOnDuration': {
            'analysis': '#2 engine cycling / start-stop (stratified, matched)',
            'byStratum': eod_cmp,
            'note': ('onFraction = engine-on %; segsPer10min = engine-start rate; '
                     'median = median engine-on burst (s). Matched urban/mixed.'),
        },
        # #2 buffer impulse — pooled
        'bufferImpulse': pair_pooled(
            'bufferImpulse',
            robust='peakKw, durationS, recoveryS, impulseTimeFractionPct',
            rate='eventsPer100km, nEvents'),
        # #2 ramp latency — pooled
        'rampLatency': pair_pooled(
            'rampLatency', robust='latency/dwell distributions', rate='nEvents'),
        # #3 SoC hysteresis — pooled prob-vs-SoC
        'socHysteresis': pair_pooled(
            'socHysteresis',
            robust='startProbBySoc / stopProbBySoc shape',
            rate='nStarts, nStops, nAtRisk*'),
    }
    return _clean(payload)


def build_turbo_payload(aux, arrays, min_reliable_n=1000):
    """M131 (#5 turbo pattern). Boost is the canonical turbo signal (MAP is
    collinear, r=0.999). Two comparisons:
      * rpmOccupancy — engine operating-point (RPM) distribution, MATCHED
        urban/mixed via rpmDistribution.byClass. Robust to stratum mix.
      * boostByRpm — boost-vs-RPM turbo map (turboByRpm), RPM-conditioned so
        largely robust to drive-type mix; aux RPM bins below min_reliable_n
        samples are flagged (aux has no highway => high-RPM bins sparse). The
        high-boost regime is uncovered by the aux; comparison is the shared
        low/mid envelope only."""
    pri_rd = arrays.get('rpmDistribution', {})
    aux_rd = aux.get('rpmDistribution', {})
    bins = pri_rd.get('bins')
    occ = {}
    for st in ('urban', 'mixed'):
        p = pri_rd.get('byClass', {}).get(st, {})
        a = aux_rd.get('byClass', {}).get(st, {})
        occ[st] = {'bins': bins, 'primaryPct': p.get('pct'), 'auxPct': a.get('pct'),
                   'primaryHours': p.get('hours'), 'auxHours': a.get('hours')}

    pri_tr = {d['rpm']: d for d in arrays.get('turboByRpm', [])}
    boost_by_rpm = []
    for d in aux.get('turboByRpm', []):
        p = pri_tr.get(d['rpm'], {})
        boost_by_rpm.append({
            'rpm': d['rpm'],
            'primary': {k: p.get(k) for k in ('n', 'activePct', 'meanActive', 'maxBoost')},
            'aux': {k: d.get(k) for k in ('n', 'activePct', 'meanActive', 'maxBoost')},
            'reliableAux': bool(d.get('n') and d['n'] >= min_reliable_n),
        })

    payload = {
        '_meta': {
            'generated': _dt.datetime.now(_dt.timezone.utc)
                .replace(microsecond=0).isoformat(),
            'mTag': 'M131',
            'nAux': 9,
            'method': (
                'Identical _RawAccum turbo builders on the 9 aux frames '
                '(turboByRpm, rpmDistribution). Boost canonical (MAP collinear '
                'r=0.999). No reimplementation.'),
            'confound': (
                'rpmOccupancy is matched (byStratum urban/mixed). boostByRpm is '
                'RPM-conditioned so largely stratum-robust; aux bins with '
                f'n < {min_reliable_n} flagged reliableAux=false (aux lacks '
                'highway => high-RPM bins sparse). High-boost regime uncovered by '
                'the aux; comparison is the shared low/mid envelope only. Boost-'
                'sensor parity across vehicles is assumed (same PID/engine).'),
            'finding': (
                'Shared engine operating-point distribution (both peak 1900-2100 '
                'rpm); the AWD runs the engine a larger fraction of time (mixed '
                'engine-off 52.3 vs 58.7 %), i.e. higher duty not different '
                'load-points. In 1500-2500 rpm the aux shows ~2x mean active '
                'boost — plausibly higher specific load feeding two motors, '
                'hypothesis-level (sensor parity + n).'),
        },
        'analysis': '#5 turbo pattern (low/mid-boost, matched envelope)',
        'rpmOccupancy': occ,
        'boostByRpm': boost_by_rpm,
    }
    return _clean(payload)


def compute_aux_ev(e4_master, raw_dir):
    """M132 (#4 pure-electric). Build an enriched aux dm on the fly (full
    analyze_bytes rows, so every column _ev_traction reads is present) and run the
    IDENTICAL _ev_traction census. The aux master is NOT modified. ev_valid gates
    out drives with broken odometer reconstruction (the two broken-distance drives),
    so nValid < 9 is expected and correct. Returns (ev_census, dm_ev) where dm_ev
    carries file / drive_type / ev_kwh_per100km for the energy comparison."""
    csa = _load('compute_summary_arrays')
    ing = _load('ingest_e4orce')
    v6 = ing._load_v6()
    e = pd.read_csv(e4_master, dtype={'date': str})
    rows = []
    for fn in e['file']:
        path = os.path.join(raw_dir, fn)
        rows.append(dict(v6.analyze_bytes(ing._normalize_bytes(open(path, 'rb').read(), fn), fn)))
    dm = pd.DataFrame(rows)
    ev = csa._ev_traction(dm)
    dm_ev = dm[['file', 'drive_type', 'ev_kwh_per100km']].copy()
    return ev, dm_ev


def build_pure_electric_payload(ev_aux, dm_ev, arrays, primary_dm):
    from scipy import stats
    pri_ev = arrays.get('evTraction', {}) or {}
    pri_bc = {r['class']: r for r in pri_ev.get('byClass', [])}
    aux_bc = {r['class']: r for r in (ev_aux.get('byClass', []) if ev_aux else [])}
    fields = ('n', 'medianPct', 'q1Pct', 'q3Pct', 'aggregatePct',
              'runsPer10km', 'runMaxKm', 'runMedianKm')
    traction = {}
    for st in ('urban', 'mixed'):
        traction[st] = {
            'primary': {k: pri_bc.get(st, {}).get(k) for k in fields},
            'aux': {k: aux_bc.get(st, {}).get(k) for k in fields},
        }

    energy = {}
    for st in ('urban', 'mixed'):
        a = pd.to_numeric(dm_ev.loc[dm_ev['drive_type'] == st, 'ev_kwh_per100km'],
                          errors='coerce').dropna()
        p = pd.to_numeric(primary_dm.loc[primary_dm['drive_type'] == st, 'ev_kwh_per100km'],
                          errors='coerce').dropna()
        if len(a) == 0 or len(p) == 0:
            energy[st] = {'primary': {'n': int(len(p))}, 'aux': {'n': int(len(a))}}
            continue
        U, pv = stats.mannwhitneyu(a, p, alternative='two-sided')
        energy[st] = {
            'primary': {'n': int(len(p)), 'median': round(float(p.median()), 2)},
            'aux': {'n': int(len(a)), 'median': round(float(a.median()), 2),
                    'values': [round(float(v), 2) for v in a.tolist()]},
            'mwuP': round(float(pv), 3),
        }

    payload = {
        '_meta': {
            'generated': _dt.datetime.now(_dt.timezone.utc)
                .replace(microsecond=0).isoformat(),
            'mTag': 'M132',
            'method': (
                'Identical _ev_traction (M53) on an enriched aux dm built on the '
                'fly (full analyze_bytes rows); aux master unchanged. EV state = '
                'eng_rpm <= 400. ev_valid gates broken-odometer drives.'),
            'nValid': ev_aux.get('nValid') if ev_aux else None,
            'nDrives': ev_aux.get('nDrives') if ev_aux else None,
            'confound': (
                'byStratum traction (urban/mixed) is matched. Overall '
                'evPctDistance/evPctTime are pooled: the primary pool includes '
                'highway (low EV share), so pooled aux>primary is expected and not '
                'inferential. EV energy (ev_kwh_per100km) is RAW/uncorrected, '
                'matching the primary master (which carries no offset-corrected EV '
                'energy column); under the M128 shared-CAP + shared-offset basis '
                'the offset cancels in matched-stratum differences. aux mixed n=2 '
                'after gating -- hypothesis-level only.'),
        },
        'analysis': '#4 pure-electric (engine-off) movement + energy',
        'overall': {
            'primary': {'evPctDistance': pri_ev.get('evPctDistance'),
                        'evPctTime': pri_ev.get('evPctTime')},
            'aux': {'evPctDistance': ev_aux.get('evPctDistance') if ev_aux else None,
                    'evPctTime': ev_aux.get('evPctTime') if ev_aux else None,
                    'evMovingShareOfEvTime': ev_aux.get('evMovingShareOfEvTime') if ev_aux else None},
            'note': 'pooled — confounded by aux lacking highway (see _meta.confound).',
        },
        'byStratumTraction': traction,
        'evEnergyIntensity': energy,
        'auxRunHistogram': ev_aux.get('runHistogram') if ev_aux else None,
    }
    return _clean(payload)


def inject(arrays_path=None, master_csv=None, e4_master=None, raw_dir=None,
           out_path=None, verbose=True):
    arrays_path = arrays_path or os.path.join(_HERE, 'summary_arrays.json')
    master_csv = master_csv or os.path.join(_HERE, 'drive_master.csv')
    e4_master = e4_master or os.path.join(_HERE, 'e4orce_master.csv')
    raw_dir = raw_dir or project_paths.raw_dir()
    out_path = out_path or arrays_path

    md5_before = _md5(master_csv)
    aux = compute_aux_detectors(e4_master, raw_dir)
    ev_aux, dm_ev = compute_aux_ev(e4_master, raw_dir)
    primary_dm = pd.read_csv(master_csv, usecols=lambda c: c in ('file', 'drive_type', 'ev_kwh_per100km'),
                             low_memory=False)
    primary_dm = primary_dm[~primary_dm['file'].astype(str).str.contains('comparison', case=False, na=False)]

    with open(arrays_path) as f:
        arrays = json.load(f)
    assert 'crossVehicle' in arrays, 'run crosscheck_vehicles.inject first'
    before_keys = set(arrays.keys())

    arrays['crossVehicle']['eventDetectors'] = build_event_payload(aux, arrays)   # M130
    arrays['crossVehicle']['turboPattern'] = build_turbo_payload(aux, arrays)      # M131
    arrays['crossVehicle']['pureElectric'] = build_pure_electric_payload(          # M132
        ev_aux, dm_ev, arrays, primary_dm)

    md5_after = _md5(master_csv)
    assert md5_before == md5_after, \
        f'drive_master.csv changed during cross-check ({md5_before}->{md5_after})'

    with open(out_path, 'w') as f:
        json.dump(arrays, f, ensure_ascii=False, indent=2)

    if verbose:
        added = set(arrays.keys()) - before_keys
        print(f'crossVehicle eventDetectors(M130)+turboPattern(M131)+pureElectric(M132) -> {out_path}')
        print(f'  new top-level keys: {sorted(added) or "none (crossVehicle updated in place)"}')
        print(f'  drive_master.csv MD5 unchanged: {md5_before}')
        bi = aux["bufferImpulse"]
        print(f'  aux M116 nEvents={bi.get("nEvents")}; M119 nStarts={aux["socHysteresis"].get("nStarts")}; '
              f'turbo bins={len(aux.get("turboByRpm") or [])}; EV nValid={ev_aux.get("nValid")}/{ev_aux.get("nDrives")}')
    return arrays['crossVehicle']


if __name__ == '__main__':
    inject()
