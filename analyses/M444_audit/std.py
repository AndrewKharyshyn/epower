"""Blind reproduction of M444 (spec Rev 2.1 sec 1-4, 11) on top of my own M441 audit extractor cache (cache_C)."""
import sys, json
sys.path.insert(0, 'analyses/M441_audit')
import numpy as np, pandas as pd
import aggregate as ag

SPEED_REQ_TEMP = (len(sys.argv) > 1 and sys.argv[1] == 'speedTemp')
DD = ag.load('analyses/M441_audit/cache_C')
X, B2, BC, TT, tr = ag.kept_all(DD)
mass = X.mass.to_numpy()
X['strict'] = (X.kind == 0)
edges = [40, 50, 55, 60, 63, 66, 69, 72, 100]
soc = X.soc.to_numpy()
band = np.full(len(X), -9)            # -9 invalid, -1 below 40, 0..7 bands
ok = np.isfinite(soc) & (soc >= 0) & (soc <= 100)
band[ok & (soc < 40)] = -1
for i in range(8):
    hi = edges[i + 1]
    m = ok & (soc >= edges[i]) & ((soc < hi) if i < 7 else (soc <= 100))
    band[m] = i
bandname = ['band 40-50', 'band 50-55', 'band 55-60', 'band 60-63', 'band 63-66', 'band 66-69', 'band 69-72', 'band 72-100']
tmp = X.temp.to_numpy()
hasT = np.isfinite(tmp)
days = np.array(sorted(X.date.unique())); D_ = len(days)
dayidx = pd.Series(range(D_), index=days)[X.date].to_numpy()
fileidx = pd.factorize(X.file)[0]
print('kept intervals', len(X), 'days', D_, 'drives', X.file.nunique())
ke = X.dv2.to_numpy() * ag.K * mass
ch = X.charge.to_numpy()
strict = X.strict.to_numpy()
# ---- reference weights
ref = hasT & (band != -9)
KEref = np.array([ke[ref & (band == s)].sum() for s in [-1] + list(range(8))])
w9 = KEref / KEref.sum()    # order: below40, 40-50, ..., 72-100
W = dict(zip(['below40'] + bandname, w9))
print('weights', {k: round(float(v), 5) for k, v in W.items()})
w = w9[1:]    # 8 in-band


def cell_arrays(rowi, g, kev, chv, st, ng):
    b = band[rowi]
    sel = b >= 0
    rowi, g, kev, chv, st, b = rowi[sel], g[sel], kev[sel], chv[sel], st[sel], b[sel]
    dk = np.zeros((ng, 8, D_)); dc = np.zeros((ng, 8, D_))
    np.add.at(dk, (g, b, dayidx[rowi]), kev); np.add.at(dc, (g, b, dayidx[rowi]), chv)
    nst = np.zeros((ng, 8)); drv = np.zeros((ng, 8), int); dys = np.zeros((ng, 8), int)
    for gg in range(ng):
        for s in range(8):
            m = (g == gg) & (b == s) & st
            nst[gg, s] = m.sum(); drv[gg, s] = len(set(fileidx[rowi[m]])); dys[gg, s] = len(set(dayidx[rowi[m]]))
    sup = (nst >= 200) & (drv >= 10) & (dys >= 5)
    gsup = np.zeros(ng, bool); gdet = []
    for gg in range(ng):
        m = (g == gg) & st
        n = m.sum(); dr = len(set(fileidx[rowi[m]])); dy = len(set(dayidx[rowi[m]]))
        gsup[gg] = (n >= 200) and dr >= 10 and dy >= 5; gdet.append((int(n), dr, dy))
    return dict(dk=dk, dc=dc, sup=sup, gsup=gsup, gdet=gdet, nst=nst, drv=drv, dys=dys)


def decide(A, cand, thr=0.80):
    T = list(cand)
    dropped = []
    while True:
        if len(T) >= 2:
            S = np.array([A['sup'][T, s].all() for s in range(8)])
            cov = w[S].sum()
        else:
            S = np.zeros(8, bool); cov = 0
        if len(T) < 2 or cov >= thr:
            return T, S, cov, dropped
        nb = {g: A['sup'][g].sum() for g in T}
        tke = {g: A['dk'][g].sum() for g in T}
        victim = sorted(T, key=lambda g: (nb[g], tke[g], g))[0]
        T.remove(victim); dropped.append(victim)


rng = np.random.default_rng(42)
IDX = rng.integers(0, D_, (4000, D_))
CNT = np.stack([np.bincount(r, minlength=D_) for r in IDX]).astype(float)     # 4000 x D


