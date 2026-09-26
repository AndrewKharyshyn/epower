#!/usr/bin/env python3
"""
fuel_recon.py — ADDITIVE generator/traction electrical-energy reconstruction
for the Nissan X-Trail T33 e-POWER OBD-II study (fuel/BSFC Path B).

Contract:
  * NEVER writes drive_master.csv (owned by compute_drive_summary_v6.py under a
    byte-exact regression harness). Reads it only for battery-energy anchors and
    the calibrated current offset; joins on the canonical `file` key.
  * Emits per-drive fuel_* rows into a COMPANION master: fuel_recon_master.csv.
  * Fuel = E10: density -> fuel MASS -> BSFC->engine->generator->traction chain;
    LHV -> chemical energy & thermal efficiency ONLY.
  * Cold gate = engine OIL temperature (<55 C), coolant fallback, no restart term.
  * All generator/traction figures are MODEL-DERIVED (generator is not a measured channel).

Usage:
  python3 fuel_recon.py DRIVE.csv [...]     process specific drives
  python3 fuel_recon.py --all               (re)build from every fuel-instrumented drive
  python3 fuel_recon.py --mc 1 DRIVE.csv    also attach optimistic/conservative scenario band
"""
import sys, os, argparse, json, warnings
import numpy as np, pandas as pd
warnings.filterwarnings('ignore')
import model_constants as MC
import recon_engine as RE

BASE = RE.BASE
MASTER = 'fuel_recon_master.csv'
FUEL_FLOW_COL = 'Витрати палива (L/h)'

def _has_fuel(fp):
    try:
        cols = pd.read_csv(fp, nrows=0, low_memory=False).columns
    except Exception:
        return False
    return any(FUEL_FLOW_COL.lower() in c.lower() for c in cols)

# Charge-sustaining band (P0-4, audit F-05). The documented convention is a
# drive whose net SoC change is within +/-2 percentage points ("charge
# sustaining" in the series-hybrid sense: the buffer returns to ~its starting
# state, so measured fuel maps cleanly to traction demand without a large
# battery credit/debit). The SoC change IS directly measured in the master as
# soc_end - soc_start (both in %), so the band needs NO capacity assumption.
#
# The previous implementation requested a `soc_delta_pp` column that the master
# never carried, then fell through to |soc_delta_kwh| <= 0.25 kWh. At the
# CAP_KWH=2.1 anchor that threshold is ~11.9 pp -- about six times looser than
# the stated +/-2 pp -- and it disagreed with the documented rule on 88 of 138
# fuel-cohort rows (121 vs 33 flagged charge-sustaining). The band is now
# computed from the measured SoC endpoints directly; the kWh path is retained
# only as a last-resort fallback for any drive missing soc_start/soc_end, and
# converted to the SAME +/-2 pp band via the capacity anchor so both paths carry
# one convention. See CHANGELOG P0-4.
CS_BAND_PP = 2.0                      # charge-sustaining tolerance, SoC points
_CS_CAP_KWH = 2.1                     # fallback-only pp<->kWh anchor (CAP_KWH,
                                      # verified:false); used only when SoC
                                      # endpoints are unavailable.


def _soc_delta_pp(mrow):
    """Net SoC change in percentage points, measured (soc_end - soc_start).
    Returns None if either endpoint is unavailable."""
    s0 = mrow.get('soc_start', None)
    s1 = mrow.get('soc_end', None)
    try:
        if s0 is not None and s0 == s0 and s1 is not None and s1 == s1:
            return float(s1) - float(s0)
    except (TypeError, ValueError):
        pass
    return None


def _cs(mrow):
    # Primary: an explicit soc_delta_pp column if a future master provides one.
    dp = mrow.get('soc_delta_pp', None)
    if dp is not None and dp == dp:
        return bool(abs(float(dp)) <= CS_BAND_PP)
    # Measured: net SoC endpoints (no capacity assumption).
    pp = _soc_delta_pp(mrow)
    if pp is not None:
        return bool(abs(pp) <= CS_BAND_PP)
    # Fallback only: convert the +/-2 pp band to kWh via the capacity anchor.
    thr_kwh = CS_BAND_PP / 100.0 * _CS_CAP_KWH        # 0.042 kWh at 2.1 kWh
    return bool(abs(float(mrow.get('soc_delta_kwh', 0) or 0)) <= thr_kwh)

