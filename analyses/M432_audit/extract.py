"""Independent per-drive variant extraction for the M432 detector-sensitivity audit.
Reuses ONLY released _prep_bytes and _series (grid/speed construction). Own debounce, own alignment loop, own validity."""
import sys, os, pickle
import numpy as np, pandas as pd
from multiprocessing import Pool
REPO = r'C:\Users\AndriiKharyshyn\Downloads\X-Trail Investigation\Repo\xtrail-repo'
sys.path.insert(0, REPO)
import compute_drive_summary_v6 as V6

TS = [100, 200, 400, 800]
BS = [0, 2, 3, 5, 10]
# alignment keys: (direction, tolerance seconds)
ALIGNS = [('nearest', 0.5), ('nearest', 1.0), ('nearest', 1.5), ('nearest', 3.0),
          ('backward', 2.0), ('backward', 3.0), ('backward', 6.0),
          ('forward', 2.0), ('forward', 3.0), ('forward', 6.0)]


def debounce(state, n):
    """state: bool ndarray. Replace each run shorter than n samples by the (already resolved) previous state; first run exempt."""
    s = state.astype(np.int8).copy()
    if n <= 1 or len(s) == 0:
        return s.astype(bool)
    chg = np.flatnonzero(np.diff(s)) + 1
    starts = np.r_[0, chg]
    ends = np.r_[chg, len(s)]
    orig_len = ends - starts
    if not ((orig_len < n) & (starts > 0)).any():
        return s.astype(bool)
    cur = s[0]
    out = s.copy()
    for a, b in zip(starts, ends):
        if a == 0:
            cur = s[0]
        elif (b - a) < n:
            out[a:b] = cur
        else:
            cur = s[a]
    return out.astype(bool)


