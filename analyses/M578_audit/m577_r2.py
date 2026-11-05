import sys, json, numpy as np, pandas as pd
from scipy import stats
sys.path.insert(0,'.')
import degradation_trends as dt
dm=pd.read_csv('drive_master.csv',low_memory=False,encoding='utf-8')
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
    n=len(y); XtXi=np.linalg.pinv(X.T@X); b=XtXi@X.T@y; e=y-X@b
    g=df[group].values; ug=np.unique(g); G=len(ug)
    As=[];idx=[];meat=np.zeros((X.shape[1],)*2)
    for k in ug:
        i=np.where(g==k)[0]; Xg=X[i]
        M=np.eye(len(i))-Xg@XtXi@Xg.T
        w,v=np.linalg.eigh((M+M.T)/2); w=np.where(w>1e-10,1/np.sqrt(np.clip(w,1e-10,None)),0)
        A=(v*w)@v.T; As.append(A); idx.append(i); u=Xg.T@(A@e[i]); meat+=np.outer(u,u)
    V=XtXi@meat@XtXi; tc=stats.t.ppf(.975,G-1); out={}
    for t in terms:
        j=1+cols.index(t); se=np.sqrt(V[j,j]); c=XtXi[:,j]
        W=np.zeros((n,G))
        for gi,(i,A) in enumerate(zip(idx,As)):
            a=A@X[i]@c
            col=-(X@(XtXi@X[i].T)); col[i,np.arange(len(i))]+=1.0
            W[:,gi]=col@a
        trB=(W**2).sum(); trB2=((W.T@W)**2).sum(); df=trB**2/trB2
        ts=stats.t.ppf(.975,df)
        out[t]=dict(est=b[j],se=se,ci95=[b[j]-tc*se,b[j]+tc*se],df_sat=df,ci95_sat=[b[j]-ts*se,b[j]+ts*se],mde=2.8*se)
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
def ns_basis(x,inner,bnd):
    kn=np.r_[bnd[0],inner,bnd[1]]; K=len(kn)
    def dk(k): return (np.clip(x-kn[k],0,None)**3-np.clip(x-kn[K-1],0,None)**3)/(kn[K-1]-kn[k])
    cols=[x]+[dk(k)-dk(K-2) for k in range(K-2)]
    return np.column_stack(cols)
terms=['step','slow']
colsA=['months','step','slow','T','I','soc','socr','lrest','first']
A,G=cr2(s,colsA,terms)
bd,_=boot(s,colsA,terms,'day'); bw,nw=boot(s,colsA,terms,'wk')
# model B
qs=s['T'].quantile([.25,.5,.75]).values
S=ns_basis(s['T'].values,qs,(lo,hi)); sb=s.copy()
for j in range(S.shape[1]): sb[f'ns{j}']=S[:,j]
nsc=[f'ns{j}' for j in range(S.shape[1])]
colsB=['months','step','slow']+nsc+['I','soc','socr','lrest','first']
B,_=cr2(sb,colsB,terms)
# C
q=s['T'].quantile(.25); c=s[s['T']<=q]; colsC=['step','slow','I','soc','socr']
cnt={a:[int((c.step==a).sum()),int(c[c.step==a].day.nunique())] for a in (0,1)}
Cok=all(cnt[a][0]>=10 and cnt[a][1]>=5 for a in (0,1))
C,Gc=cr2(c,colsC,terms) if Cok else (None,None)
Xv=np.c_[np.ones(len(s)),s[colsA].astype(float).values]
def vif(j):
    r=np.linalg.lstsq(np.delete(Xv,j,1),Xv[:,j],rcond=None)[0]; res=Xv[:,j]-np.delete(Xv,j,1)@r
    return float(1/(res@res/((Xv[:,j]-Xv[:,j].mean())**2).sum()))
V={t:vif(1+colsA.index(t)) for t in colsA}
corr_step_months=float(np.corrcoef(s.step,s.months)[0,1])
def ex(ci,sign): return (ci[0]>0) if sign>0 else (ci[1]<0)
lab={};flag={}
for t in terms:
    a=A[t]; sg=np.sign(a['est'])
    if V[t]>5 and t=='slow': lab[t]='not separable'
    else:
        others=[bd[t],B[t]['ci95'],bw[t]]+([C[t]['ci95']] if C else [])
        if not ex(a['ci95'],sg): lab[t]='not distinguishable from zero (not equivalence)'
        elif any(not ex(o,sg) for o in others): lab[t]='procedure-dependent'
        else: lab[t]='distinguishable from zero'
        if not C: lab[t]+=' [C not evaluable]'
    flag[t]=bool(ex(a['ci95'],sg) and not ex(a['ci95_sat'],sg))
res=dict(n_eligible_before_support=n0,support=[lo,hi],n_drives=len(s),n_days=int(s.day.nunique()),G=G,n_weeks=nw,
 A=A,boot_day=bd,boot_week=bw,B=B,B_knots=list(qs),nC=len(c),C_arm_drives_days=cnt,C_evaluable=Cok,C=C,Cq=float(q),
 vif=V,corr_step_months=corr_step_months,labels=lab,df_dependent_flag=flag)
json.dump(res,open('analyses/M578_audit/m577_r2_full.json','w',encoding='utf-8'),default=float,indent=1)
print(json.dumps(res,default=float,indent=1))
