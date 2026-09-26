"""
c1_joint_temp_crate.py -- Audit C1 remediation probe.

The current cRatePoints chart (compute_summary_arrays.py) pairs each drive's
T1_peak (max battery temp ANYWHERE in the drive) with that drive's peak
charge C-rate (max ANYWHERE in the drive, across regen/eng_charge/dual
channels) -- these need not be simultaneous. Both HV Battery Current and HV
Battery Temperature Sensor 1 are logged on native timestamps in every raw
CSV, so a genuinely time-aligned pairing IS computable: for each channel's
peak-current sample, look up the SIMULTANEOUS T1 (asof, 3s tolerance --
the same convention the pipeline already uses to align engine-state/speed
onto the current time base).

Reproduces the pipeline's own alignment/masking logic (V_ALIGN_TOL=1500ms,
ENG_ALIGN_TOL=3s, eng_on = eng_rpm>400, regen = eng_off & Id<-30,
eng_charge = eng_on & Id<-50, dual = eng_on & target_torque<-15 & Id<-10)
so the peak-A / C-rate figures match compute_drive_summary_v6.py exactly;
only the temperature pairing changes.

Output: per-drive, per-channel comparison of T1_peak (existing,
non-simultaneous) vs T1_at_peak (new, simultaneous).
"""
import io
import sys
import time
import pandas as pd
import numpy as np

RAW_DIR = "/mnt/project"
MASTER = "/mnt/project/drive_master.csv"
CAP_KWH = 2.1

COL_MAP = {
    '[BMS] HV Battery Current (A)': 'I',
    '[BMS] HV Battery voltage (V)': 'V',
    '[BMS] HV Battery Temperature Sensor 1 (\u2103)': 'T1',
    '[VCM] Vehicle Speed (km/h)': 'speed',
    '[VCM] Target Motor Torque (N\u22c5m)': 'target_torque',
}

V_TOL = pd.Timedelta('1500ms')   # I<->V, matches V_ALIGN_TOL
E_TOL = pd.Timedelta('3s')       # engine-state / temperature alignment, matches ENG_ALIGN_TOL


def _series(df, t, col, lo=None, hi=None):
    if col not in df.columns:
        return None
    m = df[col].notna()
    if not m.any():
        return None
    s = pd.DataFrame({'t': t[m].values, 'v': df.loc[m, col].astype(float).values})
    if lo is not None:
        s = s[s['v'] >= lo]
    if hi is not None:
        s = s[s['v'] <= hi]
    s = s.sort_values('t').reset_index(drop=True)
    return s if len(s) else None


def _asof_nearest(base_t, other, tol, name='v'):
    if other is None or len(other) == 0:
        return pd.Series([np.nan] * len(base_t))
    b = pd.DataFrame({'t': base_t}).reset_index(drop=True)
    m = pd.merge_asof(b, other[['t', 'v']].rename(columns={'v': name}).sort_values('t'),
                       on='t', direction='nearest', tolerance=tol)
    return m[name]


