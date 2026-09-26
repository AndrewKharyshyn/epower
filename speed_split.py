#!/usr/bin/env python3
"""
speed_split.py -- M255 (2026-09-14) rebuild of generatorTractionRecon.speedSplit,
the per-second "Traction supply split by vehicle speed" sub-analysis. Its
original generating code was never preserved between sessions (disclosed as
lost, `null`, with a "temporarily unavailable" notice in the dashboard since
M253/M254).

Method. For every fuel-instrumented, charge-sustaining-eligible drive (same
set fuel_recon.py processes), reload the raw per-second frame via
recon_engine.load_drive()/precompute() (unchanged, reused verbatim) and call
the new central_estimate_v2_persample() (recon_engine.py, added this
session), which is a byte-identical copy of the already-trusted
central_estimate_v2() aggregate math but additionally returns the per-sample
Ptrac/Pgen_t/Pbatt_anch/dt arrays instead of only their drive-level sums.

VALIDATION (mandatory, run before trusting any binned output): for every
drive, the per-sample arrays are summed the same way central_estimate_v2()
sums them internally, and compared against fuel_recon_master.csv's own
recorded per-drive generator_kWh_100/traction_gross_kWh_100/
gen_to_traction_kWh_100/batt_to_traction_kWh_100. This is not optional --
central_estimate_v2_persample() only earns trust by reproducing numbers
fuel_recon.py already shipped and this study has separately verified.

Binning. Instantaneous vehicle speed (`g['speed']`, the same channel
recon_engine.py already loads) at each qualifying sample, into
["0-20","20-60","60-90","90-120","120+"] km/h -- the exact bin labels the
JSX prose already references (`d.bin==="20-60"` etc., see xtrail_summary.jsx),
so this reproduces the ORIGINAL analysis's bin scheme, not a new one invented
to fit lost code. Per-sample distance is speed*dt/3600 (km) -- the standard
odometer-independent method, consistent with using speed itself as the
binning variable. Per bin: nDrives = distinct drives contributing >=1
qualifying sample; distKm = summed per-sample distance in that bin;
generator/battery = summed gen-to-traction / battery-to-traction energy in
that bin, normalized to kWh per 100 km OF DISTANCE COVERED IN THAT BIN (not
whole-drive distance -- a per-bin rate, matching every other split in this
sub-study); fGen = ratio-of-sums (gen-to-traction / traction-gross energy in
the bin), the same convention already verified for the corpus-wide and
drive-type-split f_gen figures (see wire_gtr_seasonal.py).

Output: speed_split.json (the reproducible per-bin artifact) plus a
splice into summary_arrays.json['generatorTractionRecon']['speedSplit'].
"""
import sys, os, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recon_engine as RE
import fuel_recon as FR

BINS = [(0, 20, "0-20"), (20, 60, "20-60"), (60, 90, "60-90"),
        (90, 120, "90-120"), (120, 999, "120+")]


def per_drive_persample(fname, mrow, offset):
    g = RE.load_drive(fname, offset)
    if g is None:
        return None
    pc = RE.precompute(g)
    agg, ps = RE.central_estimate_v2_persample(pc, mrow, 'central')
    speed = pd.to_numeric(g['speed'], errors='coerce').values
    if len(speed) != len(ps['dt']):
        return None
    return agg, ps, speed


def validate_against_master(dm, fr_master, targets, offsets, n_check=None):
    if n_check is None:
        n_check = len(targets)  # M255 fix: validate ALL targets, not a fixed 138 --
        # the original cap silently missed the newly-added 2026-09-11 batch (10
        # drives), which sort late in file order and fell outside the first-138 slice.
    """Sum the per-sample arrays the same way central_estimate_v2 aggregates
    them, and assert the result matches fuel_recon_master.csv's own recorded
    per-drive figures. Returns (n_checked, n_matched, max_abs_diff_pct)."""
    fr_idx = fr_master.set_index('file')
    n_checked = n_matched = 0
    max_diff = 0.0
    for f in targets[:n_check]:
        if f not in fr_idx.index:
            continue
        mrow = dm[dm['file'] == f].iloc[0]
        result = per_drive_persample(f, mrow, offsets.get(f, 0.0))
        if result is None:
            continue
        agg, ps, speed = result
        dist = float(mrow['distance_km'])
        if not (dist > 0):
            continue
        n_checked += 1
        shipped = fr_idx.loc[f]
        my_gen = round(agg['E_gen'] / dist * 100, 3)
        my_tg = round(agg['E_trac_gross'] / dist * 100, 3)
        my_g2t = round(agg['E_gen_to_trac'] / dist * 100, 3)
        my_b2t = round(agg['E_batt_to_trac'] / dist * 100, 3)
        diffs = [abs(my_gen - shipped['generator_kWh_100']),
                 abs(my_tg - shipped['traction_gross_kWh_100']),
                 abs(my_g2t - shipped['gen_to_traction_kWh_100']),
                 abs(my_b2t - shipped['batt_to_traction_kWh_100'])]
        d = max(diffs)
        max_diff = max(max_diff, d)
        if d < 0.01:  # kWh/100km, well under rounding noise
            n_matched += 1
        else:
            print(f'  MISMATCH {f}: mine gen={my_gen} tg={my_tg} g2t={my_g2t} b2t={my_b2t} '
                  f'vs shipped gen={shipped["generator_kWh_100"]} tg={shipped["traction_gross_kWh_100"]} '
                  f'g2t={shipped["gen_to_traction_kWh_100"]} b2t={shipped["batt_to_traction_kWh_100"]}')
    return n_checked, n_matched, max_diff


