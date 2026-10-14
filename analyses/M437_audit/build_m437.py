"""M437 blind audit step 1: per-drive records for forward-fill limits F in {0,3,6} from raw_only/ and the spec rules only.
Also: event-second-filled flag, raw sample counts, valid-span, raw sample intervals.
Usage: python -X utf8 build_m437.py <repo_root> <out_csv> <out_intervals_npz>"""
import sys, os
import numpy as np, pandas as pd
from multiprocessing import Pool

ROOT, OUT, OUTI = sys.argv[1], sys.argv[2], sys.argv[3]
COOL = '\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 \u043e\u0445\u043e\u043b\u043e\u0434\u043d\u043e\u0457 \u0440\u0456\u0434\u0438\u043d\u0438 (\u2103)'
OIL = '\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 \u043e\u043b\u0456\u0457 \u0443 \u0434\u0432\u0438\u0433\u0443\u043d\u0456 (\u2103)'
FS = (0, 3, 6)

def parse_time(s):
    try:
        return pd.to_datetime(s, format='%H:%M:%S.%f', errors='raise')
    except (ValueError, TypeError):
        return pd.to_datetime(s, format='mixed', errors='coerce')

def load(path):
    hdr = pd.read_csv(path, nrows=0, encoding='utf-8').columns
    use = ['time'] + [c for c in (COOL, OIL) if c in hdr]
    df = pd.read_csv(path, usecols=use, low_memory=False, encoding='utf-8')
    t = parse_time(df['time'])
    g = df[[c for c in use if c != 'time']].apply(pd.to_numeric, errors='coerce')
    g.index = pd.DatetimeIndex(t)
    return g.rename(columns={COOL: 'cool', OIL: 'oil'})

def fluid(v, samp, thr, tsec):
    ok = np.isfinite(v)
    idx = np.where(ok)[0]
    if len(idx) == 0:
        return {}
    start = v[idx[0]]
    last = tsec[idx[-1]]
    if start >= thr:
        return dict(ev=1, T=0.0, last=last, evfilled=0, start=start)
    hit = np.where(v >= thr)[0]
    if len(hit):
        k = hit[0]
        return dict(ev=1, T=float(tsec[k]), last=last, evfilled=int(not samp[k]), start=start)
    return dict(ev=0, T=np.nan, last=last, evfilled=0, start=start)

def rec(fn):
    path = os.path.join(ROOT, 'raw_only', fn)
    out = {'file': fn}
    iv = {'cool': np.array([]), 'oil': np.array([]), 'cool_u': np.array([]), 'oil_u': np.array([])}
    try:
        raw = load(path)
        for ch in ('cool', 'oil'):
            if ch in raw:
                tt = raw.index[raw[ch].notna().values]
                d = np.diff(tt.values).astype('timedelta64[ns]').astype(float) / 1e9
                iv[ch] = d
                ut = pd.DatetimeIndex(tt).unique()
                iv[ch + '_u'] = np.diff(ut.values).astype('timedelta64[ns]').astype(float) / 1e9
                out['nraw_' + ch] = int(len(tt))
        g0 = raw.resample('1s').mean()
        tsec = (g0.index - g0.index[0]).total_seconds().values
        end = float(tsec[-1])
        samp_c = np.isfinite(g0['cool'].values) if 'cool' in g0 else np.zeros(len(g0), bool)
        samp_o = np.isfinite(g0['oil'].values) if 'oil' in g0 else np.zeros(len(g0), bool)
        for F in FS:
            g = g0.ffill(limit=F) if F > 0 else g0
            p = f'f{F}_'
            out[p + 'end'] = end
            cv = g['cool'].values if 'cool' in g else np.full(len(g), np.nan)
            okc = np.isfinite(cv)
            out[p + 'ncool'] = int(okc.sum())
            if okc.sum() < 30:
                out[p + 'status'] = 'lt30'; continue
            first = cv[okc][0]
            if first >= 60:
                out[p + 'status'] = 'warm'; continue
            out[p + 'status'] = 'cold'
            ii = np.where(okc)[0]
            out[p + 'validspan'] = float(tsec[ii[-1]] - tsec[ii[0]])
            out[p + 'cstart'] = first
            for k, v in fluid(cv, samp_c, 80, tsec).items():
                out[f'{p}cool80_{k}'] = v
            ov = g['oil'].values if 'oil' in g else np.full(len(g), np.nan)
            out[p + 'noil'] = int(np.isfinite(ov).sum())
            if out[p + 'noil'] >= 30:
                for k, v in fluid(ov, samp_o, 70, tsec).items():
                    out[f'{p}oil70_{k}'] = v
    except Exception as e:
        out['error'] = repr(e)
    return out, iv

if __name__ == '__main__':
    dm = pd.read_csv(os.path.join(ROOT, 'drive_master.csv'), encoding='utf-8', low_memory=False)
    sd = pd.read_csv(os.path.join(ROOT, 'seasonal_drive_master.csv'), encoding='utf-8', low_memory=False)
    files = list(dm['file'])
    with Pool(4) as p:
        res = p.map(rec, files, chunksize=8)
    rows = [a for a, _ in res]
    r = pd.DataFrame(rows)
    r = r.merge(dm[['file', 'date', 'distance_km', 'duration_s']], on='file').merge(sd[['file', 'thermal_regime', 'local_iso']], on='file')
    r.to_csv(OUT, index=False, encoding='utf-8')
    np.savez(OUTI, **{k: np.concatenate([b[k] for _, b in res]) for k in ('cool', 'oil', 'cool_u', 'oil_u')},
             **{k + '_cold_file': np.array([0]) for k in ()})
    # per-drive interval arrays for cold-start-only pooling
    import pickle
    pickle.dump({f: b for f, (_, b) in zip(files, res)}, open(OUTI + '.pkl', 'wb'))
    print(r.shape, r.get('error', pd.Series(dtype=object)).notna().sum(), 'errors')
    for F in FS:
        print(F, r[f'f{F}_status'].value_counts().to_dict())
