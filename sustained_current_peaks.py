#!/usr/bin/env python3
"""
sustained_current_peaks.py  (M283, 2026-09-17)

Persistent generator for the rolling-window sustained pack-current peaks
(discharge AND charge), 1/5/10/30 s.  This artifact previously existed only as
`sustained_current_peaks.csv` with NO surviving generating code (the same
lost-code failure class the M279-M282 track was created to end); the M273
sustained-DISCHARGE record shipped from it, but the sustained-CHARGE side was
deferred because an *ungated* raw pass surfaces physically-impossible >1000 A
charge spikes on 9 drives (single-sample logging artifacts).  This script
closes that deferral by mirroring the main pipeline's per-sample artifact gate.

METHOD (mirrors compute_drive_summary_v6._v5_analyze_bytes exactly):
  - current PID  '[BMS] HV Battery Current (A)'  (charge-positive convention)
  - PER-SAMPLE ARTIFACT GATE:  keep only |I| < 900 A   (the master's own gate,
    compute_drive_summary_v6.py line ~539 `I = I[I['v'].abs() < 900]`)
  - discharge-positive  Id = -I_raw
  - resample('1s').mean().interpolate()  then rolling(N, min_periods=N).mean().max()
    (interpolate() — NOT ffill — is the shipped fill: it uniquely reproduces the
     M273 discharge 5 s record-setter 173.4 A on the ~2 Hz drive 20260705_122016;
     ffill gives 175.3.)
  - C-rate = amperes / cap_ah, cap_ah = CAP_KWH*1000/v_nom per drive (measured
    nominal voltage); CAP_KWH = 2.1 kWh is UNVERIFIED (label carried in the record).

Drive set = the 396 current-carrying drives (master peak_I_discharge notna),
derived self-consistently from drive_master.csv (no dependence on the old CSV).

HARD GATE: the discharge corpus maxima MUST reproduce the shipped M273 record
(205.1 / 173.4 / 145.1 / 82.7 A) byte-exact, or the script aborts.  This proves
the method is faithful before any charge figure is trusted.

Outputs: rewrites sustained_current_peaks.csv (gated, both sides, one consistent
method) and prints the sustained-charge corpus record for the summary_arrays splice.
"""
import sys, os
import pandas as pd
import numpy as np

CSVDIR   = os.environ.get('CSVDIR', '/mnt/project')
MASTER   = os.path.join(CSVDIR, 'drive_master.csv')
CUR_COL  = '[BMS] HV Battery Current (A)'
GATE_A   = 900.0          # |I| >= 900 A -> logging artifact (master gate)
CAP_KWH  = 2.1            # UNVERIFIED pack capacity assumption
WINDOWS  = (1, 5, 10, 30)
# shipped M273 sustained-discharge record (corpus maxima) — reproduction gate
DIS_GOLD = {1: 205.1, 5: 173.4, 10: 145.1, 30: 82.7}


def _load_current(fn):
    """Raw current series on native timestamps, per-sample artifact-gated."""
    df = pd.read_csv(os.path.join(CSVDIR, fn), low_memory=False)
    tcol = 'time' if 'time' in df.columns else df.columns[0]
    t = pd.to_datetime(df[tcol], format='mixed', errors='coerce')
    if CUR_COL not in df.columns:
        return None
    m = df[CUR_COL].notna()
    s = pd.DataFrame({'t': t[m].values, 'v': df.loc[m, CUR_COL].astype(float).values})
    s = s[s['v'].abs() < GATE_A]                 # <-- the gate
    s = s.sort_values('t').reset_index(drop=True)
    return s if len(s) >= 2 else None


def _rollmax(series_1hz, n):
    r = series_1hz.rolling(n, min_periods=n).mean().max()
    return round(float(r), 1) if pd.notna(r) else np.nan


def _one(fn, v_nom):
    s = _load_current(fn)
    if s is None:
        return None
    idx = s['t']
    Id  = pd.Series((-s['v']).values, index=idx).resample('1s').mean().interpolate()   # discharge+
    Ic  = pd.Series(( s['v']).values, index=idx).resample('1s').mean().interpolate()   # charge+ (BMS +)
    row = {'file': fn}
    for n in WINDOWS:
        row['dis_%ds' % n] = _rollmax(Id, n)
        row['chg_%ds' % n] = _rollmax(Ic, n)
    row['cap_ah_est'] = round(CAP_KWH * 1000.0 / v_nom, 2) if v_nom and v_nom > 0 else np.nan
    return row


def main():
    dm = pd.read_csv(MASTER, low_memory=False)
    fleet = dm.loc[dm['peak_I_discharge'].notna(), ['file', 'V_pack_median']].copy()
    print('current-carrying drives: %d' % len(fleet))

    rows = []
    for _, r in fleet.iterrows():
        o = _one(r['file'], r['V_pack_median'])
        if o:
            rows.append(o)
    out = pd.DataFrame(rows)
    cols = (['file'] + [c for n in WINDOWS for c in ('dis_%ds' % n, 'chg_%ds' % n)] + ['cap_ah_est'])
    out = out[cols]

    # ---- HARD GATE: discharge corpus maxima must reproduce the shipped M273 record ----
    ok = True
    for n in WINDOWS:
        got = out['dis_%ds' % n].max()
        want = DIS_GOLD[n]
        good = (got == got) and abs(got - want) < 0.05          # nan-safe
        ok &= good
        print('  dis_%2ds corpus max = %6.1f A  (M273 gold %6.1f)  %s'
              % (n, got, want, 'OK' if good else 'MISMATCH'))
    if not ok:
        print('ABORT: discharge reproduction gate failed — method not faithful.', file=sys.stderr)
        sys.exit(1)

    # ---- sustained-CHARGE corpus record (the deliverable) ----
    print('\n=== SUSTAINED CHARGE PEAKS (gated |I|<900 A) ===')
    setters = {}
    for n in WINDOWS:
        c = 'chg_%ds' % n
        i = out[c].idxmax()
        fn = out.loc[i, 'file']
        cap = out.loc[i, 'cap_ah_est']
        A = out.loc[i, c]
        setters[n] = (fn, A, cap, A / cap)
        print('  %2ds: %6.1f A  %5.1fC   set on %-24s (cap_ah %.3f)'
              % (n, A, A / cap, fn, cap))

    out.to_csv('sustained_current_peaks.csv', index=False)
    print('\nwrote sustained_current_peaks.csv  (%d rows, gated, interpolate fill)' % len(out))
    return out, setters


if __name__ == '__main__':
    main()
