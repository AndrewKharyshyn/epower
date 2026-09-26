#!/usr/bin/env python3
"""
sensitivity_gtr.py -- rebuild the §4b Generator->Traction one-at-a-time
sensitivity table (generatorTractionRecon.sensitivity) at the CORRECTED
M265 battery-current sign.

Why this exists
---------------
The original generating code for `sensitivity` was NOT preserved (see
`generatorTractionRecon._provenance`): the shipped table was carried forward
from a lost `sensitivity.json` at the M246 fuel-subset basis AND under the
pre-M265 sign convention. Its BASE (central) case read f_gen=0.693 /
trac100=20.463 -- inconsistent with the M265-corrected corpus headline
(f_gen=0.488, trac100=18.23) rendered elsewhere in the very same section.
This script recomputes every axis from raw telemetry through the *current*
recon_engine (which carries the M265 sign fix) and the canonical
ratio-of-sums aggregation, so BASE reproduces the corrected headline exactly.

Method (identical to the headline pipeline, one constant perturbed per axis)
---------------------------------------------------------------------------
  * Drive set: the 184 fuel-instrumented drives fuel_recon.py --all selects,
    less the documented exclusions (distance<=0, <10 fuel-flow samples) ->
    181 rows, of which 180 are "clean" (f_gen not NaN) -- the exact set behind
    fuel_recon_master.csv.
  * Per drive: recon_engine.load_drive (M265 sign) -> precompute -> the
    per-100km reconstruction. central_estimate_v2 is anchored to the master's
    gross discharge/charge energies exactly as fuel_recon.py does.
  * Aggregate: distance-weighted mean for gen100/trac100/etaBus; ratio-of-sums
    for f_gen (sum gen_to_traction*dist / sum traction_gross*dist) -- verbatim
    the wire_gtr_seasonal.aggregate() convention.
  * Each axis mutates exactly ONE model constant (or the BSFC scenario scalar),
    re-runs precompute+central for every drive, and re-aggregates. All others
    stay at central. precompute is re-run every axis so the OPT-band axis
    re-classifies regimes correctly.

BASE-reproduction assertion gates the whole run: if BASE != the shipped
corrected corpus (15.75 / 18.23 / 0.488 / 0.331) the script aborts and writes
nothing. Reproducibility != correctness (M265) -- but a BASE that fails to
reproduce the headline is definitely wrong.

Output: sensitivity_gtr_out.json  (a list[10] of {axis,gen100,trac100,fgen,etaBus}).
Splicing into summary_arrays.json is done separately, under an isolation diff.
"""
import os, json, time, copy
import numpy as np, pandas as pd
import recon_engine as RE, model_constants as MC, fuel_recon as FR

BASE = RE.BASE
SHIPPED = dict(gen100=15.75, trac100=18.23, fgen=0.488, etaBus=0.331)  # M265-corrected corpus

# ---- drive set + per-drive cache (load once) ----------------------------------
def build_cache():
    dm = pd.read_csv(BASE + 'drive_master.csv')
    master = {r['file']: r for _, r in dm.iterrows()}
    targets = [f for f in dm['file'] if os.path.exists(BASE + f) and FR._has_fuel(BASE + f)]
    cache = []
    t0 = time.time()
    for f in targets:
        mrow = master[f]
        off = float(mrow.get('I_offset_A_applied', 0.0) or 0.0)
        g = RE.load_drive(f, off)
        if g is None:
            continue
        dist = float(mrow['distance_km'])
        if not (dist > 0):
            continue
        # slim arrays precompute needs, plus mrow scalars central_estimate_v2 needs
        cache.append(dict(
            file=f, drive_type=mrow['drive_type'], dist=dist,
            cols={k: g[k].values for k in
                  ['on', 'flow', 'dt', 'rpm', 'coolant', 'since_start',
                   'boost', 'oil', 'Pbatt', 'soc', 'dist', 'used']},
            mrow={k: mrow.get(k, np.nan) for k in
                  ['gross_discharge_kwh', 'gross_charge_kwh',
                   'charge_pure_regen_kwh', 'charge_eng_only_kwh', 'charge_dual_kwh']},
        ))
    print('cache: %d drives loaded in %.1fs' % (len(cache), time.time() - t0))
    return cache

def _slim_g(entry):
    """Rebuild the minimal DataFrame precompute()/central_estimate_v2() consume."""
    return pd.DataFrame(entry['cols'])

def _wavg(frame, col):
    """Distance-weighted mean, pandas skipna semantics -- verbatim
    wire_gtr_seasonal.wavg (numerator skips NaN, denominator does not)."""
    w = frame['distance_km']
    return (frame[col] * w).sum() / w.sum()