def one(file):
    path = os.path.join(REPO, 'raw_only', file)
    with open(path, 'rb') as fh:
        b = fh.read()
    res = {'file': file, 'ok': False}
    df, t = V6._prep_bytes(b)
    eng = V6._series(df, t, 'eng_rpm', lo=0)
    spd = V6._series(df, t, 'speed', lo=0, hi=260)
    if spd is None or len(spd) < 20:
        spd = V6._series(df, t, 'speed_obd', lo=0, hi=260)
    if eng is None or spd is None or len(eng) < 20:
        return res
    tv = t.dropna()
    if len(tv) < 10:
        return res
    grid = pd.DataFrame({'t': pd.date_range(tv.min(), tv.max(), freq='1s')})
    if len(grid) < 10:
        return res
    tol3 = pd.Timedelta('3s')
    g = pd.merge_asof(grid, spd.rename(columns={'v': 'speed'}), on='t', direction='nearest', tolerance=tol3)
    res['cov_speed'] = round(float(g['speed'].notna().mean()), 4)
    res['dt_med'] = round(float(eng['t'].diff().dt.total_seconds().median()), 2)
    v = g['speed'].fillna(0.0).values
    dkm = v / 3600.0
    dist_int = float(dkm.sum())
    odo = V6._series(df, t, 'odo')
    dist_odo = float(odo['v'].max() - odo['v'].min()) if odo is not None and len(odo) else np.nan
    k = dist_odo / dist_int if (dist_int > 0 and np.isfinite(dist_odo) and dist_odo > 0) else np.nan
    kk = k if np.isfinite(k) else 1.0
    res.update(dist_odo=dist_odo, k=float(k) if np.isfinite(k) else np.nan, ngrid=len(g))
    res['base_ok'] = bool(np.isfinite(dist_odo) and dist_odo >= 1.0 and np.isfinite(k)
                          and 0.90 <= k <= 1.10 and res['dt_med'] <= 2.0)
    dist = {}
    cov = {}
    engs = eng.sort_values('t')
    rp = {}
    for (d, a) in ALIGNS:
        gg = pd.merge_asof(grid, engs.rename(columns={'v': 'rpm'}), on='t', direction=d,
                           tolerance=pd.Timedelta(seconds=a))
        rpm = gg['rpm'].values
        rp[(d, a)] = rpm
        known = ~np.isnan(rpm)
        cov[(d, a)] = round(float(known.mean()), 4)
        for T in TS:
            st = known & (np.where(known, rpm, 1e9) <= T)
            for B in BS:
                off = debounce(st, B) & known
                dist[(d, a, T, B)] = round(float(dkm[off].sum()) * kk, 3)
    res['cov'] = cov
    res['dist'] = dist
    # --- review extras at released alignment ---
    rpm0 = rp[('nearest', 3.0)]
    known0 = ~np.isnan(rpm0)
    ex = {'ngrid': len(g), 'unk': int((~known0).sum())}
    bands = {'le100': (-1, 100), 'b100_200': (100, 200), 'b200_400': (200, 400),
             'b400_800': (400, 800), 'gt800': (800, 1e9)}
    for nm, (lo, hi) in bands.items():
        m = known0 & (rpm0 > lo) & (rpm0 <= hi)
        ex['s_' + nm] = int(m.sum())
        ex['km_' + nm] = float(dkm[m].sum()) * kk
        ex['mov_' + nm] = int((m & (v >= 1.0)).sum())
    band = known0 & (rpm0 > 100) & (rpm0 <= 800)
    rl = {}
    if band.any():
        chg = np.flatnonzero(np.diff(band.astype(np.int8))) + 1
        for a_, b_ in zip(np.r_[0, chg], np.r_[chg, len(band)]):
            if band[a_]:
                L = b_ - a_
                c = '1-2' if L <= 2 else ('3-5' if L <= 5 else ('6-10' if L <= 10 else '>10'))
                rl[c] = rl.get(c, 0) + L
    ex['band_runlen_s'] = rl
    x = eng['v'].values
    tt = eng['t'].values
    nb = (x > 100) & (x <= 800)
    ex['nat_n'] = len(x)
    ex['nat_band'] = int(nb.sum())
    ex['nat_le100'] = int((x <= 100).sum())
    ex['nat_gt800'] = int((x > 800).sum())
    ctx = {}
    if nb.any():
        chg = np.flatnonzero(np.diff(nb.astype(np.int8))) + 1
        for a_, b_ in zip(np.r_[0, chg], np.r_[chg, len(nb)]):
            if not nb[a_]:
                continue
            L = b_ - a_
            prv = x[a_ - 1] if a_ > 0 else None
            nxt = x[b_] if b_ < len(x) else None
            if prv is None or nxt is None:
                c = 'edge'
            else:
                pl = 'low' if prv <= 100 else 'high'
                nl = 'low' if nxt <= 100 else 'high'
                c = {('low', 'high'): 'start(low>high)', ('high', 'low'): 'stop(high>low)',
                     ('low', 'low'): 'blip(low-low)', ('high', 'high'): 'dip(high-high)'}[(pl, nl)]
            lc = '1' if L == 1 else ('2' if L == 2 else ('3-4' if L <= 4 else '>=5'))
            ctx[(c, lc)] = ctx.get((c, lc), 0) + L
    ex['nat_ctx'] = ctx
    ex['nat_hist'] = (np.histogram(x[nb], bins=[100, 150, 200, 250, 300, 350, 400, 500, 600, 700, 800])[0].tolist()
                      if nb.any() else [0] * 10)
    nt = tt.astype('datetime64[ns]').astype(np.int64) / 1e9
    gt = grid['t'].values.astype('datetime64[ns]').astype(np.int64) / 1e9
    idx = np.clip(np.searchsorted(nt, gt), 1, len(nt) - 1)
    dn = np.minimum(np.abs(gt - nt[idx]), np.abs(gt - nt[idx - 1]))
    ex['band_sec_dist_gt05'] = int((band & (dn > 0.5)).sum())
    ex['band_sec_dist_gt1'] = int((band & (dn > 1.0)).sum())
    res['ex'] = ex
    res['ok'] = True
    return res


if __name__ == '__main__':
    dm = pd.read_csv(os.path.join(REPO, 'drive_master.csv'), low_memory=False)
    files = dm['file'].tolist()
    with Pool(4) as p:
        out = p.map(one, files, chunksize=4)
    with open(os.path.join(REPO, 'analyses', 'M432_audit', 'extract.pkl'), 'wb') as fh:
        pickle.dump(out, fh)
    print('done', sum(o['ok'] for o in out), len(out))
