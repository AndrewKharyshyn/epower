import json, numpy as np, datetime as dt
d=json.load(open('analyses/M429_pairs.json',encoding='utf-8'))
def sen(x,y):
    dx=x[:,None]-x[None,:]; dy=y[:,None]-y[None,:]
    iu=np.triu_indices(len(x),k=1); a=dx[iu]; b=dy[iu]; v=a!=0
    return float(np.median(b[v]/a[v]))
res={}
for name,fit in zip(d['order'],d['fits']):
    x=np.array(fit['gapH']); y=np.array(fit['y']); ar=np.array(fit['arrivalDay'])
    ps=sen(x,y)
    days=np.array(sorted(set(ar))); dn=np.array([dt.date.fromisoformat(a).toordinal() for a in days])
    o={}
    # residual ICC by arrival day: resid from median line through median intercept
    b0=np.median(y-ps*x); e=y-ps*x-b0
    u,inv=np.unique(ar,return_inverse=True); cnt=np.bincount(inv)
    gm=np.bincount(inv,e)/cnt
    ssb=(cnt*(gm-e.mean())**2).sum(); ssw=((e-gm[inv])**2).sum()
    k=len(u); n=len(e); msb=ssb/(k-1); msw=ssw/(n-k); n0=(n-(cnt**2).sum()/n)/(k-1)
    o['icc_arrival_day']=float((msb-msw)/(msb+(n0-1)*msw))
    # lag-1 corr of residuals between consecutive pairs when crossing a day
    # (pairs in input order = chronological)
    cross=ar[1:]!=ar[:-1]
    o['lag1_resid_corr_all']=float(np.corrcoef(e[1:],e[:-1])[0,1])
    o['lag1_resid_corr_cross_day']=float(np.corrcoef(e[1:][cross],e[:-1][cross])[0,1]) if cross.sum()>3 else None
    o['n_cross_day_adjacent']=int(cross.sum())
    # contiguous calendar-day block bootstrap (fixed L-day blocks, start on any day, concatenated to cover span)
    for L in (3,7):
        rng=np.random.default_rng(42); span=dn.max()-dn.min()+1; nb=int(np.ceil(span/L))
        starts=np.arange(dn.min(),dn.max()-L+2)
        byday={dd:np.where(np.array([dt.date.fromisoformat(a).toordinal() for a in ar])==dd)[0] for dd in dn}
        sl=[]
        for b in range(2000):
            st=rng.choice(starts,nb); idx=np.concatenate([byday[dd] for s0 in st for dd in range(s0,s0+L) if dd in byday])
            sl.append(sen(x[idx],y[idx]))
        sl=np.array(sl); lo,hi=np.percentile(sl,[2.5,97.5])
        o[f'movingblock{L}d_k_ci']=[float(-hi),float(-lo)]; o[f'movingblock{L}d_tau_ci']=[float(-1/lo),float(-1/hi)] if hi<0 else [float(-1/lo),None]
    # leverage: slope on gap>=1h only, gap<1h only
    for lab,m in (('gap_ge_1h',x>=1),('gap_lt_1h',x<1)):
        o[lab]=dict(n=int(m.sum()),k=float(-sen(x[m],y[m])) if m.sum()>3 else None)
    # k width ratios from bootstrap results
    res[name]=o; print(name,json.dumps(o))
a=json.load(open('analyses/M429_audit/audit_result_full.json',encoding='utf-8'))
for n,r in a.items():
    w=lambda m:r[m]['k_ci'][1]-r[m]['k_ci'][0]
    print(n,'width ratio arrival/iid',w('arrival')/w('iid4000'),'isoweek/iid',w('isoweek')/w('iid4000'),'arrival lo/hi diff vs iid',r['arrival']['k_ci'],r['iid4000']['k_ci'])
json.dump(res,open('analyses/M429_audit/diagnostics.json','w',encoding='utf-8'),indent=1)
