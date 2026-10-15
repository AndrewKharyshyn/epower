"""Shared setup for the second M444 audit (study block). Reuses my own M441 audit cache (cache_C) and aggregate.py."""
import sys, json
sys.path.insert(0, 'analyses/M441_audit')
import numpy as np, pandas as pd
import aggregate as ag

DD = ag.load('analyses/M441_audit/cache_C')
X, B2, BC, TT, tr = ag.kept_all(DD)
mass = X.mass.to_numpy()
# episode deceleration: iv rows (kind>=0) are consecutive in k within an episode
epdec = []
epid_all = []
epc = 0
for f, d in DD.items():
    iv = d.get('iv')
    if iv is None or len(iv) == 0:
        continue
    k = iv.k.to_numpy(); kind = iv.kind.to_numpy()
    brk = np.concatenate([[0], (np.diff(k) != 1).astype(int)]); eid = np.cumsum(brk)
    kept = kind < 2
    drop = (iv.v0 - iv.v1).to_numpy(); dts = iv.dt_s.to_numpy()
    sd = np.bincount(eid[kept], weights=drop[kept], minlength=eid.max() + 1)
    st = np.bincount(eid[kept], weights=dts[kept], minlength=eid.max() + 1)
    with np.errstate(all='ignore'):
        dec = sd / 3.6 / st
    epdec.append(dec[eid][kept]); epid_all.append(eid[kept] + epc); epc += eid.max() + 1
X['epdec'] = np.concatenate(epdec); X['epid'] = np.concatenate(epid_all)
X['strict'] = X.kind == 0
edges = [40, 50, 55, 60, 63, 66, 69, 72, 100]
soc = X.soc.to_numpy()
band = np.full(len(X), -9)
ok = np.isfinite(soc) & (soc >= 0) & (soc <= 100)
band[ok & (soc < 40)] = -1
for i in range(8):
    hi = edges[i + 1]
    m = ok & (soc >= edges[i]) & ((soc < hi) if i < 7 else (soc <= 100))
    band[m] = i
bandname = ['band 40-50', 'band 50-55', 'band 55-60', 'band 60-63', 'band 63-66', 'band 66-69', 'band 69-72', 'band 72-100']
tmp = X.temp.to_numpy(); hasT = np.isfinite(tmp)
days = np.array(sorted(X.date.unique())); D_ = len(days)
dayidx = pd.Series(range(D_), index=days)[X.date].to_numpy()
fileidx = pd.factorize(X.file)[0]
ke = X.dv2.to_numpy() * ag.K * mass
ch = X.charge.to_numpy()
strict = X.strict.to_numpy()
v0 = X.v0.to_numpy(); v1 = X.v1.to_numpy()
tb = ag.TEMP_BINS
tn = [t[2] for t in tb]
