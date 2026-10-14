"""Any drive where the first grid second >= threshold is a forward-filled second? All thresholds 60/70/80, both fluids, F in {3,6}.
Usage: python -X utf8 check_filled_events.py <repo_root>"""
import sys, os
root = sys.argv[1]
sys.argv = [sys.argv[0], root, os.devnull, os.devnull]   # build_m437 reads argv at import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd
import build_m437 as B
from multiprocessing import Pool

def one(fn):
    raw = B.load(os.path.join(root, 'raw_only', fn))
    g0 = raw.resample('1s').mean()
    res = []
    for F in (3, 6):
        g = g0.ffill(limit=F)
        for ch in ('cool', 'oil'):
            if ch not in g: continue
            v = g[ch].values; s = np.isfinite(g0[ch].values)
            ok = np.isfinite(v)
            if not ok.any(): continue
            for thr in (60, 70, 80):
                if v[np.where(ok)[0][0]] >= thr: continue
                hit = np.where(v >= thr)[0]
                if len(hit):
                    res.append((F, ch, thr, int(not s[hit[0]])))
    return res

if __name__ == '__main__':
    dm = pd.read_csv(os.path.join(root, 'drive_master.csv'), encoding='utf-8', low_memory=False)
    with Pool(4) as p:
        rr = p.map(one, list(dm['file']), chunksize=8)
    df = pd.DataFrame([x for r in rr for x in r], columns=['F', 'ch', 'thr', 'filled'])
    print(df.groupby(['F', 'ch', 'thr']).filled.agg(['count', 'sum']))
