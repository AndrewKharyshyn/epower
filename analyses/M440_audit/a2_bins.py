import sys, json, numpy as np, pandas as pd
REPO = r"C:\Users\AndriiKharyshyn\Downloads\X-Trail Investigation\Repo\xtrail-repo"
TB = [(-99,-10,"<-10"),(-10,0,"-10-0"),(0,10,"0-10"),(10,20,"10-20"),(20,30,"20-30"),(30,40,"30-40"),(40,50,"40-50"),(50,99,"50+")]
def tbin(d, mask=None):
    rows = {}
    for lo, hi, l in TB:
        m = d.Tpack.notna() & (d.Tpack >= lo) & (d.Tpack < hi)
        if mask is not None: m &= mask
        rows[l] = m
    return rows
def sbin(v):  # v array of speed
    return (np.clip(v, 0, 129) // 10 * 10 + 5).astype(int)
def eff_temp(d, keep=None, cap='cap'):
    out = {}
    for l, m in tbin(d, keep).items():
        out[l] = (int(m.sum()), 100*d.loc[m, cap].sum()/d.loc[m, 'ke'].sum() if m.sum() else None)
    return out
def eff_speed(d, keep=None, col='speed', cap='cap'):
    mid = pd.Series(sbin(d[col].values), index=d.index)
    out = {}
    for b in sorted(mid.unique()):
        m = (mid == b)
        if keep is not None: m &= keep
        out[int(b)] = (int(m.sum()), 100*d.loc[m, cap].sum()/d.loc[m, 'ke'].sum() if m.sum() else None)
    return out
if __name__ == '__main__':
    d = pd.read_pickle(sys.argv[1])
    a = json.load(open(REPO + r'\summary_arrays.json', encoding='utf-8'))
    pt = {r['label']: r for r in a['regenByTempMeasured']}
    et = eff_temp(d)
    print('TEMP'); 
    for (lo,hi,l),(k,r) in zip(TB, et.items()):
        pub = [x for x in a['regenByTempMeasured'] if x['lo']==(None if lo==-99 else lo)][0]
        print(l, et[l][0], pub['n'], None if et[l][1] is None else round(et[l][1],3), pub['eff'])
    es = eff_speed(d)
    print('SPEED')
    ps = {r[0]: r for r in a['regenCaptureMeasured']}
    for b,(n,e) in es.items():
        print(b, n, ps.get(b,[None,None,None])[2], round(e,3), ps.get(b,[None,None,None])[1])
    print(len(d), sum(r[2] for r in a['regenCaptureMeasured']), sum(r['n'] for r in a['regenByTempMeasured']), d.Tpack.notna().sum())
