import os, pickle, numpy as np, pandas as pd, sys
sys.path.insert(0, r'C:\Users\AndriiKharyshyn\Downloads\X-Trail Investigation\Repo\xtrail-repo')
import compute_drive_summary_v6 as V6
REPO = r'C:\Users\AndriiKharyshyn\Downloads\X-Trail Investigation\Repo\xtrail-repo'
dm = pd.read_csv(os.path.join(REPO, 'drive_master.csv'), low_memory=False).copy()
R = {r['file']: r for r in pickle.load(open(os.path.join(REPO, 'analyses', 'M432_audit', 'extract.pkl'), 'rb'))}
asb = lambda s: s.map(lambda x: x is True or str(x).strip().lower() == 'true').astype(bool)
P0 = asb(dm.ev_valid) & ~asb(dm.ens_outlier_v2)
f = dm.file[P0].tolist()
e0 = np.array([R[x]['dist'][('nearest', 3.0, 400, 3)] for x in f])
print('exact A=0.5 lost', end=' ')
v = np.array([R[x]['cov'][('nearest', 0.5)] >= 0.95 and R[x]['cov_speed'] >= 0.95 and R[x]['base_ok'] for x in f])
d = dm.distance_km[P0].values
print(100 * e0[v].sum() / d[v].sum() - 100 * e0.sum() / d.sum(), 100 * e0.sum() / d.sum())
# spin-down detail on a sample of P0 drives: values of exact zero, stop events
n0 = nz = nle = 0; durs = []; 
for x in f[::6]:
    b = open(os.path.join(REPO, 'raw_only', x), 'rb').read()
    df, t = V6._prep_bytes(b)
    e = V6._series(df, t, 'eng_rpm', lo=0)
    if e is None: continue
    xs = e['v'].values; ts = e['t'].values
    n0 += (xs == 0).sum(); nle += (xs <= 100).sum()
    # stop events: transitions from >800 to <=100 through band; duration of band passage in seconds
    band = (xs > 100) & (xs <= 800)
    idx = np.flatnonzero(band)
    if len(idx) == 0: continue
    grp = np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1)
    for gp in grp:
        a, b_ = gp[0], gp[-1]
        if a > 0 and b_ < len(xs) - 1 and xs[a - 1] > 800 and xs[b_ + 1] <= 100:
            durs.append((ts[b_ + 1] - ts[a - 1]) / np.timedelta64(1, 's'))
print('exact-zero share of <=100 native samples', n0 / nle)
print('spin-down passages (>800 -> band -> <=100): n', len(durs), 'median window s', np.median(durs), 'p90', np.percentile(durs, 90))
