import json, numpy as np
from audit_m430 import *
def fast_ci(x,y,days,p,cell,B=4000,seed=42,block=1,dep=None):
    ok=~np.isnan(p['M']); sel=cell_sel(x,cell)&ok
    eM=np.abs(np.exp(y)-np.exp(p['M'])); E={'B0':np.abs(np.exp(y)-1),'B1':np.abs(np.exp(y)-np.exp(p['B1m'])),'B2':np.abs(np.exp(y)-np.exp(p['B2m']))}
    ud=np.array(sorted(set(days[sel])))
    # per-day sums
    idx={d:np.where(sel&(days==d))[0] for d in ud}
    sM=np.array([eM[idx[d]].sum() for d in ud]); sB={k:np.array([E[k][idx[d]].sum() for d in ud]) for k in E}
    rng=np.random.default_rng(seed); nd=len(ud)
    res={k:[] for k in E}
    for _ in range(B):
        if block==1: pick=rng.integers(0,nd,nd)
        else:
            nb=int(np.ceil(nd/block)); st=rng.integers(0,nd-block+1,nb); pick=np.concatenate([np.arange(s,s+block) for s in st])[:nd]
        m=sM[pick].sum()
        for k in E: res[k].append(1-m/sB[k][pick].sum())
    pt={k:1-sM.sum()/sB[k].sum() for k in E}
    return {k:(round(pt[k],3),round(np.percentile(res[k],2.5),3),round(np.percentile(res[k],97.5),3)) for k in E}
print('--- seed robustness (primary MAE; lo/hi per ref) ---')
for i,name in enumerate(P['order']):
    f=P['fits'][i]; x=np.array(f['gapH']); y=np.array(f['y']); days=np.array(f['arrivalDay'])
    p,_=heldout(x,y,days,'k10')
    for cell in ['pooled','lt1','ge1']:
        ups=[];los0=[];los1=[]
        for sd in range(30):
            r=fast_ci(x,y,days,p,cell,B=4000,seed=sd)
            ups.append(r['B2'][2]); los0.append(r['B0'][1]); los1.append(r['B1'][1])
        print(name,cell,'B2 upper range [%.3f,%.3f] S3 fires %d/30 | B0 lower min %.3f | B1 lower min %.3f'%(min(ups),max(ups),sum(u<0 for u in ups),min(los0),min(los1)))
print('--- LODO ---')
for i,name in enumerate(P['order']):
    f=P['fits'][i]; x=np.array(f['gapH']); y=np.array(f['y']); days=np.array(f['arrivalDay'])
    p,sk=heldout(x,y,days,'lodo')
    for cell in ['pooled','lt1','ge1']:
        r=fast_ci(x,y,days,p,cell)
        print(name,cell,'skipped',sk,{k:v for k,v in r.items()})
print('--- fold design variants (pooled+strata, S3 upper, S1 lower) ---')
def heldout_edges(x,y,days,k,shift=0):
    days=np.array(days); ud=np.array(sorted(set(days))); n=len(ud)
    e=np.linspace(0,n,k+1).astype(int)
    preds={q:np.full(len(x),np.nan) for q in ['M','B0','B1m','B2m']}
    for j in range(k):
        fd=ud[e[j]:e[j+1]]; te=np.isin(days,fd); tr=~te
        s=sen(x[tr],y[tr]); preds['M'][te]=s*x[te]; pm=predict(x[tr],y[tr],x[te],'median')
        preds['B0'][te]=0; preds['B1m'][te]=pm['B1']; preds['B2m'][te]=pm['B2']
    return preds
for i,name in enumerate(P['order']):
    f=P['fits'][i]; x=np.array(f['gapH']); y=np.array(f['y']); days=np.array(f['arrivalDay'])
    for k in [5,10,20]:
        p=heldout_edges(x,y,days,k)
        for cell in ['pooled','lt1','ge1']:
            r=fast_ci(x,y,days,p,cell,B=2000)
            print(name,'k',k,cell,'B0',r['B0'],'B2',r['B2'])
    # random day-permutation CV (non-contiguous) for contiguity comparison
    rng=np.random.default_rng(7); ud=np.array(sorted(set(days))); perm=rng.permutation(ud)
    dd=np.array(days); mp={d:j for j,d in enumerate(perm)}; pseudo=np.array([mp[d] for d in dd])
    p=heldout_edges(x,y,pseudo,10)
    for cell in ['pooled']:
        print(name,'random-day 10-fold',cell,fast_ci(x,y,days,p,cell,B=2000))
print('--- moving-block bootstrap over ordered held-out days (block 5) ---')
for i,name in enumerate(P['order']):
    f=P['fits'][i]; x=np.array(f['gapH']); y=np.array(f['y']); days=np.array(f['arrivalDay'])
    p,_=heldout(x,y,days,'k10')
    for cell in ['pooled','lt1','ge1']:
        print(name,cell,'iid',fast_ci(x,y,days,p,cell,B=4000)['B2'],'MBB5',fast_ci(x,y,days,p,cell,block=5)['B2'], 'MBB5 B0',fast_ci(x,y,days,p,cell,block=5)['B0'])
