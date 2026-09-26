#!/usr/bin/env python3
"""
simultaneity_gtr.py -- rebuild generatorTractionRecon.simultaneity (currently
null; no surviving source) at the corrected M265 sign.

What it is
----------
For every engine-on second (Pgen_t>0) on the fuel-instrumented drives, solve the
same DC-bus balance central_estimate_v2 uses and label the instant by what the
generator and battery are doing SIMULTANEOUSLY, then report the duration-weighted
time share of each of four mutually-exclusive states per drive type. The states
are exactly those the dashboard prose (M249) defines:

  genPlusBattDischarge : gen running AND battery discharging into the motor,
                         traction demand present  -> generator SATURATION (buffer
                         tops up what the generator alone cannot supply).
  chargesAndDrives     : gen drives the motor AND surplus charges the battery.
  genAloneNeutral      : traction present, battery essentially idle (gen ~= trac).
  fullyBanked          : little/no traction demand -- engine output banks to the
                         pack (SoC-recovery / charging while stopped or coasting).

Substrate: recon_engine.central_estimate_v2_persample (M255) -- the byte-identical
per-sample form of central_estimate_v2, carrying the M265 sign fix. Its per-sample
Ptrac / Pgen_t / Pbatt_anch / dt sum back to the aggregate E_trac_gross etc., which
is asserted per drive before any classification is trusted (same gate speed_split.py
uses).

Classification (per engine-on second, eps in kW):
  eon = Pgen_t > 0
  if Ptrac <  EPS_TRAC          -> fullyBanked
  elif Pbatt_anch >  EPS_BATT   -> genPlusBattDischarge   (battery discharging)
  elif Pbatt_anch < -EPS_BATT   -> chargesAndDrives       (battery charging)
  else                          -> genAloneNeutral        (battery idle)

EPS_TRAC / EPS_BATT are small power deadbands (kW); a sweep is printed so the
reader can see the split is not an artifact of one threshold choice. Shares are
duration-weighted (dt), the section's convention.

No surviving numbers exist to reproduce, so this is validated three ways instead:
(1) per-drive persample->aggregate energy identity (<1e-6 kWh); (2) the four
states partition 100% of engine-on time exactly; (3) the qualitative pattern is
reported, NOT assumed -- if urban does not read as more saturated than highway,
that is surfaced, not smoothed over.
"""
import os, json, warnings
import numpy as np, pandas as pd
import recon_engine as RE, model_constants as MC, fuel_recon as FR
warnings.filterwarnings('ignore')

BASE = RE.BASE
CLASS_ORDER = ['urban', 'mixed', 'mixed_highway', 'highway']
EPS_TRAC = 0.5   # kW -- "little/no traction demand" deadband
EPS_BATT = 0.5   # kW -- "battery essentially idle" deadband

def build_cache():
    dm = pd.read_csv(BASE + 'drive_master.csv')
    master = {r['file']: r for _, r in dm.iterrows()}
    targets = [f for f in dm['file'] if os.path.exists(BASE + f) and FR._has_fuel(BASE + f)]
    cache = []
    max_ident_err = 0.0
    for f in targets:
        mrow = master[f]
        off = float(mrow.get('I_offset_A_applied', 0.0) or 0.0)
        g = RE.load_drive(f, off)
        if g is None:
            continue
        dist = float(mrow['distance_km'])
        if not (dist > 0):
            continue
        pc = RE.precompute(g)
        agg, ps = RE.central_estimate_v2_persample(pc, mrow, 'central')
        if agg is None:
            continue
        # (1) per-drive persample -> aggregate identity gate
        Ptrac, dt = ps['Ptrac'], ps['dt']
        e_trac_ps = float(np.sum(np.maximum(Ptrac, 0.0) * dt) / 3600.0)
        max_ident_err = max(max_ident_err, abs(e_trac_ps - agg['E_trac_gross']))
        cache.append(dict(file=f, drive_type=str(mrow['drive_type']),
                          fgen=agg['f_gen'],
                          Ptrac=Ptrac, Pgen_t=ps['Pgen_t'],
                          Pbatt=ps['Pbatt_anch'], dt=dt))
    print('cache: %d fuel drives | max persample->aggregate E_trac err %.2e kWh' %
          (len(cache), max_ident_err))
    assert max_ident_err < 1e-6, "persample arrays must reproduce the aggregate"
    return cache

