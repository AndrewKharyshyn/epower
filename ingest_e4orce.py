"""ingest_e4orce.py  (M128, 2026-08-17)

M128 (2026-08-17). CAP-INVARIANCE RELAXED FOR THE ENERGY SET. The original rail
(M127) admitted only CAP_KWH-invariant quantities because the AWD pack capacity
was treated as independently unverified. Two facts, now corroborated, remove that
barrier for cross-vehicle *energy* comparison and are both carried as explicit
verified:false assumptions:
  (1) Shared pack. The T33 X-Trail e-POWER carries the same 2.1 kWh Li-ion pack
      (~1.8 kWh usable) in FWD and e-4ORCE; the AWD delta is purely the rear MM48
      motor (Nissan spec). CAP_KWH = 2.1 therefore applies to BOTH vehicles, so a
      shared constant cancels in ratios/normalised forms and is a common
      multiplicative factor in absolute levels.
  (2) Shared current-offset phenomenon. Running the IDENTICAL SoC-anchored
      estimator (M13/M24) on this rail's own 9 drives reproduces the main rail's
      offset in sign (charge-biased, 100% of bootstrap resamples), order of
      magnitude, and duration-signature (corr(residual,duration) = -0.72 vs main
      -0.86). e-4ORCE self-estimate -0.547 A, drive-bootstrap 95% CI
      [-0.70,-0.29]; the main-rail -0.4130 A lies inside that CI. The rail
      self-estimates its OWN global offset (offset_source='soc_anchored_global'),
      exactly as the main rail does — no value is imported — recomputed each
      ingest so it refines as drives are added. No bench calibration is feasible
      for this vehicle; this data-driven estimator is the same one the main rail
      relies on when no calibration log is present.
Energy columns are thus emitted (see _ADMISSIBLE / _CAP_ADMITTED and
_apply_soc_anchored_offset). The defect guard is retained and still fires for any
CAP-dependent column NOT explicitly vetted. Admissibility unlocks the UNIT only,
not the STRATUM: cross-vehicle energy comparison remains confined to the matched
urban/mixed strata (the rail has no highway/mixed_highway coverage), and the two
broken-distance drives stay barred from any per-100 km figure (their per-time
energy and the offset estimate itself remain valid, since the estimator uses
DSoC, integral(I.V)dt, time and voltage — never distance).

------------------------------------------------------------------------
ingest_e4orce.py  (M127, 2026-08-16)

Segregated ingestion of the e-4ORCE AWD cross-check rail into its OWN master
(``e4orce_master.csv``). This rail is NEVER merged into the primary corpus:
``corpus_manifest.py`` already tags every ``e4orce_*.csv`` as role='auxiliary',
and this module writes only to ``e4orce_master.csv`` -- it does not read, touch,
or emit ``drive_master.csv``.

Two things distinguish this rail from the primary FWD corpus and both are handled
here:

  1. DUAL FILE FORMAT. Exactly one capture (2026-08-07) is the WIDE primary-corpus
     layout (``time, "[BMS] ...", ...``). The other eight are a LONG/tidy export
     (``"SECONDS";"PID";"VALUE";"UNITS"``, semicolon-delimited, CRLF, SECONDS =
     seconds-since-midnight). ``_normalize_bytes`` pivots the long form to the wide
     schema, reconstructing the canonical ``"{PID} ({UNITS})"`` column names so the
     shared ``COL_MAP`` and the *unmodified* per-drive extractor apply verbatim.

  2. CAP_KWH INADMISSIBILITY. The AWD carries an independently-unverified pack
     capacity, so only CAP_KWH-invariant quantities (%, A, 1/h, Ohm, mV, degC,
     N.m, dimensionless ratios) are admissible for cross-vehicle comparison. The
     ``_ADMISSIBLE`` allowlist below is an EXPLICIT allowlist (not a denylist): any
     column that is not enumerated -- in particular every ``*_kwh``, ``peak_*_kw``,
     ``soc_delta_kwh``, ``cap_ah_est``, ``gtc``/``rf_efc`` -- is dropped before the
     row is written, so a CAP-dependent quantity cannot leak into the rail by
     omission.

Resistance uses the IDENTICAL main-corpus estimator: ``compute_drive_summary_v6
._vsag_metrics`` (M25b Huber regression V ~ b0 + b1*soc + b2*Id as the primary
estimate, R = -b2, with the v-sag rest-curve method as an independent cross-check;
same VREG_MIN_N/VREG_MIN_I_P95 thresholds and the same 0..500 mOhm plausibility
window). No bespoke estimator. Drives whose coverage falls below those inherited
thresholds carry NaN resistance (disclosed, not forced) -- consistent with the
study's disclose-don't-patch stance.

The ambient covariate is supplied EXTERNALLY (``e4orce_ambient.csv``: file,
ambient_c) because the e-4ORCE logs carry no OBD ambient-air PID. It is a
per-drive scalar covariate joined at ingest, analogous to ``calibration_ledger``:
the raw CSVs are never modified.
"""
import os
import io
import re
import glob
import importlib.util

