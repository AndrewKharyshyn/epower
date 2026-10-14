"""M435 audit: extra per-drive raw diagnostics for cold starts (temps at fixed times, last valid values, max, gap structure).
Usage: python -X utf8 diag_raw.py <repo_root> <rec.csv> <out.csv>"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import numpy as np, pandas as pd
from multiprocessing import Pool
import build_records as B   # reads sys.argv at import; harmless (ROOT/OUT reassigned below)

def one(args):
    root, fn = args
    g = B.grid(os.path.join(root, 'raw_only', fn), 3)
    tsec = (g.index - g.index[0]).total_seconds().values
    o = {'file': fn}
    for f in ('cool', 'oil'):
        if f not in g: continue
        v = g[f].values
        ok = np.isfinite(v)
        if not ok.any(): continue
        idx = np.where(ok)[0]
        o[f + '_lastval'] = v[idx[-1]]
        o[f + '_max'] = np.nanmax(v)
        o[f + '_first'] = v[idx[0]]
        # longest invalid run inside valid span, and number of invalid seconds in the span
        span = ok[idx[0]:idx[-1] + 1]
        o[f + '_invalid_in_span'] = int((~span).sum())
        for h in (120, 300, 600):
            k = np.searchsorted(tsec, h)
            o[f + f'_v{h}'] = v[k] if k < len(v) and np.isfinite(v[k]) else np.nan
        # slope over first 120 s of valid data (deg/s)
        s0 = idx[0]
        seg = v[s0:s0 + 121]
        o[f + '_gain120'] = (seg[np.isfinite(seg)][-1] - seg[np.isfinite(seg)][0]) if np.isfinite(seg).sum() > 1 else np.nan
    return o

if __name__ == '__main__':
    root, recp, outp = sys.argv[1:4]
    r = pd.read_csv(recp, encoding='utf-8', low_memory=False)
    files = list(r.loc[r['ff3_status'] == 'cold', 'file'])
    with Pool(4) as p:
        rows = p.map(one, [(root, f) for f in files], chunksize=8)
    pd.DataFrame(rows).to_csv(outp, index=False, encoding='utf-8')
    print(len(rows))
