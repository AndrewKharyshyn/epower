import sys; sys.path.insert(0, 'analyses/M444_audit')
from lib2 import *
mst = pd.read_csv('drive_master.csv', usecols=['file', 'ev_rpm_dt_med_s']).set_index('file')
fast = (mst.ev_rpm_dt_med_s.reindex(X.file).to_numpy() < 1.0)
print('fast drives', len(set(X.file[fast])), 'slow/unknown rows', int((~fast).sum()), 'nan master', int(mst.ev_rpm_dt_med_s.isna().sum()))
res = {}
def run(label, popmask, dmode):
    rows = np.flatnonzero(hasT & (band != -9) & popmask)
    if dmode == 'allDays':
        Dm = D_; di = dayidx
    else:
        dsub = np.array(sorted(X.date[popmask].unique())); Dm = len(dsub)
        di = pd.Series(range(Dm), index=dsub).reindex(X.date).to_numpy()
        di = np.nan_to_num(di, nan=0).astype(int)
    A = cells(rows, gT[rows], band[rows], len(tb), 8, Dm, di)
    cand = [g for g in range(len(tb)) if A['gsup'][g]]
    T, S, cov, dropped = decide(A, cand, w)
    CNT = boot_idx(Dm)
    r = report(A, T, S, w, CNT, tn)
    print(label, dmode, 'D', Dm, 'cand', [tn[g] for g in cand], 'T', [tn[g] for g in T], 'bands', [bandname[s] for s in range(8) if S[s]], 'cov', round(float(cov), 4), 'dropped', [tn[g] for g in dropped])
    for k, v in r.items(): print('   ', k, v)
    res[label + '|' + dmode] = dict(T=[tn[g] for g in T], bands=[bandname[s] for s in range(8) if S[s]], cov=round(float(cov), 4), bars=r, D=Dm, avail=bool(len(T) >= 2 and cov >= 0.8))
for dm in ('allDays', 'subsetDays'):
    run('strictDropOnly', strict, dm)
    run('cadenceFast', fast, dm)
json.dump(res, open('analyses/M444_audit/out_sens.json', 'w', encoding='utf-8'), indent=1)
