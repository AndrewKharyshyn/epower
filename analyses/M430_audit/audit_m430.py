import json, numpy as np, sys
R='C:/Users/AndriiKharyshyn/Downloads/X-Trail Investigation/Repo/xtrail-repo/'
P=json.load(open(R+'analyses/M429_pairs.json',encoding='utf-8'))
EDGES=[0,1,3,6,12,24,np.inf]
def sen(x,y):
    dx=x[:,None]-x[None,:]; dy=y[:,None]-y[None,:]
    iu=np.triu_indices(len(x),1); a=dx[iu]; b=dy[iu]; v=a!=0
    return float(np.median(b[v]/a[v]))
def binidx(x): return np.searchsorted(EDGES,x,side='right')-1
def predict(xtr,ytr,xte,stat):
    """returns dict model->yhat for given stat family ('median' or 'mean')"""
    f=np.median if stat=='median' else np.mean
    out={}
    out['B0']=np.zeros(len(xte))
    lvl=f(ytr); out['B1']=np.full(len(xte),lvl)
    bt=binidx(xtr); be=binidx(xte); yh=np.empty(len(xte))
    for b in range(6):
        m=bt==b
        lv=f(ytr[m]) if m.sum()>=5 else lvl
        yh[be==b]=lv
    out['B2']=yh
    return out
def folds_assign(days,mode):
    ud=np.array(sorted(set(days)))
    if mode=='k10':
        e=np.linspace(0,len(ud),11).astype(int)
        return [list(ud[e[i]:e[i+1]]) for i in range(10)]
    return [[d] for d in ud]
def heldout(x,y,days,mode):
    days=np.array(days); n=len(x)
    preds={k:np.full(n,np.nan) for k in ['M','M_B3','B0','B1m','B1a','B2m','B2a']}
    skipped=0
    for fd in folds_assign(days,mode):
        te=np.isin(days,fd); tr=~te
        if te.sum()==0: continue
        if tr.sum()<8 or len(set(x[tr]))<3: skipped+=1; continue
        s=sen(x[tr],y[tr]); preds['M'][te]=s*x[te]
        res=y[tr]-s*x[tr]; c=np.median(res); preds['M_B3'][te]=s*x[te]+c
        pm=predict(x[tr],y[tr],x[te],'median'); pa=predict(x[tr],y[tr],x[te],'mean')
        preds['B0'][te]=0; preds['B1m'][te]=pm['B1']; preds['B2m'][te]=pm['B2']
        preds['B1a'][te]=pa['B1']; preds['B2a'][te]=pa['B2']
    return preds,skipped
def metrics(y,p,idx,which):
    # which: dict of (M name, B name, metric)
    pass
def stat(y,ph,kind):
    if kind=='mae': e=np.abs(np.exp(y)-np.exp(ph)); return e.mean()
    if kind=='medae': return np.median(np.abs(y-ph))
    if kind=='mse': return np.mean((y-ph)**2)
def skills(y,p,sel):
    out={}
    for kind in ['mae','medae','mse']:
        fam='a' if kind=='mse' else 'm'
        m=stat(y[sel],p['M'][sel],kind)
        for B,key in [('B0','B0'),('B1','B1'+fam),('B2','B2'+fam),('B3',None)]:
            b=stat(y[sel],p['M_B3'][sel],kind) if B=='B3' else stat(y[sel],p[key][sel],kind)
            # B3 is a reference-model: skill of M relative to... here report skill of M vs B3
            out[(kind,B)]=np.nan if b==0 else 1-m/b
    return out
def cell_sel(x,cell):
    return {'pooled':np.ones(len(x),bool),'lt1':x<1,'ge1':x>=1}[cell]
def run_fit(i,mode='k10',B=4000,cells=('pooled','lt1','ge1')):
    f=P['fits'][i]; x=np.array(f['gapH']); y=np.array(f['y']); days=np.array(f['arrivalDay'])
    p,skipped=heldout(x,y,days,mode)
    ok=~np.isnan(p['M'])
    res={'n':int(len(x)),'ndays':int(len(set(days))),'skipped':skipped}
    s=sen(x,y); r2=1-np.sum((y-s*x)**2)/np.sum((y-y.mean())**2); res['r2']=r2; res['slope']=s
    res['cells']={}
    for cell in cells:
        sel=cell_sel(x,cell)&ok
        pt=skills(y,p,sel)
        ud=np.array(sorted(set(days[sel])))
        c={'n':int(sel.sum()),'ndays':int(len(ud)),'point':{f'{k[0]}|{k[1]}':v for k,v in pt.items()}}
        if B and sel.sum()>0:
            rng=np.random.default_rng(42)
            idxs=[np.where(sel&(days==d))[0] for d in ud]
            draws={k:[] for k in pt}; zero=0
            for _ in range(B):
                pick=rng.integers(0,len(ud),len(ud))
                ii=np.concatenate([idxs[j] for j in pick])
                sk=skills_idx(y,p,ii)
                for k,v in sk.items():
                    draws[k].append(v)
            c['ci']={}
            for k,v in draws.items():
                v=np.array(v); nz=int(np.isnan(v).sum())
                v=v[~np.isnan(v)]
                c['ci'][f'{k[0]}|{k[1]}']=[float(np.percentile(v,2.5)),float(np.percentile(v,97.5)),nz] if len(v) else None
        res['cells'][cell]=c
    return res,(x,y,days,p)
def skills_idx(y,p,ii):
    out={}
    for kind in ['mae','medae','mse']:
        fam='a' if kind=='mse' else 'm'
        m=stat(y[ii],p['M'][ii],kind)
        for B,key in [('B0','B0'),('B1','B1'+fam),('B2','B2'+fam),('B3',None)]:
            b=stat(y[ii],p['M_B3'][ii],kind) if B=='B3' else stat(y[ii],p[key][ii],kind)
            out[(kind,B)]=np.nan if b==0 else 1-m/b
    return out
if __name__=='__main__':
    out={}
    for i,name in enumerate(P['order']):
        r,_=run_fit(i)
        out[name]=r
        print(name,r['n'],r['ndays'],'skipped',r['skipped'],'R2 %.3f'%r['r2'])
        for cell,c in r['cells'].items():
            print(' ',cell,c['n'],c['ndays'])
            for k in ['mae|B0','mae|B1','mae|B2','mae|B3','mse|B0','mse|B1','mse|B2','medae|B0','medae|B1','medae|B2']:
                pt=c['point'][k]; ci=c['ci'][k]
                print('    %-10s %.3f'%(k,pt), None if ci is None else '[%.3f, %.3f] nz=%d'%tuple(ci))
    json.dump(out,open('audit_k10.json','w',encoding='utf-8'),default=float)
