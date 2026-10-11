import json, numpy as np, pandas as pd, scipy.linalg as sl
import statsmodels.api as sm
rng_seed=20261011
D=pd.read_csv('drive_master.csv',encoding='utf-8',low_memory=False,dtype={'ens_outlier_v2':str})
D=D[D.ens_outlier_v2.fillna('')!='True'].copy()
D['date']=D['date'].astype(str)
D=D[D.date.notna() & (D.date!='nan')]
D['dt']=pd.to_datetime(D.date)
out={}
def design(df,y,T,I):
    df=df[df[y].notna()].copy()
    df['months']=(df.dt-df.dt.min()).dt.days/30.4375
    cols=['months']; 
    for c in (T,I):
        if df[c].notna().mean()>0.5: cols.append(c)
    df=df.dropna(subset=cols+[y])
    return df,cols
def cr1_fit(X,y,g):
    n,p=X.shape; M=np.linalg.inv(X.T@X); b=M@X.T@y; e=y-X@b
    S=pd.DataFrame(X*e[:,None]).groupby(g).sum().values
    G=S.shape[0]; V=G/(G-1)*(n-1)/(n-p)*M@(S.T@S)@M
    return b,np.sqrt(np.diag(V)),M,e
def msqrt_inv(A,mode='eig',tol=1e-10):
    w,v=np.linalg.eigh((A+A.T)/2)
    if mode=='eig': # exact inverse sqrt (error if <=0)
        return (v/np.sqrt(w))@v.T
    w2=np.where(w>tol,1/np.sqrt(np.clip(w,tol,None)),0.0)
    return (v*w2)@v.T
def cr2(X,y,g,mode='eig'):
    n,p=X.shape; M=np.linalg.inv(X.T@X); H=X@M@X.T; e=y-H@y
    IH=np.eye(n)-H; ids=pd.factorize(g)[0]; G=ids.max()+1
    c=M[:,0]; meat=np.zeros((p,p)); ws=[]; minev=1e9
    for k in range(G):
        ix=np.where(ids==k)[0]
        Ag=msqrt_inv(IH[np.ix_(ix,ix)],mode); minev=min(minev,np.linalg.eigvalsh(IH[np.ix_(ix,ix)]).min())
        Xg=X[ix]; s=Xg.T@Ag@e[ix]; meat+=np.outer(s,s)
        a=Ag@Xg@c; ws.append(IH[:,ix]@a)
    V=M@meat@M; W=np.column_stack(ws)
    df=(np.sum(W**2))**2/np.linalg.norm(W.T@W,'fro')**2
    return np.sqrt(V[0,0]),df,minev
def wild(X,y,g,B=4000,seed=42):
    rng=np.random.default_rng(seed); n,p=X.shape
    b,se,_,_=cr1_fit(X,y,g); t0=b[0]/se[0]
    Xr=X[:,1:]; br=np.linalg.lstsq(Xr,y,rcond=None)[0]; fr=Xr@br; er=y-fr
    ids=pd.factorize(g)[0]; G=ids.max()+1; Ind=np.zeros((n,G)); Ind[np.arange(n),ids]=1
    M=np.linalg.inv(X.T@X); P=M@X.T; fac=G/(G-1)*(n-1)/(n-p)
    ts=np.empty(B)
    for s in range(B):
        w=rng.choice([-1.0,1.0],size=G)[ids]
        ys=fr+w*er; bb=P@ys; ee=ys-X@bb
        Sg=Ind.T@(X*ee[:,None]); V=fac*M@(Sg.T@Sg)@M
        ts[s]=bb[0]/np.sqrt(V[0,0])
    return (1+np.sum(np.abs(ts)>=abs(t0)))/(B+1)
