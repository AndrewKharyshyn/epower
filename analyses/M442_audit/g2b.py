from lib import *
pool=files
even=[f for f in pool if int(res[f]['date'][-2:])%2==0]
both=['2026-05-14','2026-09-06','2026-10-08']
fastall=[f for f in sup if res[f]['fast']]
def e(fs,c,var='nat',m=1890.):
    a=np.array([res[f][var][CI[c]] for f in fs]).sum(0); return 100*a[0]/(a[4]*m/1890.+a[1]-a[4]) if a[1]>0 else np.nan
cells=['total','T3','T4','T5','S1','S2','S3','S4','S5','S6','S7']
for c in cells:
    b=max(abs(e(fastall,c)-e(fastall,c,v)) for v in ('d2','d3'))
    F=[f for f in even if res[f]['fast'] and res[f]['date'] in both]; S=[f for f in even if not res[f]['fast'] and res[f]['date'] in both]
    pf=perday(F,'nat',[c],both)[c]; ps=perday(S,'nat',[c],both)[c]
    pt=100*pf[:,0].sum()/pf[:,1].sum()-100*ps[:,0].sum()/ps[:,1].sum()
    rng=np.random.default_rng(42); idx=rng.integers(0,3,(4000,3))
    with np.errstate(all='ignore'):
        d=100*pf[idx,0].sum(1)/pf[idx,1].sum(1)-100*ps[idx,0].sum(1)/ps[idx,1].sum(1)
    ci=np.nanpercentile(d,[2.5,97.5])
    hw=(e(F+S,c,m=1860.)-e(F+S,c,m=1920.))/2
    print(c,'diff',round(pt,2),'ci',ci.round(2),'tol',round(b+abs(hw),2),'FAIL' if (ci[0]>0 or ci[1]<0) and abs(pt)>b+abs(hw) else 'ok/indet', 'nan draws',np.isnan(d).sum())
