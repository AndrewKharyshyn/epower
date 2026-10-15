from common2 import *

def cells(rowi, g, s, ng, ns, D, dayidx_, ke_=None, ch_=None):
    """cell arrays over (group, stratum, day); floors from strict intervals"""
    ke_ = ke if ke_ is None else ke_; ch_ = ch if ch_ is None else ch_
    sel = (s >= 0) & (g >= 0)
    rowi, g, s = rowi[sel], g[sel], s[sel]
    dk = np.zeros((ng, ns, D)); dc = np.zeros((ng, ns, D))
    np.add.at(dk, (g, s, dayidx_[rowi]), ke_[rowi]); np.add.at(dc, (g, s, dayidx_[rowi]), ch_[rowi])
    st = strict[rowi]
    nst = np.zeros((ng, ns)); drv = np.zeros((ng, ns), int); dys = np.zeros((ng, ns), int)
    key = g * ns + s
    for c in np.unique(key[st]):
        m = st & (key == c); gg, ss = divmod(int(c), ns)
        nst[gg, ss] = m.sum(); drv[gg, ss] = len(set(fileidx[rowi[m]])); dys[gg, ss] = len(set(dayidx_[rowi[m]]))
    sup = (nst >= 200) & (drv >= 10) & (dys >= 5)
    gsup = np.zeros(ng, bool); gdet = []
    for gg in range(ng):
        m = st & (g == gg); n = int(m.sum()); dr = len(set(fileidx[rowi[m]])); dy = len(set(dayidx_[rowi[m]]))
        gsup[gg] = (n >= 200) and dr >= 10 and dy >= 5; gdet.append((n, dr, dy))
    return dict(dk=dk, dc=dc, sup=sup, gsup=gsup, gdet=gdet, nst=nst)

def decide(A, cand, w, thr=0.80, order_key=None):
    T = list(cand); dropped = []
    ns = len(w)
    while True:
        if len(T) >= 2:
            S = np.array([A['sup'][T, s].all() for s in range(ns)]); cov = w[S].sum()
        else:
            S = np.zeros(ns, bool); cov = 0.0
        if len(T) < 2 or cov >= thr:
            return T, S, cov, dropped
        nb = {g: A['sup'][g].sum() for g in T}; tke = {g: A['dk'][g].sum() for g in T}
        victim = sorted(T, key=lambda g: (nb[g], tke[g], g))[0]
        T.remove(victim); dropped.append(victim)

def boot_idx(D):
    rng = np.random.default_rng(42)
    IDX = rng.integers(0, D, (4000, D))
    return np.stack([np.bincount(r, minlength=D) for r in IDX]).astype(float)

def report(A, T, S, w, CNT, names):
    wt = w[S] / w[S].sum(); out = {}
    for g in T:
        K_ = A['dk'][g][S]; C_ = A['dc'][g][S]
        R = 100 * C_.sum(1) / K_.sum(1); std = float((wt * R).sum())
        obsS = 100 * C_.sum() / K_.sum()
        kb = CNT @ K_.T; cb = CNT @ C_.T
        with np.errstate(all='ignore'):
            Rb = 100 * cb / kb
        fail = (kb <= 0).any(1) | ~np.isfinite(Rb).all(1)
        sb = (wt * Rb).sum(1)[~fail]
        lo, hi = np.percentile(sb, [2.5, 97.5])
        out[names[g]] = dict(std=round(std, 3), ci=[round(float(lo), 3), round(float(hi), 3)], obsCommon=round(float(obsS), 3), failed=int(fail.sum()))
    return out

def point_std(A, T, S, w):
    wt = w[S] / w[S].sum(); out = {}
    for g in T:
        K_ = A['dk'][g][S]; C_ = A['dc'][g][S]
        R = 100 * C_.sum(1) / K_.sum(1); out[g] = float((wt * R).sum())
    return out

# primary reference
ref = hasT & (band != -9)
KEref = np.array([ke[ref & (band == s)].sum() for s in [-1] + list(range(8))])
w9 = KEref / KEref.sum(); w = w9[1:]
gT = np.full(len(X), -1)
for j, (lo, hi, _) in enumerate(tb):
    gT[(tmp >= lo) & (tmp < hi)] = j
