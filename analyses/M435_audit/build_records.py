"""M435 blind audit step 1: per-drive cold-start records rebuilt from raw_only/ and the spec rules only.
Usage: python -X utf8 build_records.py <repo_root> <out_csv>"""
import sys, os
import numpy as np, pandas as pd
from multiprocessing import Pool

ROOT, OUT = sys.argv[1], sys.argv[2]
COOL = '\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 \u043e\u0445\u043e\u043b\u043e\u0434\u043d\u043e\u0457 \u0440\u0456\u0434\u0438\u043d\u0438 (\u2103)'
OIL = '\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 \u043e\u043b\u0456\u0457 \u0443 \u0434\u0432\u0438\u0433\u0443\u043d\u0443 (\u2103)'
OIL = '\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 \u043e\u043b\u0456\u0457 \u0443 \u0434\u0432\u0438\u0433\u0443\u043d\u0456 (\u2103)'

def parse_time(s):
    try:
        return pd.to_datetime(s, format='%H:%M:%S.%f', errors='raise')
    except (ValueError, TypeError):
        return pd.to_datetime(s, format='mixed', errors='coerce')

def grid(path, ff):
    hdr = pd.read_csv(path, nrows=0, encoding='utf-8').columns
    use = ['time'] + [c for c in (COOL, OIL) if c in hdr]
    df = pd.read_csv(path, usecols=use, low_memory=False, encoding='utf-8')
    t = parse_time(df['time'])
    g = df[[c for c in use if c != 'time']].apply(pd.to_numeric, errors='coerce')
    g.index = pd.DatetimeIndex(t)
    g = g.rename(columns={COOL: 'cool', OIL: 'oil'})
    g = g.resample('1s').mean()
    return g.ffill(limit=ff) if ff > 0 else g

def fluid(v, thr, tsec, endsec):
    """returns dict for one fluid: n_valid, start, event time, last valid sec, gap-before-event"""
    ok = np.isfinite(v)
    idx = np.where(ok)[0]
    if len(idx) == 0:
        return None
    start = v[idx[0]]
    last = tsec[idx[-1]]
    if start >= thr:
        return dict(nvalid=len(idx), start=start, T=0.0, last=last, gap=0, ev=1)
    hit = np.where(v >= thr)[0]   # NaN comparisons False
    if len(hit):
        k = hit[0]
        prev = idx[idx < k]
        gap = (k - prev[-1] - 1) if len(prev) else 0   # invalid seconds immediately before the event
        return dict(nvalid=len(idx), start=start, T=float(tsec[k]), last=last, gap=int(gap), ev=1)
    return dict(nvalid=len(idx), start=start, T=np.nan, last=last, gap=0, ev=0)

def rec(fn):
    path = os.path.join(ROOT, 'raw_only', fn)
    out = {'file': fn}
    try:
        for ff in (3, 0):
            g = grid(path, ff)
            tsec = (g.index - g.index[0]).total_seconds().values
            end = float(tsec[-1])
            cv = g['cool'].values if 'cool' in g else np.full(len(g), np.nan)
            ncv = int(np.isfinite(cv).sum())
            p = f'ff{ff}_'
            out[p + 'end'] = end
            out[p + 'ncool'] = ncv
            if ncv < 30:
                out[p + 'status'] = 'lt30'; continue
            first = cv[np.isfinite(cv)][0]
            out[p + 'cstart'] = first
            out[p + 'lag_first_valid'] = float(tsec[np.where(np.isfinite(cv))[0][0]])
            if first >= 60:
                out[p + 'status'] = 'warm'; continue
            out[p + 'status'] = 'cold'
            for thr in (60, 70, 80):
                r = fluid(cv, thr, tsec, end)
                for k, v in r.items():
                    out[f'{p}cool{thr}_{k}'] = v
            ov = g['oil'].values if 'oil' in g else np.full(len(g), np.nan)
            out[p + 'noil'] = int(np.isfinite(ov).sum())
            if out[p + 'noil'] >= 30:
                for thr in (60, 70, 80):
                    r = fluid(ov, thr, tsec, end)
                    for k, v in r.items():
                        out[f'{p}oil{thr}_{k}'] = v
    except Exception as e:
        out['error'] = repr(e)
    return out

if __name__ == '__main__':
    dm = pd.read_csv(os.path.join(ROOT, 'drive_master.csv'), encoding='utf-8', low_memory=False)
    sd = pd.read_csv(os.path.join(ROOT, 'seasonal_drive_master.csv'), encoding='utf-8', low_memory=False)
    with Pool(4) as p:
        rows = p.map(rec, list(dm['file']), chunksize=8)
    r = pd.DataFrame(rows)
    r = r.merge(dm[['file', 'date', 'distance_km', 'duration_s']], on='file').merge(sd[['file', 'thermal_regime', 'local_iso']], on='file')
    r.to_csv(OUT, index=False, encoding='utf-8')
    print(r.shape, r.get('error', pd.Series(dtype=object)).notna().sum(), 'errors')
    print(r['ff3_status'].value_counts())
