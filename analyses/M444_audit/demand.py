import sys; sys.path.insert(0, 'analyses/M444_audit')
from lib2 import *
def wq(x, w_, q):
    o = np.argsort(x, kind='stable'); x = x[o]; w_ = w_[o]; c = np.cumsum(w_) / w_.sum()
    return x[np.searchsorted(c, q, 'left')]
m0 = strict & (v0 >= 10)
c1, c2 = [float(wq(X.epdec.to_numpy()[m0], ke[m0], q)) for q in (1/3, 2/3)]
print('cuts', c1, c2)
dec = X.epdec.to_numpy()
dcl = np.where(dec < c1, 0, np.where(dec < c2, 1, 2))
scl = np.where(v0 < 40, 0, np.where(v0 < 70, 1, 2))
pop = (v0 >= 10) & hasT & (band != -9)
soc9 = band + 1   # 0 below40 ... 8
grp3 = np.full(len(X), -1)
grp3[(band == 0) | (band == 1)] = 0; grp3[(band >= 2) & (band <= 4)] = 1; grp3[band >= 5] = 2
levels = {
 'L1': (soc9 * 9 + scl * 3 + dcl, 81),
 'L2': (soc9 * 3 + scl, 27),
 'L3': (np.where(grp3 >= 0, grp3 * 9 + scl * 3 + dcl, -1), 27),
 'SOConly': (soc9, 9),
}
rows = np.flatnonzero(pop)
CNT = boot_idx(D_)
res = {}
for lev, (sid, nS) in levels.items():
    wl_full = np.array([ke[pop & (sid == s)].sum() for s in range(nS)])
    for norm in ('all-pop', 'strata-only'):
        wl = wl_full / (wl_full.sum() if norm == 'strata-only' or lev != 'L3' else ke[pop].sum())
        if lev != 'L3' and norm == 'strata-only':
            pass
        A = cells(rows, gT[rows], sid[rows], len(tb), nS, D_, dayidx)
        cand = [g for g in range(len(tb)) if A['gsup'][g]]
        T, S, cov, dropped = decide(A, cand, wl)
        avail = len(T) >= 2 and cov >= 0.8
        # coverage on initial candidate set
        S0 = np.array([A['sup'][cand, s].all() for s in range(nS)]); cov0 = wl[S0].sum()
        print(lev, norm, 'wsum', round(float(wl.sum()), 4), 'cand', [tn[g] for g in cand], 'cov0', round(float(cov0), 4), 'final T', [tn[g] for g in T], 'S nstrata', int(S.sum()), 'cov', round(float(cov), 4), 'avail', avail, 'dropped', [tn[g] for g in dropped])
        if lev in ('L2', 'SOConly') or (lev in ('L1', 'L3')) and avail:
            names = tn
            if avail or lev == 'SOConly':
                r = report(A, T, S, wl, CNT, names)
                for k, v in r.items(): print('   ', k, v)
                res[lev + '|' + norm] = dict(cov=float(cov), T=[tn[g] for g in T], bars=r, avail=bool(avail), nS=int(S.sum()))
        res.setdefault(lev + '|' + norm + '|info', dict(cov0=float(cov0), cov=float(cov), avail=bool(avail), T=[tn[g] for g in T], nStrata=nS))
json.dump(res, open('analyses/M444_audit/out_demand.json', 'w', encoding='utf-8'), indent=1)

print('--- L1 drop path')
sid, nS = levels['L1']
wl = np.array([ke[pop & (sid == s)].sum() for s in range(nS)]); wl /= wl.sum()
A = cells(rows, gT[rows], sid[rows], len(tb), nS, D_, dayidx)
print('nstrata with KE>0', int((wl > 0).sum()), 'supported per group', {tn[g]: int(A['sup'][g].sum()) for g in range(len(tb))})
T = [3, 4, 5, 6]
while len(T) >= 2:
    S = np.array([A['sup'][T, s].all() for s in range(nS)]); print([tn[g] for g in T], 'S', int(S.sum()), 'cov', round(float(wl[S].sum()), 4))
    nb = {g: A['sup'][g].sum() for g in T}; tke = {g: A['dk'][g].sum() for g in T}
    T.remove(sorted(T, key=lambda g: (nb[g], tke[g], g))[0])