import numpy as np
import pandas as pd

import project_paths

_HERE = os.path.dirname(os.path.abspath(__file__))


# ----------------------------------------------------------------------
# reuse the UNMODIFIED primary per-drive extractor
# ----------------------------------------------------------------------
def _load_v6(path=None):
    path = path or os.path.join(_HERE, 'compute_drive_summary_v6.py')
    spec = importlib.util.spec_from_file_location('compute_drive_summary_v6', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ----------------------------------------------------------------------
# CAP_KWH-invariant allowlist. EXPLICIT: anything not listed is dropped.
# ----------------------------------------------------------------------
_ADMISSIBLE = [
    # -- identity / context (dimensionless, km, s, %, source strings) --
    'file', 'date', 'time_start', 'time_end', 'drive_type', 'pipeline_version',
    'distance_km', 'duration_s', 'integr_time_h',
    'n_raw_rows', 'n_I_samples', 'I_sample_period_s', 'sign_check',
    'speed_source', 'speed_max', 'speed_mean', 'speed_mean_moving', 'speed_p95',
    'pct_urban', 'pct_highway', 'stationary_pct', 'engine_on_pct',
    'accel_max_g', 'accel_min_g', 'accel_p05_g', 'accel_p95_g',
    # -- SoC operating window (%) --
    'soc_start', 'soc_end', 'soc_min', 'soc_max', 'soc_band',
    'rf_socmean_wtd_pct', 'rf_dod_max_pct', 'rf_dod_wmean_pct',
    # -- cell spread (mV) --
    'cell_spread_mean_mv', 'cell_spread_max_mv', 'cell_spread_p95_mv',
    'cell_spread_loaded_mean_mv', 'cell_spread_loaded_max_mv',
    'cell_spread_loaded_p95_mv', 'n_loaded_spread_samples',
    # -- internal resistance (mOhm / A / %) : identical main-corpus estimator --
    'vsag_R_pack_mohm', 'vsag_R_iqr_mohm', 'vsag_I_mean_A', 'vsag_soc_mean',
    'n_vsag_rest', 'n_vsag_load',
    'vreg_R_pack_mohm', 'n_vreg_samples', 'vreg_I_p95_A',
    # -- current / C-rate (A, 1/h) --
    'peak_I_discharge', 'peak_I_charge',
    'dual_peak_A', 'dual_peak_Crate', 'regen_peak_A', 'regen_peak_Crate',
    'eng_charge_peak_A', 'eng_charge_peak_Crate',
    # -- dimensionless charge/regen ratios --
    'charge_fraction', 'regen_share_of_charge',
    # -- pack voltage (V) --
    'V_pack_median',
    # -- thermal (degC) --
    'T_pack_mean_avg', 'T_pack_mean_max', 'T1_peak', 'T2_peak', 'T3_peak',
    'T4_peak', 'T1_minus_pack_max', 'T_intake', 'T_motor_max', 'T_coolant_max',
    # -- regen torque signal (N.m) : Target Motor Torque is the correct channel --
    'target_torque_max', 'target_torque_min',
    # -- M128 (2026-08-17): CAP-DEPENDENT energy set, ADMITTED under two --
    #    corroborated verified:false assumptions (see header + CHANGELOG M128): --
    #    (1) shared 2.1 kWh pack (FWD == e-4ORCE; Nissan spec, ~1.8 kWh usable), --
    #    (2) SoC-anchored current-offset present on this rail with the SAME sign, --
    #        order of magnitude and duration-signature as the main rail's --
    #        (self-estimate -0.547 A, n=9, drive-bootstrap 95% CI [-0.70,-0.29]; --
    #        main-rail -0.4130 A lies inside that CI). --
    #    Energy (kWh):
    'gross_discharge_kwh', 'gross_charge_kwh', 'gross_throughput_kwh',
    'net_draw_kwh', 'net_draw_per100km', 'soc_delta_kwh', 'energy_residual_kwh',
    'charge_eng_on_kwh', 'charge_eng_off_kwh', 'charge_eng_only_kwh',
    'charge_dual_kwh', 'charge_pure_regen_kwh', 'charge_lowtq_engoff_kwh',
    #    Nameplate turnover (throughput / CAP) — inherits capKwhAssumed:
    'gtc', 'fce', 'cap_ah_est',
    #    Power (kW) — I*V, itself CAP-invariant, previously guard-blocked:
    'peak_discharge_kw', 'peak_charge_kw',
    'standstill_draw_kw', 'n_standstill_samples',
]

# M128: CAP-dependent columns DELIBERATELY admitted (see _ADMISSIBLE above and the
# master-level offset postprocess). The guard below still fires for ANY other
# CAP-dependent column, so an unvetted quantity cannot leak in by omission.
_CAP_ADMITTED = frozenset({
    'gross_discharge_kwh', 'gross_charge_kwh', 'gross_throughput_kwh',
    'net_draw_kwh', 'net_draw_per100km', 'soc_delta_kwh', 'energy_residual_kwh',
    'charge_eng_on_kwh', 'charge_eng_off_kwh', 'charge_eng_only_kwh',
    'charge_dual_kwh', 'charge_pure_regen_kwh', 'charge_lowtq_engoff_kwh',
    'gtc', 'fce', 'cap_ah_est',
    'peak_discharge_kw', 'peak_charge_kw', 'standstill_draw_kw', 'n_standstill_samples',
    # offset-corrected columns added at master level by _apply_soc_anchored_offset
    'I_offset_A_applied', 'offset_kwh_removed', 'net_draw_kwh_corr',
    'energy_residual_kwh_corr', 'net_draw_per100km_corr', 'implied_offset_A_drive',
})

# CAP-dependent guard: fires for any CAP-dependent pattern NOT explicitly admitted.
_CAP_FORBIDDEN = re.compile(
    r'kwh|_kw$|_kw_|^cap_|cap_ah|energy|\bgtc\b|rf_efc|throughput|net_draw'
    r'|standstill_draw', re.I)

# Master-level offset-derived columns (appended after per-drive projection).
_OFFSET_DERIVED = [
    'I_offset_A_applied', 'offset_kwh_removed', 'net_draw_kwh_corr',
    'energy_residual_kwh_corr', 'net_draw_per100km_corr', 'implied_offset_A_drive',
]


def _apply_soc_anchored_offset(out, verbose=True):
    """M128. Self-estimated SoC-anchored current-offset correction for the e-4ORCE
    rail, arithmetic IDENTICAL to compute_drive_summary_v6._v5_postprocess_master
    (M13/M24). The rail self-estimates its own global offset from its own drives
    (offset_source='soc_anchored_global'), exactly as the main rail does — no value
    is imported. Estimator (discharge-positive frame), anchored on the SoC ledger
    (soc_delta_kwh), which is independent of the current integral:
        I_off = sum(energy_residual_kwh)*1000 / (sum(h) * Vw)
    Only net_draw / residual are corrected; gross_* are NOT re-split (the offset
    shifts the sign boundary second-order for |I_off| << typical |I|). Recomputed
    every ingest, so the estimate refines as drives are added."""
    out = out.copy()
    m = (out['energy_residual_kwh'].notna() & out['duration_s'].notna()
         & out['V_pack_median'].notna())
    if 'integr_time_h' in out.columns and out.loc[m, 'integr_time_h'].notna().all():
        h = out.loc[m, 'integr_time_h']
    else:
        h = out.loc[m, 'duration_s'] / 3600.0
    Vw = float((out.loc[m, 'V_pack_median'] * h).sum() / h.sum())
    i_off = float(out.loc[m, 'energy_residual_kwh'].sum() * 1000.0 / (h.sum() * Vw))

    h_all = (out['integr_time_h'].fillna(out['duration_s'] / 3600.0)
             if 'integr_time_h' in out.columns else out['duration_s'] / 3600.0)
    off_kwh = i_off * out['V_pack_median'] * h_all / 1000.0
    out['I_offset_A_applied'] = np.where(m, round(i_off, 4), np.nan)
    out['offset_kwh_removed'] = off_kwh.round(4)
    out['net_draw_kwh_corr'] = (out['net_draw_kwh'] - off_kwh).round(4)
    out['energy_residual_kwh_corr'] = (out['energy_residual_kwh'] - off_kwh).round(4)
    dist_ok = out['distance_km'].fillna(0) > 0
    out['net_draw_per100km_corr'] = np.where(
        dist_ok & out['net_draw_kwh_corr'].notna(),
        (out['net_draw_kwh_corr'] / out['distance_km'] * 100).round(2), np.nan)
    out['implied_offset_A_drive'] = np.where(
        m & (h_all > 0.05),
        (out['energy_residual_kwh'] * 1000.0
         / (h_all * out['V_pack_median'])).round(3), np.nan)
    if verbose:
        print(f'  M128 offset (soc_anchored_global, self-estimate): '
              f'{i_off:+.4f} A  Vw={Vw:.1f} V  n={int(m.sum())}  '
              f'resid_corr_mean={out["energy_residual_kwh_corr"].mean():+.4f} kWh')
    return out


def _is_long_format(raw_bytes):
    head = raw_bytes[:400].lstrip(b'\xef\xbb\xbf').split(b'\n', 1)[0]
    return b'SECONDS' in head and b';' in head


def _date_from_name(fn):
    m = re.search(r'(\d{4})(\d{2})(\d{2})[_-](\d{2})(\d{2})(\d{2})', os.path.basename(fn))
    if not m:
        return None
    y, mo, d, hh, mm, ss = m.groups()
    return f'{y}-{mo}-{d}'


def _normalize_bytes(raw_bytes, filename):
    """Return WIDE-schema csv bytes. Wide input is returned unchanged; long input
    is pivoted to wide with canonical ``"{PID} ({UNITS})"`` column names and a
    synthesized ``time`` column (base_date + seconds-since-midnight)."""
    if not _is_long_format(raw_bytes):
        return raw_bytes
    base_date = _date_from_name(filename)
    df = pd.read_csv(io.BytesIO(raw_bytes), sep=';', engine='python',
                     usecols=[0, 1, 2, 3],
                     names=['SECONDS', 'PID', 'VALUE', 'UNITS'],
                     header=0, dtype=str)
    df = df.dropna(subset=['PID'])
    df['SECONDS'] = pd.to_numeric(df['SECONDS'], errors='coerce')
    df = df.dropna(subset=['SECONDS'])
    units = df['UNITS'].fillna('').str.strip()
    col = df['PID'].str.strip()
    df['col'] = np.where(units.ne(''), col + ' (' + units + ')', col)
    df['VALUE'] = pd.to_numeric(df['VALUE'], errors='coerce')
    wide = df.pivot_table(index='SECONDS', columns='col', values='VALUE',
                          aggfunc='mean').sort_index()
    t0 = pd.Timestamp(base_date) if base_date else pd.Timestamp('1970-01-01')
    wide.insert(0, 'time', t0 + pd.to_timedelta(wide.index.values, unit='s'))
    out = io.BytesIO()
    wide.to_csv(out, index=False)
    return out.getvalue()


def _load_ambient(ambient_csv):
    if not os.path.exists(ambient_csv):
        return {}
    a = pd.read_csv(ambient_csv, dtype={'file': str})
    return {str(r['file']): float(r['ambient_c']) for _, r in a.iterrows()}


def ingest(raw_dir=None, ambient_csv=None, out_csv=None, pattern='e4ORCE_*.csv',
           verbose=True):
    raw_dir = raw_dir or project_paths.raw_dir()
    ambient_csv = ambient_csv or os.path.join(_HERE, 'e4orce_ambient.csv')
    out_csv = out_csv or os.path.join(_HERE, 'e4orce_master.csv')

    v6 = _load_v6()
    ambient = _load_ambient(ambient_csv)
    files = sorted(glob.glob(os.path.join(raw_dir, pattern)))
    if not files:
        raise SystemExit(f'no e-4ORCE files matched {pattern} in {raw_dir}')

    rows = []
    for path in files:
        fn = os.path.basename(path)
        raw = open(path, 'rb').read()
        wide = _normalize_bytes(raw, fn)
        r = v6.analyze_bytes(wide, fn)

        # strict admissible projection
        row = {k: r.get(k) for k in _ADMISSIBLE}
        # CAP-dependency defect guard: still fires for any CAP-dependent column
        # NOT on the M128 explicitly-admitted list, so an unvetted CAP-dependent
        # quantity cannot leak in by omission.
        leaked = [k for k in row
                  if _CAP_FORBIDDEN.search(k) and k not in _CAP_ADMITTED]
        if leaked:
            raise AssertionError(f'CAP-dependent columns leaked into rail: {leaked}')

        # external ambient + derived pack-ambient offset (degC)
        amb = ambient.get(fn)
        row['ambient_c'] = amb
        row['fmt'] = 'long' if _is_long_format(raw) else 'wide'
        tp = row.get('T_pack_mean_avg')
        row['pack_minus_ambient_c'] = (round(float(tp) - amb, 1)
                                       if (amb is not None and tp is not None
                                           and not pd.isna(tp)) else None)
        rows.append(row)
        if verbose:
            print(f'  {fn:30s} fmt={row["fmt"]:4s} type={row.get("drive_type"):>13} '
                  f'vreg={row.get("vreg_R_pack_mohm")} vsag={row.get("vsag_R_pack_mohm")} '
                  f'amb={amb}')

    cols = ['file', 'fmt', 'date', 'drive_type', 'ambient_c',
            'pack_minus_ambient_c'] + \
           [c for c in _ADMISSIBLE if c not in ('file', 'date', 'drive_type')]
    out = pd.DataFrame(rows)[cols]

    # M128: master-level self-estimated SoC-anchored offset correction, then
    # append the offset-derived columns in canonical order.
    out = _apply_soc_anchored_offset(out, verbose=verbose)
    out = out[cols + _OFFSET_DERIVED]

    # segregation guard: this master must never contain a primary-corpus row
    assert out['file'].str.lower().str.startswith('e4orce').all(), \
        'non-e4ORCE row present in e4orce_master'

    out.to_csv(out_csv, index=False)
    if verbose:
        nv = out['vreg_R_pack_mohm'].notna().sum()
        ns = out['vsag_R_pack_mohm'].notna().sum()
        print(f'\nwrote {out_csv}: {len(out)} drives x {out.shape[1]} admissible cols')
        print(f'resistance coverage: vreg {nv}/{len(out)}, vsag {ns}/{len(out)}')
    return out


if __name__ == '__main__':
    ingest()