def reconstruct(fname, mrow, offset, band=False):
    g = RE.load_drive(fname, offset)
    if g is None:
        return None
    pc = RE.precompute(g)
    ce = RE.central_estimate_v2(pc, mrow, 'central')
    if ce is None:
        return None
    dist = float(mrow['distance_km'])
    if not (dist > 0):
        return None
    def p100(x):
        return round(x / dist * 100, 3) if dist > 0 else np.nan
    fuel_L = float(pc['vol_total'])
    trac_net = ce['E_trac_gross'] - ce.get('E_trac_regen', 0.0)
    row = dict(
        file=fname, drive_type=mrow['drive_type'], date=mrow['date'], distance_km=round(dist, 3),
        fuel_L_per_100km=round(fuel_L / dist * 100, 3) if dist > 0 else np.nan,
        fuel_chem_kWh_100=p100(ce['E_fuel']),
        generator_kWh_100=p100(ce['E_gen']),
        traction_gross_kWh_100=p100(ce['E_trac_gross']),
        traction_net_kWh_100=p100(trac_net),
        gen_to_traction_kWh_100=p100(ce['E_gen_to_trac']),
        batt_to_traction_kWh_100=p100(ce['E_batt_to_trac']),
        regen_to_batt_kWh_100=p100(ce.get('regen_to_batt', np.nan)),
        gen_to_batt_kWh_100=p100(ce.get('gen_to_batt', np.nan)),
        f_gen=round(ce['f_gen'], 4),
        eta_eng=round(ce['eta_eng'], 4), eta_fuel_bus=round(ce['eta_fuel_bus'], 4),
        cold_fuel_frac=round(ce['cold_fuel_frac'], 4),
        soc_delta_kwh=round(float(mrow.get('soc_delta_kwh', np.nan)), 4),
        charge_sustaining=_cs(mrow),
        fuel_basis='E10', density_g_per_L=MC.RHO_G_PER_L[0], LHV_MJ_per_kg=MC.LHV_MJ_PER_KG[0],
        cold_gate='oil<55C', method='PathB_fuel_BSFC_v1',
    )
    if band:
        acc = {}
        for sc in ('optimistic', 'conservative'):
            e = RE.central_estimate_v2(pc, mrow, sc)
            if e:
                acc.setdefault('generator_kWh_100_band', []).append(round(e['E_gen'] / dist * 100, 3))
                acc.setdefault('traction_gross_kWh_100_band', []).append(round(e['E_trac_gross'] / dist * 100, 3))
                acc.setdefault('f_gen_band', []).append(round(e['f_gen'], 4))
        row.update({k: json.dumps(sorted(v)) for k, v in acc.items()})
    return row

def upsert_master(rows):
    rows = [r for r in rows if r]
    if not rows:
        print('no rows to write'); return
    new = pd.DataFrame(rows)
    if os.path.exists(MASTER):
        old = pd.read_csv(MASTER)
        old = old[~old['file'].isin(new['file'])]
        out = pd.concat([old, new], ignore_index=True)
    else:
        out = new
    out = out.sort_values(['drive_type', 'date', 'file']).reset_index(drop=True)
    out.to_csv(MASTER, index=False)
    print(f'{MASTER}: {len(out)} rows total ({len(new)} added/updated)')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='*')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--mc', type=int, default=0, help='if >0, attach optimistic/conservative scenario band')
    a = ap.parse_args()
    dm = pd.read_csv(BASE + 'drive_master.csv')
    master = {r['file']: r for _, r in dm.iterrows()}
    targets = ([f for f in dm['file'] if os.path.exists(BASE + f) and _has_fuel(BASE + f)]
               if a.all else [os.path.basename(f) for f in a.files])
    print(f'processing {len(targets)} fuel drive(s); band={bool(a.mc)}')
    rows = []
    for f in targets:
        if f not in master:
            print(f'  skip {f}: not in drive_master'); continue
        if not _has_fuel(BASE + f):
            print(f'  skip {f}: no fuel-flow PID'); continue
        off = float(master[f].get('I_offset_A_applied', 0.0) or 0.0)
        r = reconstruct(f, master[f], off, band=bool(a.mc))
        if r:
            rows.append(r); print(f'  ok  {f}: gen={r["generator_kWh_100"]} f_gen={r["f_gen"]} eta_eng={r["eta_eng"]}')
        else:
            print(f'  --  {f}: reconstruction returned None')
    upsert_master(rows)

if __name__ == '__main__':
    main()
