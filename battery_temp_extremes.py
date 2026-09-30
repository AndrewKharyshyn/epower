"""
battery_temp_extremes.py -- M255 additive side-pass for two new Dataset
Extremes rows: "Battery temp min" and "Battery intake air temperature min".

drive_master.csv carries only per-drive MAXIMA for the four pack-temperature
sensors (T1_peak..T4_peak) and no per-drive minimum at all for either the
pack sensors or the intake-air channel -- so, unlike every other row in
_records(), these two cannot be computed from already-logged master columns.
Rather than add columns to drive_master.csv (the corpus-integrity anchor;
any change there requires the full ingestion/validation chain, out of scope
for a two-row display addition), this is a read-only raw pass over the
canonical raw CSVs, following the same "additive side-module, master
untouched" pattern as fuel_recon.py.

Method: for each of the 374 canonical drives (from drive_master.csv['file']),
read only the 4 pack-sensor + 1 intake-air columns, apply an artefact floor
(FLOOR=-40 degC) to drop a stuck-sensor sentinel (-100 degC was observed
repeatedly on the intake-air channel across many drives -- clearly a
dropout/no-data value, not real cold-air readings) then take the row-wise
minimum across the 4 pack sensors (mirroring the row-wise-MAX convention
already used for "Battery temp max"/tbatt in _records()) and, separately,
the per-drive minimum of the intake-air channel. The corpus-wide minimum of
each per-drive series is the reported extremum, attributed to its setting
drive via the pipeline's own _day_label()/_ctx() so the note text is
generated exactly like every other row, not hand-typed.

Output: battery_temp_extremes.csv (per-drive pack_min/pack_min_sensor/
intake_min -- the reproducible artifact) plus the two record dicts, ready to
splice into summary_arrays.json['records'] (see splice_battery_temp_extremes.py).
"""
import pandas as pd, numpy as np, sys, os

# NOTE: importing compute_summary_arrays.py directly pulls in its full heavy
# dependency chain (statsmodels/sklearn/etc., not needed for this side-pass).
# _day_label/_ctx/_CTX_FIELDS are reproduced verbatim from compute_summary_arrays.py
# (lines 1157-1197 at the time of writing) rather than imported, to keep this
# script dependency-light; the logic is copied, not reinvented.

def _day_label(dm, idx):
    if idx is None or idx not in dm.index:
        return None
    row = dm.loc[idx]
    d = row.get('date')
    if d is None or (isinstance(d, float) and pd.isna(d)):
        return None
    try:
        day_rows = dm[dm['date'] == d].sort_values('time_start')
        ordinal = list(day_rows.index).index(idx) + 1
        label = pd.to_datetime(d).strftime('%b%d')
        return f"{label} D{ordinal}"
    except Exception:
        return str(d)


_CTX_FIELDS = {
    'class':  (('drive_type',),
               lambda r: (None if pd.isna(r['drive_type'])
                          or str(r['drive_type']) == 'unknown'
                          else str(r['drive_type']).replace('_', '-'))),
    'trip':   (('distance_km', 'duration_s'),
               lambda r: f"{r['distance_km']:.1f} km / {r['duration_s'] / 60:.0f} min"),
    'pack':   (('T_pack_mean_max',),
               lambda r: f"pack mean {r['T_pack_mean_max']:.0f}\u00b0C"),
}


def _ctx(dm, idx, keys):
    if idx is None or idx not in dm.index:
        return ''
    row = dm.loc[idx]
    frags = []
    for k in keys:
        spec = _CTX_FIELDS.get(k)
        if spec is None:
            continue
        cols, fmt = spec
        if any(c not in dm.columns or pd.isna(row.get(c)) for c in cols):
            continue
        try:
            s = fmt(row)
        except Exception:
            continue
        if s:
            frags.append(s)
    return ' \u00b7 '.join(frags)


FLOOR = -40.0
SENSOR_COLS = [f'[BMS] HV Battery Temperature Sensor {i} (\u2103)' for i in range(1, 5)]
INTAKE_COL = '[BMS] HV Battery Intake Air Temperature (\u2103)'