def run_axis(cache, scen='central'):
    """One aggregate pass over all cached drives at the current MC state + scen.
    Builds a per-drive frame and applies the EXACT aggregate() convention so the
    method is byte-identical to the shipped headline pipeline."""
    recs = []
    for e in cache:
        g = _slim_g(e)
        pc = RE.precompute(g)
        ce = RE.central_estimate_v2(pc, e['mrow'], scen)
        if ce is None:
            continue
        dist = e['dist']
        recs.append(dict(
            distance_km=dist,
            generator_kWh_100=ce['E_gen'] / dist * 100.0,
            traction_gross_kWh_100=ce['E_trac_gross'] / dist * 100.0,
            gen_to_traction_kWh_100=ce['E_gen_to_trac'] / dist * 100.0,
            eta_fuel_bus=ce['eta_fuel_bus'],
            f_gen=ce['f_gen'],
        ))
    fr = pd.DataFrame(recs)
    clean = fr[fr['f_gen'].notna()].copy()
    s_g2t = (clean['gen_to_traction_kWh_100'] * clean['distance_km']).sum()
    s_tg = (clean['traction_gross_kWh_100'] * clean['distance_km']).sum()
    return dict(
        gen100=round(_wavg(clean, 'generator_kWh_100'), 2),
        trac100=round(_wavg(clean, 'traction_gross_kWh_100'), 2),
        fgen=round(s_g2t / s_tg, 3),
        etaBus=round(_wavg(clean, 'eta_fuel_bus'), 3),
        nClean=len(clean),
    )

# axis label -> (mutation fn, scen). Each mutation returns a restore fn.
def _set(attr, val):
    old = getattr(MC, attr)
    def restore(o=old): setattr(MC, attr, o)
    setattr(MC, attr, val); return restore

def _set_tuple0(attr, val):
    old = getattr(MC, attr); new = (val,) + tuple(old[1:])
    def restore(o=old): setattr(MC, attr, o)
    setattr(MC, attr, new); return restore

AXES = [
    ('BASE (central)',            lambda: [], 'central'),
    ('BSFC optimistic (-6%)',     lambda: [], 'optimistic'),
    ('BSFC conservative (+9%)',   lambda: [], 'conservative'),
    ('\u03b7_gen low (0.90)',     lambda: [_set_tuple0('ETA_GEN', 0.90)], 'central'),
    ('\u03b7_gen high (0.97)',    lambda: [_set_tuple0('ETA_GEN', 0.97)], 'central'),
    ('P_aux low (0.2kW)',         lambda: [_set_tuple0('P_AUX_KW', 0.20)], 'central'),
    ('P_aux high (1.2kW)',        lambda: [_set_tuple0('P_AUX_KW', 1.20)], 'central'),
    ('cold penalty OFF',          lambda: [_set_tuple0('COLD_MULT', 1.00)], 'central'),
    ('cold penalty heavy (\u00d71.45)', lambda: [_set_tuple0('COLD_MULT', 1.45)], 'central'),
    ('OPT band wide (1750-2250)', lambda: [_set('OPT_LO', 1750.0), _set('OPT_HI', 2250.0)], 'central'),
]

def main():
    cache = build_cache()
    out = []
    for label, mutate, scen in AXES:
        restores = mutate()
        try:
            r = run_axis(cache, scen)
        finally:
            for fn in restores:
                fn()
        out.append(dict(axis=label, gen100=r['gen100'], trac100=r['trac100'],
                        fgen=r['fgen'], etaBus=r['etaBus']))
        print('  %-30s gen100=%6.2f trac100=%6.2f fgen=%.3f etaBus=%.3f (nClean=%d)'
              % (label, r['gen100'], r['trac100'], r['fgen'], r['etaBus'], r['nClean']))

    base = out[0]
    # nan-safe: a nan base value must FAIL, not silently pass (M265 lesson).
    mism = [k for k, v in SHIPPED.items()
            if not (base[k] == base[k]) or abs(base[k] - v) > 1e-9]
    if mism:
        raise SystemExit('BASE does NOT reproduce corrected headline; mismatched: %s\n  BASE=%s\n  SHIPPED=%s'
                         % (mism, base, SHIPPED))
    print('\nBASE reproduces corrected headline exactly (15.75/18.23/0.488/0.331). OK')
    fgens = [r['fgen'] for r in out]
    print('f_gen sweep range: %.3f .. %.3f (BASE %.3f)' % (min(fgens), max(fgens), out[0]['fgen']))
    json.dump(out, open('sensitivity_gtr_out.json', 'w'), ensure_ascii=False, indent=1)
    print('wrote sensitivity_gtr_out.json (%d axes)' % len(out))

if __name__ == '__main__':
    main()
