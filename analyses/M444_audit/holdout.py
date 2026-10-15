import sys; sys.path.insert(0, 'analyses/M444_audit')
from lib2 import *
rows = np.flatnonzero(hasT & (band != -9))
rows_all = rows
A = cells(rows, gT[rows], band[rows], len(tb), 8, D_, dayidx)
cand = [g for g in range(len(tb)) if A['gsup'][g]]
T, S, cov, dropped = decide(A, cand, w)
print('full', [tn[g] for g in T], [bandname[s] for s in range(8) if S[s]], round(float(cov), 4))
full_std = point_std(A, T, S, w)
print({tn[g]: round(v, 3) for g, v in full_std.items()})
blocks = np.array_split(days, 4)
out = []
for k, bd in enumerate(blocks):
    inb = np.isin(X.date.to_numpy(), bd)
    r = np.flatnonzero(hasT & (band != -9) & inb)
    Ak = cells(r, gT[r], band[r], len(tb), 8, D_, dayidx)
    Tk = [g for g in T if Ak['gsup'][g]]
    # S*_k = bands of S* supported for every group in T_k
    def dec(Tk):
        Tk = list(Tk); dropped = []
        while True:
            if len(Tk) >= 2:
                Sk = np.array([S[s] and Ak['sup'][Tk, s].all() for s in range(8)]); covk = w[Sk].sum()
            else:
                Sk = np.zeros(8, bool); covk = 0.0
            if len(Tk) < 2 or covk >= 0.8:
                return Tk, Sk, covk, dropped
            nb = {g: (Ak['sup'][g] & S).sum() for g in Tk}; tke = {g: Ak['dk'][g].sum() for g in Tk}
            victim = sorted(Tk, key=lambda g: (nb[g], tke[g], g))[0]
            Tk.remove(victim); dropped.append(victim)
    Tk2, Sk, covk, dr = dec(Tk)
    avail = len(Tk2) >= 2 and covk >= 0.8
    rec = dict(block=k + 1, firstDay=str(bd[0]), lastDay=str(bd[-1]), nDays=len(bd), Tk_initial=[tn[g] for g in Tk], groups=[tn[g] for g in Tk2],
               bands=[bandname[s] for s in range(8) if Sk[s]], cov=round(float(covk), 4), available=bool(avail), dropped=[tn[g] for g in dr])
    if avail:
        bs = point_std(Ak, Tk2, Sk, w)
        rec['bars'] = {tn[g]: round(v, 2) for g, v in bs.items()}
        ref = point_std(A, Tk2, Sk, w)    # full-sample cells restandardized over S*_k on final groups
        rec['refBars'] = {tn[g]: round(v, 2) for g, v in ref.items()}
        pairs = 0; same = 0; pl = []
        for a, b in zip(Tk2[:-1], Tk2[1:]):
            db = bs[b] - bs[a]; dr_ = ref[b] - ref[a]; pairs += 1; same += int(np.sign(db) == np.sign(dr_)); pl.append((tn[a], tn[b], round(db, 2), round(dr_, 2)))
        rec['nAdjacentPairs'] = pairs; rec['nSameSign'] = same; rec['pairs'] = pl
    print(rec)
    out.append(rec)
print('total pairs', sum(r.get('nAdjacentPairs', 0) for r in out), 'same', sum(r.get('nSameSign', 0) for r in out))
json.dump(dict(blocks=out), open('analyses/M444_audit/out_holdout.json', 'w', encoding='utf-8'), indent=1)
