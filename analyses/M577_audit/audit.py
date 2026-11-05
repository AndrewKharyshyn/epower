import sys, json, numpy as np, pandas as pd
from scipy import stats
sys.path.insert(0,'.')
import degradation_trends as dt
dm=pd.read_csv('drive_master.csv',low_memory=False)
f=dm.copy()
f['_ts']=pd.to_datetime(f['date'].astype(str)+' '+f['time_start'].astype(str),errors='coerce')
f['_te']=pd.to_datetime(f['date'].astype(str)+' '+f['time_end'].astype(str),errors='coerce')
f=f.sort_values('_ts'); f['rest_h']=(f['_ts']-f['_te'].shift()).dt.total_seconds()/3600
d=dt._prep(f,'cell_spread_loaded_p95_mv',icol='peak_I_discharge').dropna(subset=['T','I']).copy()
d['soc']=d['rf_socmean_wtd_pct']; d['socr']=d['soc_max']-d['soc_min']
d['lrest']=np.log1p(d['rest_h'].clip(0,200)); d['first']=(d['rest_h']>4).astype(float)
d['step']=(d['date']>='2026-10-01').astype(float); d['slow']=(d['I_sample_period_s']>=1.05).astype(float)
d['wk']=d['date'].dt.strftime('%G-%V')
d=d.dropna(subset=['soc','socr','lrest','I_sample_period_s']).copy()
n0=len(d)
lo=max(d['T'][d.step==0].min(),d['T'][d.step==1].min()); hi=min(d['T'][d.step==0].max(),d['T'][d.step==1].max())
s=d[(d['T']>=lo)&(d['T']<=hi)].copy()
def cr2(df,cols,terms,group='day'):
    X=np.c_[np.ones(len(df)),df[cols].values.astype(float)]; y=df['y'].values.astype(float)
    XtXi=np.linalg.pinv(X.T@X); b=XtXi@X.T@y; e=y-X@b
    g=df[group].values; meat=np.zeros((X.shape[1],)*2)
    for k in np.unique(g):
        i=np.where(g==k)[0]; Xg=X[i]
        Hgg=Xg@XtXi@Xg.T; M=np.eye(len(i))-Hgg
        w,v=np.linalg.eigh((M+M.T)/2); w=np.where(w>1e-10,1/np.sqrt(np.clip(w,1e-10,None)),0)
        A=(v*w)@v.T; u=Xg.T@(A@e[i]); meat+=np.outer(u,u)
    V=XtXi@meat@XtXi; G=len(np.unique(g)); tc=stats.t.ppf(.975,G-1); out={}
    for t in terms:
        j=1+cols.index(t); se=np.sqrt(V[j,j]); out[t]=dict(est=b[j],se=se,ci95=[b[j]-tc*se,b[j]+tc*se])
    return out,G
def boot(df,cols,terms,group):
    rng=np.random.default_rng(42); keys=df[group].unique(); parts={k:g for k,g in df.groupby(group)}
    res={t:[] for t in terms}
    for _ in range(4000):
        ss=pd.concat([parts[k] for k in rng.choice(keys,len(keys))])
        A=np.c_[np.ones(len(ss)),ss[cols].values.astype(float)]
        bb=np.linalg.lstsq(A,ss['y'].values.astype(float),rcond=None)[0]
        for t in terms: res[t].append(bb[1+cols.index(t)])
    return {t:[float(np.percentile(v,2.5)),float(np.percentile(v,97.5))] for t,v in res.items()},len(keys)
colsA=['months','step','slow','T','I','soc','socr','lrest','first']
A,G=cr2(s,colsA,['step','slow'])
bd,_=boot(s,colsA,['step','slow'],'day'); bw,nw=boot(s,colsA,['step','slow'],'wk')
q=s['T'].quantile(.25); c=s[s['T']<=q]; colsC=['step','slow','I','soc','socr']
C,Gc=cr2(c,colsC,['step','slow'])
X=s[colsA].astype(float); X=np.c_[np.ones(len(X)),X.values]
def vif(j):
    r=np.linalg.lstsq(np.delete(X,j,1),X[:,j],rcond=None)[0]; res=X[:,j]-np.delete(X,j,1)@r
    return float(1/(res@res/((X[:,j]-X[:,j].mean())**2).sum()))
V={'step':vif(1+colsA.index('step')),'slow':vif(1+colsA.index('slow'))}
cnt={a:[int(((c.step==a)).sum()),int(c[c.step==a].day.nunique())] for a in (0,1)}
print(json.dumps(dict(n0=n0,support=[lo,hi],n=len(s),days=s.day.nunique(),A=A,boot_day=bd,boot_week=bd and bw,nweeks=nw,C=C,nC=len(c),daysC=c.day.nunique(),Cq=q,Carm=cnt,vif=V),default=float,indent=1))
json.dump(dict(n_drives=len(s),n_days=int(s.day.nunique()),support=[lo,hi],A=A,boot_day=bd,boot_week=bw,C=C,nC=len(c),C_arm_drives_days=cnt,vif=V),open('analyses/M577_audit/audit.json','w',encoding='utf-8'),default=float,indent=1)