def process_one(path, fname):
    with open(path, 'rb') as f:
        csv_bytes = f.read()
    df = pd.read_csv(io.BytesIO(csv_bytes), low_memory=False)
    eng_col = None
    for c in df.columns:
        cl = c.lower()
        if 'rpm' in cl and 'motor' not in cl and 'x1000' not in cl and '[vcm]' not in cl:
            eng_col = c
            break
    rename = {k: v for k, v in COL_MAP.items() if k in df.columns}
    if eng_col:
        rename[eng_col] = 'eng_rpm'
    df = df.rename(columns=rename)
    if 'I' not in df.columns or 'T1' not in df.columns or 'V' not in df.columns:
        return None
    t = pd.to_datetime(df['time'], format='mixed', errors='coerce')

    I = _series(df, t, 'I')
    if I is None:
        return None
    I = I[I['v'].abs() < 900]
    V = _series(df, t, 'V', lo=200, hi=450)
    T1 = _series(df, t, 'T1', lo=-40, hi=90)
    eng = _series(df, t, 'eng_rpm', lo=0) if 'eng_rpm' in df.columns else None
    tq = _series(df, t, 'target_torque') if 'target_torque' in df.columns else None

    if T1 is None or V is None or len(I) == 0:
        return None

    e = I.copy()
    e = pd.merge_asof(e, V.rename(columns={'v': 'V'}), on='t',
                       direction='nearest', tolerance=V_TOL).dropna(subset=['V'])
    # BUGFIX: dropna() leaves a non-contiguous index; _asof_nearest() below
    # rebuilds its own base frame with reset_index(drop=True), so assigning
    # its result back onto `e` by pandas' label-based Series alignment
    # silently scrambles rows whenever e's index has gaps. Re-flatten to a
    # clean 0..n-1 RangeIndex so every subsequent column assignment is
    # positional, not label-matched.
    e = e.reset_index(drop=True)
    if len(e) < 2:
        return None
    e['Id'] = -e['v']   # discharge-positive (M11)
    e['eng_rpm'] = _asof_nearest(e['t'], eng, E_TOL, 'eng_rpm') if eng is not None else np.nan
    e['eng_on'] = e['eng_rpm'].fillna(0) > 400
    e['target_torque'] = _asof_nearest(e['t'], tq, V_TOL, 'target_torque') if tq is not None else np.nan
    e['T1_now'] = _asof_nearest(e['t'], T1, E_TOL, 'T1_now')

    v_nom = float(e['V'].median())
    cap_ah = CAP_KWH * 1000.0 / v_nom

    out = {'file': fname, 'T1_peak_drive': round(float(T1['v'].max()), 1),
           'cap_ah': round(cap_ah, 2)}

    regen = e[(~e['eng_on']) & (e['Id'] < -30)]
    eng_chg = e[(e['eng_on']) & (e['Id'] < -50)]
    tq_regen = e['target_torque'].fillna(0) < -15
    dual = e[(e['eng_on']) & tq_regen & (e['Id'] < -10)]

    for label, sub in [('regen', regen), ('eng_charge', eng_chg), ('dual', dual)]:
        if len(sub) and sub['Id'].notna().any():
            idx = sub['Id'].idxmin()
            peak_A = float(-sub.loc[idx, 'Id'])
            t1_simul = sub.loc[idx, 'T1_now']
            out[f'{label}_peak_A'] = round(peak_A, 1)
            out[f'{label}_peak_Crate'] = round(peak_A / cap_ah, 1)
            out[f'{label}_T1_at_peak'] = round(float(t1_simul), 1) if pd.notna(t1_simul) else None
        else:
            out[f'{label}_peak_A'] = None
            out[f'{label}_peak_Crate'] = None
            out[f'{label}_T1_at_peak'] = None

    return out


def main():
    dm = pd.read_csv(MASTER, low_memory=False)
    files = dm['file'].dropna().unique().tolist()
    rows = []
    t0 = time.time()
    n_ok, n_skip = 0, 0
    for i, fname in enumerate(files):
        path = f"{RAW_DIR}/{fname}"
        try:
            r = process_one(path, fname)
        except FileNotFoundError:
            r = None
        except Exception as ex:
            r = None
            print(f"  ERR {fname}: {ex}", file=sys.stderr)
        if r is None:
            n_skip += 1
            continue
        rows.append(r)
        n_ok += 1
        if (i + 1) % 50 == 0:
            print(f"  ...{i+1}/{len(files)} ({time.time()-t0:.0f}s)", file=sys.stderr)
    print(f"done: {n_ok} ok, {n_skip} skipped, {time.time()-t0:.0f}s", file=sys.stderr)
    out = pd.DataFrame(rows)
    out.to_csv("/home/claude/work/c1_joint_temp_crate_results.csv", index=False)


if __name__ == "__main__":
    main()