def classify(cache, eps_trac=EPS_TRAC, eps_batt=EPS_BATT, clean_only=True):
    acc = {k: dict(gpd=0.0, cad=0.0, gan=0.0, fb=0.0, eon=0.0, n=0) for k in CLASS_ORDER}
    for e in cache:
        if clean_only and not (e['fgen'] == e['fgen']):
            continue
        dtp = str(e['drive_type'])
        if dtp not in acc:
            continue
        Pg, Pt, Pb, dt = e['Pgen_t'], e['Ptrac'], e['Pbatt'], e['dt']
        eon = Pg > 0.0
        if not eon.any():
            continue
        trac = eon & (Pt >= eps_trac)
        fb = eon & (Pt < eps_trac)
        gpd = trac & (Pb > eps_batt)
        cad = trac & (Pb < -eps_batt)
        gan = trac & (np.abs(Pb) <= eps_batt)
        a = acc[dtp]
        a['gpd'] += float(np.sum(dt[gpd])); a['cad'] += float(np.sum(dt[cad]))
        a['gan'] += float(np.sum(dt[gan])); a['fb'] += float(np.sum(dt[fb]))
        a['eon'] += float(np.sum(dt[eon])); a['n'] += 1
    rows = []
    for k in CLASS_ORDER:
        a = acc[k]
        if a['eon'] <= 0:
            continue
        tot = a['eon']
        rows.append(dict(
            type=k, nDrives=a['n'], engineOnHours=round(tot / 3600.0, 1),
            genPlusBattDischarge=round(a['gpd'] / tot * 100, 1),
            chargesAndDrives=round(a['cad'] / tot * 100, 1),
            genAloneNeutral=round(a['gan'] / tot * 100, 1),
            fullyBanked=round(a['fb'] / tot * 100, 1),
        ))
    return rows

def main():
    cache = build_cache()
    rows = classify(cache)
    print('\nsimultaneity (EPS_TRAC=%.2f, EPS_BATT=%.2f kW), clean fuel drives:' % (EPS_TRAC, EPS_BATT))
    for r in rows:
        s = r['genPlusBattDischarge'] + r['chargesAndDrives'] + r['genAloneNeutral'] + r['fullyBanked']
        print('  %-14s n=%2d %5.1fh  gpd=%4.1f cad=%4.1f gan=%4.1f fb=%4.1f  (sum=%.1f)' %
              (r['type'], r['nDrives'], r['engineOnHours'],
               r['genPlusBattDischarge'], r['chargesAndDrives'],
               r['genAloneNeutral'], r['fullyBanked'], s))
        assert abs(s - 100.0) < 0.2, "the four states must partition engine-on time"

    # (3) pattern check -- reported, not assumed
    d = {r['type']: r for r in rows}
    if 'urban' in d and 'highway' in d:
        print('\npattern check (prose claims urban saturated > highway):')
        print('  urban gpd %.1f vs highway gpd %.1f  -> %s'
              % (d['urban']['genPlusBattDischarge'], d['highway']['genPlusBattDischarge'],
                 'MATCHES prose' if d['urban']['genPlusBattDischarge'] > d['highway']['genPlusBattDischarge']
                 else 'CONTRADICTS prose -- do NOT publish without revising prose'))
        print('  urban cad %.1f vs highway cad %.1f  -> %s'
              % (d['urban']['chargesAndDrives'], d['highway']['chargesAndDrives'],
                 'MATCHES prose' if d['highway']['chargesAndDrives'] > d['urban']['chargesAndDrives']
                 else 'CONTRADICTS prose'))

    # (2) threshold sensitivity sweep
    print('\nthreshold sweep (urban gpd / highway gpd / urban cad / highway cad):')
    for et in (0.25, 0.5, 1.0):
        for eb in (0.25, 0.5, 1.0):
            rr = {r['type']: r for r in classify(cache, et, eb)}
            if 'urban' in rr and 'highway' in rr:
                print('  eps_trac=%.2f eps_batt=%.2f -> u_gpd %4.1f  h_gpd %4.1f  u_cad %4.1f  h_cad %4.1f'
                      % (et, eb, rr['urban']['genPlusBattDischarge'], rr['highway']['genPlusBattDischarge'],
                         rr['urban']['chargesAndDrives'], rr['highway']['chargesAndDrives']))

    json.dump(dict(rows=rows, params=dict(epsTracKw=EPS_TRAC, epsBattKw=EPS_BATT)),
              open('simultaneity_gtr_out.json', 'w'), ensure_ascii=False, indent=1)
    print('\nwrote simultaneity_gtr_out.json')

if __name__ == '__main__':
    main()
