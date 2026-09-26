#!/usr/bin/env python3
"""
crossval_gtr.py -- reproduce and sign-audit the §4b Path A (road-load) vs
Path B (fuel/BSFC) generator cross-validation
(generatorTractionRecon.crossval).

Context
-------
The cross-validation's per-drive source, `crossval.csv` (82 fuel-instrumented
drives), was recovered 2026-09-17 after being reported lost. It carries, per
drive: E_gen_fuel / E_trac_fuel (Path B), E_gen_roadload / E_trac_roadload
(Path A, road-load P_wheel=(C_rr*m*g + 0.5*rho*C_dA*v^2 + m*a)*v -> electrical),
and gen_ratio = roadload/fuel. The Path A road-load COEFFICIENTS (m, C_rr,
C_dA, eta_dt) were NOT preserved in any surviving script -- only these outputs
survive -- so Path A cannot be recomputed for drives outside this 82-set
without re-introducing assumed coefficients (which would be fabrication, not
restoration). The cross-validation therefore stands at its 82-drive basis.

Two things this script establishes:
  1. crossval.csv reproduces the shipped crossval dict
     (pearsonR, nDrives, genRatioMedian, genRatioIqr) exactly.
  2. The cross-validation is SIGN-INVARIANT w.r.t. the M265 battery-current
     fix: Path B *generator* energy is a fuel->BSFC quantity, independent of
     battery sign, so re-running the current (M265-corrected) recon_engine on
     the same 82 drives leaves E_gen_fuel -- and hence pearsonR and the
     gen_ratio distribution -- unchanged. (Path B *traction* DOES move,
     23.19 -> 18.00 kWh/100km, which is why the traction-level band tightens
     toward the independent road-load Path A traction, 17.45 -- an independent
     corroboration of M265, not a change to the cross-validation statistic.)

Output: crossval_gtr_out.json (the verified crossval dict + the sign-audit).
"""
import json
import numpy as np, pandas as pd, os
import recon_engine as RE, model_constants as MC

CROSSVAL_CSV = '/mnt/user-data/uploads/crossval.csv'  # recovered source
SHIPPED = dict(pearsonR=0.997, nDrives=82, genRatioMedian=1.177,
               genRatioIqr=[0.995, 1.282])

def main():
    cv = pd.read_csv(CROSSVAL_CSV)
    assert {'file', 'E_gen_fuel', 'E_gen_roadload', 'E_trac_fuel',
            'E_trac_roadload', 'gen_ratio'} <= set(cv.columns)

    # (1) reproduce shipped stats
    r = float(np.corrcoef(cv['E_gen_fuel'], cv['E_gen_roadload'])[0, 1])
    med = float(cv['gen_ratio'].median())
    q1, q3 = float(cv['gen_ratio'].quantile(.25)), float(cv['gen_ratio'].quantile(.75))
    crossval = dict(pearsonR=round(r, 3), nDrives=int(len(cv)),
                    genRatioMedian=round(med, 3),
                    genRatioIqr=[round(q1, 3), round(q3, 3)])
    assert crossval['pearsonR'] == SHIPPED['pearsonR'], (crossval, SHIPPED)
    assert crossval['nDrives'] == SHIPPED['nDrives']
    assert crossval['genRatioMedian'] == SHIPPED['genRatioMedian']
    assert [round(q1, 3), round(q3, 3)] == SHIPPED['genRatioIqr']
    print('reproduced shipped crossval dict exactly:', crossval)

    # (2) sign-audit against the current M265-corrected engine
    dm = pd.read_csv(RE.BASE + 'drive_master.csv')
    master = {row['file']: row for _, row in dm.iterrows()}
    rows = []
    for f in cv['file']:
        mrow = master.get(f)
        if mrow is None:
            continue
        off = float(mrow.get('I_offset_A_applied', 0.0) or 0.0)
        g = RE.load_drive(f, off)
        if g is None:
            continue
        dist = float(mrow['distance_km'])
        if not (dist > 0):
            continue
        pc = RE.precompute(g)
        ce = RE.central_estimate_v2(pc, mrow, 'central')
        rows.append(dict(file=f, E_gen_fuel_now=ce['E_gen'],
                         E_trac_fuel_now=ce['E_trac_gross']))
    now = pd.DataFrame(rows)
    m = cv.merge(now, on='file')
    r_now = float(np.corrcoef(m['E_gen_fuel_now'], m['E_gen_roadload'])[0, 1])
    ratio_now = (m['E_gen_roadload'] / m['E_gen_fuel_now'])
    dwt = lambda c: float(m[c].sum() / m['dist'].sum() * 100)
    audit = dict(
        nRecomputed=int(len(m)),
        genFuel_dwt_old=round(dwt('E_gen_fuel'), 2),
        genFuel_dwt_now=round(dwt('E_gen_fuel_now'), 2),
        tracFuel_dwt_old=round(dwt('E_trac_fuel'), 2),
        tracFuel_dwt_now=round(dwt('E_trac_fuel_now'), 2),
        tracRoadload_dwt=round(dwt('E_trac_roadload'), 2),
        pearsonR_now=round(r_now, 3),
        genRatioMedian_now=round(float(ratio_now.median()), 3),
        genRatioIqr_now=[round(float(ratio_now.quantile(.25)), 3),
                         round(float(ratio_now.quantile(.75)), 3)],
    )
    print('sign-audit:', json.dumps(audit, indent=1))

    sign_invariant = (audit['genFuel_dwt_now'] == audit['genFuel_dwt_old']
                      and audit['pearsonR_now'] == crossval['pearsonR']
                      and audit['genRatioMedian_now'] == crossval['genRatioMedian'])
    print('\nSIGN-INVARIANT (generator cross-validation unchanged by M265):', sign_invariant)
    print('traction Path B moved %.2f -> %.2f, toward independent Path A road-load %.2f'
          % (audit['tracFuel_dwt_old'], audit['tracFuel_dwt_now'], audit['tracRoadload_dwt']))
    assert sign_invariant, "expected the generator cross-validation to be sign-invariant"

    json.dump(dict(crossval=crossval, signAudit=audit, signInvariant=sign_invariant),
              open('crossval_gtr_out.json', 'w'), ensure_ascii=False, indent=1)
    print('wrote crossval_gtr_out.json')

if __name__ == '__main__':
    main()
