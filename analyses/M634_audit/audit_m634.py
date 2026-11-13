import numpy as np, pandas as pd, json, statsmodels.api as sm
from scipy import stats
m=pd.read_csv('drive_master.csv'); p=pd.read_csv('powerfade_density.csv',usecols=['file','eff_dt_s','coverage_frac'])
m['bad']=m.ens_outlier_v2.map(lambda v: v is True or str(v).lower()=='true')
m['day']=m.date.astype(str).str[:10]
fin=lambda d,c:np.isfinite(pd.to_numeric(d[c],errors='coerce'))
def mk(cols,den):
    d=m[~m.bad].copy()
    if den: d=d.merge(p.drop_duplicates('file'),on='file')
    for c in cols: d[c]=pd.to_numeric(d[c],errors='coerce')
    d=d[np.all([np.isfinite(d[c]) for c in cols],axis=0)&d.day.str.len().eq(10)].copy()
    d['dt']=pd.to_datetime(d.day); d['months']=(d.dt-d.dt.min()).dt.days/30.44
    return d.reset_index(drop=True)
R=mk(['vreg_R_pack_mohm','T_pack_mean_avg','vreg_I_p95_A'],True); R=R[np.isfinite(R.eff_dt_s)&np.isfinite(R.coverage_frac)].reset_index(drop=True)
C=mk(['cell_spread_loaded_p95_mv','T_pack_mean_avg','peak_I_discharge'],False)
def ns(T,lo,hi):
    xi=[lo]+[k for k in (10,20,30) if lo<k<hi]+[hi]; K=len(xi)
    d=lambda k,x:(np.maximum(x-xi[k],0)**3-np.maximum(x-xi[-1],0)**3)/(xi[-1]-xi[k])
    return np.column_stack([T]+[d(k,T)-d(K-2,T) for k in range(K-2)])
def design(d,s,ctl,I,extra,bnd):
    T=d.T_pack_mean_avg.values; base=[np.ones(len(d)),d.months.values]
    if ctl=='T-arr': t=[1/(T+273.15)]
    elif ctl=='T-lin': t=[T]
    elif ctl=='T-quad': t=[T,T**2]
    else: t=list(ns(T,*bnd).T)
    return np.column_stack(base+t+[d[I].values]+[d[c].values for c in extra])
def fit(d,y,ctl,I,extra,bnd=None):
    X=design(d,0,ctl,I,extra,bnd or (d.T_pack_mean_avg.min(),d.T_pack_mean_avg.max()))
    if ctl=='T-arr':
        b=np.linalg.lstsq(X,np.log(y),rcond=None)[0]; sm_=np.mean(np.exp(np.log(y)-X@b))
        return sm_*np.exp(X.mean(0)@b)*b[1],(b,sm_,X)
    b=np.linalg.lstsq(X,y,rcond=None)[0]; return b[1],(b,1,X)
def boot(d,yc,ctl,I,extra):
    days=d.day.unique(); g={k:v.values for k,v in d.groupby('day').groups.items()}
    rng=np.random.default_rng(42); out=[]
    for _ in range(4000):
        idx=np.concatenate([g[x] for x in rng.choice(days,len(days))]); dd=d.iloc[idx].reset_index(drop=True)
        try: out.append(fit(dd,dd[yc].values,ctl,I,extra)[0])
        except Exception: pass
    return np.percentile(out,[2.5,97.5]).tolist()
def cv(d,yc,ctl,I,extra):
    days=np.array(sorted(d.day.unique())); K=min(10,len(days)); perm=np.random.default_rng(42).permutation(len(days))
    fold=np.empty(len(days),int)
    for r in range(len(days)): fold[perm[r]]=r%K
    fm=d.day.map(dict(zip(days,fold))).values; res=[]
    for k in range(K):
        tr,te=d[fm!=k],d[fm==k]; lo,hi=tr.T_pack_mean_avg.min(),tr.T_pack_mean_avg.max()
        te=te.copy(); te['T_pack_mean_avg']=te.T_pack_mean_avg.clip(lo,hi)
        _,(b,s,_)=fit(tr,tr[yc].values,ctl,I,extra,(lo,hi))
        Xt=design(te,0,ctl,I,extra,(lo,hi)); pr=Xt@b
        if ctl=='T-arr': pr=s*np.exp(pr)
        res.append(np.sqrt(np.mean((te[yc].values-pr)**2)))
    return np.array(res)
out={}
for nm,d,yc,I,ex in [('S0',R,'vreg_R_pack_mohm','vreg_I_p95_A',[]),('S1',R,'vreg_R_pack_mohm','vreg_I_p95_A',['eff_dt_s','coverage_frac']),('CS',C,'cell_spread_loaded_p95_mv','peak_I_discharge',[])]:
    out[nm]={'n':len(d),'days':int(d.day.nunique())}; cvs={}
    for ctl in ['T-lin','T-quad','T-arr','T-spl']:
        y=d[yc].values; est,(b,s,X)=fit(d,y,ctl,I,ex); r={'slope':round(est,4)}
        if ctl!='T-arr':
            lab=pd.factorize(d.day)[0]; mod=sm.OLS(y,X).fit(cov_type='cluster',cov_kwds={'groups':lab,'use_correction':True,'df_correction':True},use_t=True)
            G=lab.max()+1; se=mod.bse[1]; tq=stats.t.ppf(.975,G-1); r['cr1']=[round(b[1]-tq*se,4),round(b[1]+tq*se,4)]
        r['boot']=[round(x,4) for x in boot(d,yc,ctl,I,ex)]
        cvs[ctl]=cv(d,yc,ctl,I,ex); r['cv_rmse']=round(cvs[ctl].mean(),4)
        if ctl=='T-spl' : r['knots_n']=X.shape[1]
        out[nm][ctl]=r
    if nm=='S0':
        for ctl in ['T-lin','T-quad','T-spl']:
            df=cvs[ctl]-cvs['T-arr']; out[nm][ctl]['dRMSE_vs_arr']=[round(df.mean(),4),round(df.std(ddof=1)/np.sqrt(len(df)),4)]
print(json.dumps(out))