def pairs(X,y,cl,B=4000,seed=42):
    rng=np.random.default_rng(seed); u,inv=np.unique(cl,return_inverse=True); G=len(u)
    idx=[np.where(inv==k)[0] for k in range(G)]; r=np.empty(B)
    for s in range(B):
        pick=rng.integers(0,G,G); ii=np.concatenate([idx[k] for k in pick])
        r[s]=np.linalg.lstsq(X[ii],y[ii],rcond=None)[0][0+1] if False else np.linalg.lstsq(X[ii],y[ii],rcond=None)[0][1]
    return np.percentile(r,[2.5,97.5]).tolist()
ser={'cellSpread':('cell_spread_loaded_p95_mv','T_pack_mean_avg','peak_I_discharge'),
     'resistanceVreg':('vreg_R_pack_mohm','T_pack_mean_avg','vreg_I_p95_A')}
for name,(y,T,I) in ser.items():
    df,cols=design(D,y,T,I)
    X=np.column_stack([np.ones(len(df)),df[cols].values.astype(float)]); Y=df[y].values.astype(float)
    # months coefficient is column 1; reorder so months is col 0 for cr2/wild helpers
    Xm=np.column_stack([df['months'].values,X[:,[0]],X[:,2:]]) if len(cols)>1 else np.column_stack([df['months'].values,X[:,[0]]])
    g=df.date.values
    b,se,_,_=cr1_fit(Xm,Y,g)
    ref=sm.OLS(Y,X).fit(cov_type='cluster',cov_kwds={'groups':pd.factorize(g)[0]})
    se2,dfs,minev=cr2(Xm,Y,g,'eig')
    se2p,dfp,_=cr2(Xm,Y,g,'pinv')
    wk=pd.to_datetime(df.date).dt.isocalendar(); wkid=(wk.year.astype(str)+'-'+wk.week.astype(str)).values
    # pairs expects months at col 1: use X ordering [1,months,...]
    r={'n':len(df),'days':int(df.date.nunique()),'cols':cols,'slope':b[0],'cr1_se':se[0],'sm_cluster_slope':float(ref.params[1]),'sm_cluster_se':float(ref.bse[1]),
       'cr2_se':se2,'cr2_df':dfs,'cr2_pinv_se':se2p,'cr2_pinv_df':dfp,'min_eig_I_minus_Hgg':minev,
       'wild_p':wild(Xm,Y,g),'pairs_week_ci':pairs(X,Y,wkid),'pairs_day_ci':pairs(X,Y,g)}
    out[name]=r; print(name,r)
# KPIs
K=D.dropna(subset=['gross_throughput_kwh','gross_discharge_kwh','net_draw_kwh_corr']); K=K[K.gross_throughput_kwh>0]
def boot(df,stat,cl,B=4000,seed=42):
    rng=np.random.default_rng(seed); u,inv=np.unique(cl,return_inverse=True); G=len(u); idx=[np.where(inv==k)[0] for k in range(G)]
    r=np.empty(B)
    for s in range(B):
        ii=np.concatenate([idx[k] for k in rng.integers(0,G,G)]); r[s]=stat(df.iloc[ii])
    return np.percentile(r,[2.5,97.5]).tolist()
k1=lambda d:d.gross_throughput_kwh.sum()/d.gross_discharge_kwh.sum()
k2=lambda d:abs(d.net_draw_kwh_corr.sum())/d.gross_throughput_kwh.sum()
def wkid(df):
    w=df.dt.dt.isocalendar(); return (w.year.astype(str)+'-'+w.week.astype(str)).values
out['K1']={'n':len(K),'days':int(K.date.nunique()),'est':k1(K),'day':boot(K,k1,K.date.values),'week':boot(K,k1,wkid(K))}
out['K2']={'est':k2(K),'day':boot(K,k2,K.date.values),'week':boot(K,k2,wkid(K))}
S=D.dropna(subset=['soc_band']); md=lambda d:float(d.soc_band.median())
out['soc_median']={'n':len(S),'days':int(S.date.nunique()),'est':md(S),'day':boot(S,md,S.date.values),'week':boot(S,md,wkid(S))}
for k in ['K1','K2','soc_median']: print(k,out[k])
json.dump(out,open('analyses/M406_audit/auditor_results.json','w',encoding='utf-8'),indent=1,default=float)