def report(A, T, S, names):
    wt = w[S] / w[S].sum()
    out = {}
    for g in T:
        K_ = A['dk'][g][S]; C_ = A['dc'][g][S]     # nS x D
        R = 100 * C_.sum(1) / K_.sum(1)
        std = float((wt * R).sum())
        obsS = 100 * C_.sum() / K_.sum()
        obsAll = 100 * A['dc'][g].sum() / A['dk'][g].sum()
        kb = CNT @ K_.T; cb = CNT @ C_.T
        with np.errstate(all='ignore'):
            Rb = 100 * cb / kb
        fail = (kb <= 0).any(1) | ~np.isfinite(Rb).all(1)
        sb = (wt * Rb).sum(1)[~fail]
        lo, hi = np.percentile(sb, [2.5, 97.5])
        out[names[g]] = dict(std=round(std, 3), ci=[round(float(lo), 3), round(float(hi), 3)], obsCommon=round(float(obsS), 3), obsAllSoc=round(float(obsAll), 3), failed=int(fail.sum()))
    return out


res = {'weights': {k: round(float(v), 5) for k, v in W.items()}, 'nIntervalsKept': len(X), 'nDays': D_}
tb = ag.TEMP_BINS
tn = [t[2] for t in tb]
rowsT = np.flatnonzero(hasT)
gT = np.full(len(X), -1)
for j, (lo, hi, _) in enumerate(tb):
    gT[(tmp >= lo) & (tmp < hi)] = j
A_T = cell_arrays(rowsT, gT[rowsT], ke[rowsT], ch[rowsT], strict[rowsT], len(tb))
print('TEMP group support (n strict, drives, days)', dict(zip(tn, A_T['gdet'])))
print('TEMP sup matrix\n', pd.DataFrame(A_T['sup'].astype(int), index=tn, columns=bandname))
candT = [g for g in range(len(tb)) if A_T['gsup'][g]]
T, S, cov, dropped = decide(A_T, candT)
print('TEMP cand', [tn[g] for g in candT], 'retained groups', [tn[g] for g in T], 'bands', [bandname[s] for s in range(8) if S[s]], 'cov', cov, 'dropped', [tn[g] for g in dropped])
for thr in (0.7, 0.9):
    t2, s2, c2, d2 = decide(A_T, candT, thr); print(' avail@', thr, len(t2) >= 2 and c2 >= thr, [tn[g] for g in t2], round(float(c2), 4))
res['temp'] = dict(cand=[tn[g] for g in candT], groups=[tn[g] for g in T], bands=[bandname[s] for s in range(8) if S[s]], cov=round(float(cov), 4), dropped=[tn[g] for g in dropped],
                   bars=report(A_T, T, S, tn))
for k, v in res['temp']['bars'].items(): print(' ', k, v)

sn = ['%d-%d' % (10 * j, 10 * j + 10) for j in range(13)] + ['>=130']
Bk = B2 * ag.K * mass[:, None]
rows, gs = np.nonzero(TT)
if SPEED_REQ_TEMP:
    m = hasT[rows]; rows, gs = rows[m], gs[m]
kv = Bk[rows, gs]; cv = BC[rows, gs]; st = strict[rows]
A_S = cell_arrays(rows, gs, kv, cv, st, 14)
print('SPEED group support', dict(zip(sn, A_S['gdet'])))
print(pd.DataFrame(A_S['sup'].astype(int), index=sn, columns=bandname))
candS = [g for g in range(1, 13) if A_S['gsup'][g]]
T2, S2, cov2, dropped2 = decide(A_S, candS)
print('SPEED cand', [sn[g] for g in candS], 'retained', [sn[g] for g in T2], 'bands', [bandname[s] for s in range(8) if S2[s]], 'cov', cov2, 'dropped', [sn[g] for g in dropped2])
for thr in (0.7, 0.9):
    t2, s2, c2, d2 = decide(A_S, candS, thr); print(' avail@', thr, len(t2) >= 2 and c2 >= thr, [sn[g] for g in t2], round(float(c2), 4))
res['speed'] = dict(cand=[sn[g] for g in candS], groups=[sn[g] for g in T2], bands=[bandname[s] for s in range(8) if S2[s]], cov=round(float(cov2), 4), dropped=[sn[g] for g in dropped2],
                    bars=report(A_S, T2, S2, sn))
for k, v in res['speed']['bars'].items(): print(' ', k, v)
json.dump(res, open('analyses/M444_audit/out%s.json' % ('_speedTemp' if SPEED_REQ_TEMP else ''), 'w', encoding='utf-8'), indent=1)
