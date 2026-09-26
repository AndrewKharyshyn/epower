#!/usr/bin/env python3
"""kpi_ci3_extract.py (M285d): one pass over the raw frame cache extracting, per drive, the components of the five Compare KPIs that
carry no interval yet: EnergyShifting net kW (5-15 km/h pooled median), CellSpreadRelaxation loaded spread + half-time (per rest window),
HandoffSequence boost involvement (counts), HighSocRegen engine-on / non-decelerating shares (counts). Extraction loops are transcribed
from compute_summary_arrays.py (_energy_shifting, _cell_spread_relaxation, _handoff_sequence, _high_soc_regen) and are validated against the
shipped values by kpi_ci3_splice.py before any interval is written."""
import sys, os, pickle
sys.path.insert(0, os.environ.get('XT_CODE', '/home/claude/work/code'))
import numpy as np, pandas as pd
import compute_summary_arrays as C
import drive_raw_cache as D
RAW = os.environ.get('XT_RAW', '/home/claude/work/raw')
FL = D.make_frame_loader(os.environ.get('XT_CACHE', '/home/claude/work/raw_cache'))
def raw_loader(fn):
    with open(os.path.join(RAW, fn), 'rb') as fh: return fh.read()
dm = pd.read_csv(sys.argv[1]); out_p = sys.argv[2]
lo_bin = [i for i in range(len(C._ESH_SPEED_EDGES) - 1) if C._ESH_SPEED_EDGES[i] == 5][0]
res = {}
for _, r in dm.iterrows():
    fn = r['file']; day = str(r.get('date', ''))[:10]; rec = {'day': day}
    # --- EnergyShifting (net kW, 5-15 km/h bin)
    try:
        g = C._esh_grid(fn, raw_loader, FL)
    except Exception:
        g = None
    if g is not None:
        g = g.dropna(subset=['speed'])
        if len(g) >= 30:
            sb = np.digitize(g['speed'].values, C._ESH_SPEED_EDGES[1:-1])
            pdis = (((-g['I']) * g['V'] / 1000.0).values if 'I' in g.columns and 'V' in g.columns else None)
            m = sb == lo_bin
            rec['esh_covered'] = True
            rec['esh_net'] = (pdis[m][np.isfinite(pdis[m])].astype(np.float32) if (pdis is not None and m.sum() >= 3) else np.array([], np.float32))
    # --- CellSpreadRelaxation
    fr = FL(fn)
    g = C._csr_grid(fr)
    win = []
    if g is not None and 'I' in g.columns:
        g = g.dropna(subset=['maxv', 'minv', 'I'])
        if len(g) >= 30:
            rec['csr_covered'] = True
            spread = (g['maxv'] - g['minv']).values * 1000.0
            cur = g['I'].abs().values
            resting = cur < C._CSR_REST_I
            i = 0; n = len(resting)
            while i < n:
                if resting[i]:
                    j = i
                    while j < n and resting[j]: j += 1
                    if j - i >= C._CSR_MIN_REST_S:
                        pre0 = max(0, i - C._CSR_PRELOAD_S)
                        if i - pre0 >= 2 and np.nanmean(cur[pre0:i]) >= C._CSR_LOAD_I:
                            seg = spread[i:j]
                            if np.isfinite(seg).sum() >= 5:
                                s_onset = float(np.nanmean(spread[max(0, i - 1):i + 1]))
                                s_asym = float(np.nanmedian(seg[-min(5, len(seg)):]))
                                mg = s_onset - s_asym
                                hf = np.nan
                                if mg > 1.0:
                                    hit = np.where(seg <= s_onset - 0.5 * mg)[0]
                                    if len(hit): hf = float(hit[0])
                                win.append((s_onset, hf))
                    i = j
                else:
                    i += 1
    rec['csr'] = win
    # --- HandoffSequence
    ev = C._handoff_sequence_events(fr)
    if ev:
        rec['ho_n'] = len(ev)
        rec['ho_boost'] = sum(1 for e in ev if e.get('boostOnsetLagS') is not None)
    # --- HighSocRegen shares
    g, used_fb = C._hr_grid(fr)
    if g is not None and 'soc' in g.columns:
        g = g.dropna(subset=['I', 'V', 'soc'])
        if len(g) >= 20:
            chg = (g['I'] * g['V'] / 1000.0).values
            m = (chg > C._HR_MIN_CHG_KW) & (chg < C._HR_CAP_KW)
            if m.any():
                rpm = g['rpm'].values if 'rpm' in g.columns else np.full(len(g), np.nan)
                speed = g['speed'].values if 'speed' in g.columns else np.full(len(g), np.nan)
                v_prev = np.concatenate([speed[:1], speed[:-1]]); decel = v_prev - speed
                eng_off = np.nan_to_num(rpm, nan=9999.0) <= 300
                dec = np.nan_to_num(decel, nan=-1.0) > 0
                rec['hr_n'] = int(m.sum()); rec['hr_eng_on'] = int((~eng_off[m]).sum()); rec['hr_nondec'] = int((~dec[m]).sum())
    res[fn] = rec
pickle.dump(res, open(out_p, 'wb'))
print('extracted', len(res))
