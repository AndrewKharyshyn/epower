# per-drive native cadence (median dt of native samples) and rest-period current (speed==0, engine off, 1 Hz grid)
import sys, os, numpy as np, pandas as pd
from multiprocessing import Pool
sys.path.insert(0, os.path.dirname(__file__))
import a1_extract as X
def one(args):
    k, fn = args
    path = os.path.join(X.RAWDIR, fn)
    hdr = pd.read_csv(path, nrows=0).columns
    want = ['time'] + [v for v in X.C.values() if v in hdr]
    df = pd.read_csv(path, usecols=want, low_memory=False)
    t = X.parse_time(df['time'])
    spc = X.C['speedV'] if (X.C['speedV'] in df and pd.to_numeric(df[X.C['speedV']], errors='coerce').notna().sum() >= 20) else (X.C['speedO'] if X.C['speedO'] in df else X.C['speedV'])
    out = {'k': k}
    for nm, src in [('speed', spc), ('rpm', X.C['rpm']), ('I', X.C['I']), ('V', X.C['V'])]:
        if src not in df: out['dt_' + nm] = np.nan; continue
        s = pd.to_numeric(df[src], errors='coerce'); lo, hi = X.RNG[nm]
        ok = X.gated(s, lo, hi).notna() & t.notna()
        tt = np.sort(t[ok].values.astype('datetime64[ns]').astype('int64')) / 1e9
        dt = np.diff(tt); dt = dt[dt > 0]
        out['dt_' + nm] = float(np.median(dt)) if len(dt) else np.nan
        out['p90dt_' + nm] = float(np.percentile(dt, 90)) if len(dt) else np.nan
    # rest: grid seconds with speed==0 and rpm<=300 and I,V present
    g = pd.DataFrame({'t': t, 'speed': pd.to_numeric(df[spc], errors='coerce').ffill(limit=15) if spc in df else np.nan,
                      'rpm': pd.to_numeric(df[X.C['rpm']], errors='coerce').ffill(limit=15) if X.C['rpm'] in df else np.nan,
                      'I': pd.to_numeric(df[X.C['I']], errors='coerce').ffill(limit=15) if X.C['I'] in df else np.nan,
                      'V': pd.to_numeric(df[X.C['V']], errors='coerce').ffill(limit=15) if X.C['V'] in df else np.nan}).dropna(subset=['t']).set_index('t')
    hz = g.resample('1s').mean().ffill(limit=15)
    m = (hz.speed == 0) & (hz.rpm <= 300) & hz.I.notna() & hz.V.notna()
    out['rest_n'] = int(m.sum()); out['rest_I_mean'] = float(hz.I[m].mean()) if m.any() else np.nan; out['rest_I_med'] = float(hz.I[m].median()) if m.any() else np.nan
    # sign convention check: mean I during seconds with acceleration vs deceleration (engine off)
    sp = hz.speed.values; dv = np.diff(sp, prepend=sp[:1]); Iv = hz.I.values; ro = (hz.rpm.fillna(0).values <= 300)
    ok = ro & ~np.isnan(Iv) & ~np.isnan(dv)
    out['I_decel'] = float(np.nanmean(Iv[ok & (dv < -1)])) if (ok & (dv < -1)).any() else np.nan
    out['n_decel'] = int((ok & (dv < -1)).sum())
    out['I_accel'] = float(np.nanmean(Iv[ok & (dv > 1)])) if (ok & (dv > 1)).any() else np.nan
    out['n_accel'] = int((ok & (dv > 1)).sum())
    return out
if __name__ == '__main__':
    dm = pd.read_csv(os.path.join(X.REPO, 'drive_master.csv'), encoding='utf-8')
    with Pool(4) as p:
        r = p.map(one, list(enumerate(dm.file)), chunksize=4)
    pd.DataFrame(r).to_pickle(sys.argv[1]); print('ok')
