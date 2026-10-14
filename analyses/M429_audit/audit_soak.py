import json, numpy as np, datetime as dt, sys
P='analyses/M429_pairs.json'
d=json.load(open(P,encoding='utf-8'))
def sen(x,y):
    dx=x[:,None]-x[None,:]; dy=y[:,None]-y[None,:]
    iu=np.triu_indices(len(x),k=1); a=dx[iu]; b=dy[iu]; v=a!=0
    return float(np.median(b[v]/a[v])) if v.any() else np.nan
def f(s): return np.inf if s>=0 else -1/s
def iso(day):
    y,w,_=dt.date.fromisoformat(day).isocalendar(); return f'{y}-W{w:02d}'
def boot(x,y,labels,B=4000,seed=42,iid=False):
    rng=np.random.default_rng(seed); n=len(x)
    sl=np.empty(B)
    if iid:
        for b in range(B):
            i=rng.integers(0,n,n); sl[b]=sen(x[i],y[i])
        G=n
    else:
        u,inv=np.unique(labels,return_inverse=True); G=len(u)
        idx=[np.where(inv==g)[0] for g in range(G)]
        for b in range(B):
            gs=rng.integers(0,G,G); i=np.concatenate([idx[g] for g in gs]); sl[b]=sen(x[i],y[i])
    ok=~np.isnan(sl); und=int((~ok).sum()); s=sl[ok]
    lo,hi=np.percentile(s,[2.5,97.5],method='linear')
    return dict(G=G,slope_ci=[lo,hi],k_ci=[-hi,-lo],tau_ci=[f(lo) if lo<0 else None, f(hi) if hi<0 else None],
                tau_upper_unbounded=bool(hi>=0),hl_ci=[np.log(2)*f(lo) if lo<0 else None,np.log(2)*f(hi) if hi<0 else None],
                nondecay=float((s>=0).mean()),undef=und,slopes=s)
def kish(labels):
    u,c=np.unique(labels,return_counts=True); return float(c.sum()**2/(c**2).sum())
out={}
for name,fit in zip(d['order'],d['fits']):
    x=np.array(fit['gapH']); y=np.array(fit['y']); ar=np.array(fit['arrivalDay']); dp=np.array(fit['departureDay'])
    wk=np.array([iso(a) for a in ar])
    ps=sen(x,y); r=dict(n=len(x),point_slope_recomputed=ps,point_slope_given=fit['pointSlope'],tau=f(ps),k=-ps,
        n_arrival=len(set(ar)),n_depart=len(set(dp)),n_week=len(set(wk)),kish_arrival=kish(ar),kish_depart=kish(dp),kish_week=kish(wk),
        cross_midnight=int((ar!=dp).sum()),share_gap_lt1h=float((x<1).mean()))
    # non-overlapping ISO week blocks (calendar iso week of arrival)
    for lab,L,iid in [('arrival',ar,False),('departure',dp,False),('isoweek',wk,False),('iid4000',None,True)]:
        o=boot(x,y,L,iid=iid); s=o.pop('slopes'); r[lab]=o
        if lab=='arrival': arr_slopes=s
        if lab=='iid4000': iid_slopes=s
    # old rule: iid B=1000, drop slope>=0, tau-scale percentile
    o1=np.random.default_rng(42); n=len(x); t=[]
    for b in range(1000):
        i=o1.integers(0,n,n); s_=sen(x[i],y[i])
        if s_<0: t.append(-1/s_)
    r['old_iid1000_tau_scale']=list(np.percentile(t,[2.5,97.5]))
    # tau-scale percentile of retained draws, arrival clusters (old-style on new draws)
    ts=-1/arr_slopes[arr_slopes<0]; r['arrival_tau_scale_pct_of_retained']=list(np.percentile(ts,[2.5,97.5]))
    # leave-one-arrival-day-out
    ks=[];nn=0
    for dday in np.unique(ar):
        m=ar!=dday; s_=sen(x[m],y[m]); ks.append(-s_); nn+=int(s_>=0)
    r['loo_k_range']=[min(ks),max(ks)]; r['loo_nonneg_slope_count']=nn; r['loo_n']=len(ks)
    out[name]=r
    print(name,json.dumps(r,default=float,indent=None)); sys.stdout.flush()
json.dump(out,open('analyses/M429_audit/audit_result_full.json','w',encoding='utf-8'),default=float,indent=1)