def raw_pass(dm, raw_dir):
    rows = []
    for f in dm['file']:
        path = os.path.join(raw_dir, f)
        df = pd.read_csv(path, usecols=lambda c: c in SENSOR_COLS or c == INTAKE_COL)
        present = [c for c in SENSOR_COLS if c in df.columns]
        pack = df[present].where(df[present] >= FLOOR) if present else pd.DataFrame()
        pack_min, pack_min_sensor = np.nan, None
        if len(pack.columns) and pack.notna().any().any():
            rowmin = pack.min(axis=1)
            ridx = rowmin.idxmin()
            pack_min = float(rowmin.loc[ridx])
            pack_min_sensor = int(pack.loc[ridx].idxmin()[len('[BMS] HV Battery Temperature Sensor ')])
        intake_s = df[INTAKE_COL].where(df[INTAKE_COL] >= FLOOR) if INTAKE_COL in df.columns else pd.Series(dtype=float)
        intake_min = float(intake_s.min()) if intake_s.notna().any() else np.nan
        rows.append((f, pack_min, pack_min_sensor, intake_min))
    return pd.DataFrame(rows, columns=['file', 'pack_min', 'pack_min_sensor', 'intake_min'])


def build_records(dm, res):
    file_to_idx = {row['file']: idx for idx, row in dm.iterrows()}

    out = {}
    # ---- Battery temp min ----
    sub = res.dropna(subset=['pack_min'])
    if len(sub):
        w = sub.loc[sub['pack_min'].idxmin()]
        idx = file_to_idx.get(w['file'])
        drive = _day_label(dm, idx) if idx is not None else None
        ctx = _ctx(dm, idx, ('class', 'trip', 'pack')) if idx is not None else ''
        why = ('Coldest single pack probe in the dataset (row-wise min over sensors '
               '1-4, mirroring the M32 true-maximum convention). Marks the coldest '
               'state the cells have been observed in \u2014 the starting point for '
               'internal resistance and available power at a cold start.')
        rec = {'metric': 'Battery temp min', 'value': f"{w['pack_min']:.0f}\u00b0C",
               'drive': drive or ''}
        rec['note'] = f"{why} Set on: {ctx}." if ctx else why
        if w['pack_min_sensor'] is not None and not pd.isna(w['pack_min_sensor']):
            rec['sensor'] = int(w['pack_min_sensor'])
        out['Battery temp min'] = rec

    # ---- Battery intake air temperature min ----
    sub2 = res.dropna(subset=['intake_min'])
    if len(sub2):
        w2 = sub2.loc[sub2['intake_min'].idxmin()]
        idx2 = file_to_idx.get(w2['file'])
        drive2 = _day_label(dm, idx2) if idx2 is not None else None
        ctx2 = _ctx(dm, idx2, ('class', 'trip', 'pack')) if idx2 is not None else ''
        why2 = ('Coldest cabin-sourced cooling air presented to the pack inlet on '
                'this dataset\u2019s coldest mornings \u2014 the counterpart to the '
                'intake-air maximum above, and the low end of the range the pack\u2019s '
                'passive thermal environment has to work with.')
        rec2 = {'metric': 'Battery intake air temperature min',
                'value': f"{w2['intake_min']:.1f}\u00b0C", 'drive': drive2 or ''}
        rec2['note'] = f"{why2} Set on: {ctx2}." if ctx2 else why2
        out['Battery intake air temperature min'] = rec2

    return out


if __name__ == '__main__':
    dm = pd.read_csv('drive_master.csv')
    import os
    res = raw_pass(dm, os.environ.get('XT_RAW_DIR') or '/mnt/project')   # M308: env-aware (unset -> legacy path, unchanged behaviour)
    res.to_csv('battery_temp_extremes.csv', index=False)
    recs = build_records(dm, res)
    import json
    print(json.dumps(recs, indent=2, ensure_ascii=False))