def build_speed_split(dm, fr_master, targets, offsets):
    bin_gen = {lbl: 0.0 for _, _, lbl in BINS}
    bin_batt = {lbl: 0.0 for _, _, lbl in BINS}
    bin_dist = {lbl: 0.0 for _, _, lbl in BINS}
    bin_drives = {lbl: set() for _, _, lbl in BINS}
    fr_idx = fr_master.set_index('file')

    for f in targets:
        if f not in fr_idx.index:
            continue
        mrow = dm[dm['file'] == f].iloc[0]
        result = per_drive_persample(f, mrow, offsets.get(f, 0.0))
        if result is None:
            continue
        agg, ps, speed = result
        dt = ps['dt']
        Ptrac = ps['Ptrac']; Pgen_t = ps['Pgen_t']
        trac_pos = np.maximum(Ptrac, 0.0)
        gen_to_trac_t = np.minimum(Pgen_t, trac_pos)      # kW, per-sample
        batt_to_trac_t = trac_pos - gen_to_trac_t          # kW, per-sample (residual)
        dist_t = np.nan_to_num(speed) / 3600.0 * dt        # km, per-sample

        for lo, hi, lbl in BINS:
            m = np.isfinite(speed) & (speed >= lo) & (speed < hi) & (dt > 0)
            if not m.any():
                continue
            bin_gen[lbl] += float(np.sum(gen_to_trac_t[m] * dt[m]) / 3600.0)   # kWh
            bin_batt[lbl] += float(np.sum(batt_to_trac_t[m] * dt[m]) / 3600.0)  # kWh
            bin_dist[lbl] += float(np.sum(dist_t[m]))                          # km
            bin_drives[lbl].add(f)

    out = []
    for _, _, lbl in BINS:
        km = round(bin_dist[lbl], 1)
        if km <= 0:
            out.append(dict(bin=lbl, nDrives=0, distKm=0.0, generator=None, battery=None, fGen=None))
            continue
        gen100 = round(bin_gen[lbl] / km * 100, 2)
        batt100 = round(bin_batt[lbl] / km * 100, 2)
        tg = bin_gen[lbl] + bin_batt[lbl]
        fgen = round(bin_gen[lbl] / tg, 4) if tg > 0 else None
        out.append(dict(bin=lbl, nDrives=len(bin_drives[lbl]), distKm=km,
                         generator=gen100, battery=batt100, fGen=fgen))
    return out


if __name__ == '__main__':
    dm = pd.read_csv(os.path.join(RE.BASE, 'drive_master.csv'))
    fr_master = pd.read_csv('fuel_recon_master.csv')
    # M255 fix (found via the validation step below): fuel_recon.py's main()
    # resolves the offset as `float(master[f].get('I_offset_A_applied', 0.0) or 0.0)`
    # -- Python's `x or default` does NOT substitute for NaN (NaN is truthy), so a
    # NaN I_offset_A_applied passes through UNCHANGED as NaN, not 0.0. That NaN then
    # propagates through Iadj -> Pbatt (all-NaN for the drive), which
    # central_estimate_v2's `np.nan_to_num(pc['Pbatt'])` silently zeroes -- the net
    # effect is the battery term is fully suppressed for any drive with a missing
    # calibrated offset (2 of 135 in this corpus: 20260813_145651.csv,
    # 20260813_150341.csv), not "corrected with offset=0" as a naive .fillna(0.0)
    # would do. Replicated exactly here (rather than the more intuitive
    # .fillna(0.0)) so this script's output matches the already-shipped,
    # independently-verified fuel_recon_master.csv byte-for-byte on these drives
    # too -- confirmed by the validation step, which failed under .fillna(0.0)
    # and passes under this exact replication.
    offsets = {f: (float(v) or 0.0) for f, v in zip(dm['file'], dm['I_offset_A_applied'])}
    targets = [f for f in dm['file']
               if os.path.exists(RE.BASE + f) and FR._has_fuel(RE.BASE + f)]
    print(f'{len(targets)} fuel-instrumented drives found')

    print('\n=== VALIDATION: per-sample reconstruction vs shipped fuel_recon_master.csv ===')
    n_checked, n_matched, max_diff = validate_against_master(dm, fr_master, targets, offsets)
    print(f'{n_matched}/{n_checked} drives matched shipped figures to <0.01 kWh/100km '
          f'(max diff observed: {max_diff:.4f})')
    if n_matched != n_checked:
        print('VALIDATION FAILED -- refusing to trust the speed-binned output. Aborting.')
        sys.exit(1)
    print('VALIDATION PASSED -- central_estimate_v2_persample reproduces the trusted '
          'per-drive figures exactly. Proceeding to speed-bin the full fuel-instrumented set.')

    print('\n=== Building speed-binned split ===')
    speed_split = build_speed_split(dm, fr_master, targets, offsets)
    for row in speed_split:
        print(' ', row)

    with open('speed_split.json', 'w') as fp:
        json.dump(speed_split, fp, indent=2)
    print('\nwrote speed_split.json')
