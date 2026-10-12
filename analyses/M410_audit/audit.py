import sys, json, numpy as np, pandas as pd
from scipy.optimize import minimize_scalar
ROOT=r"C:\Users\AndriiKharyshyn\Downloads\X-Trail Investigation\Repo\xtrail-repo"
sys.path.insert(0,ROOT)
import degradation_trends as dt
dm=pd.read_csv(ROOT+r"\drive_master.csv",low_memory=False)

def design(ycol,icol):
    d=dt._prep(dm,ycol,icol=icol)
    use=dt._covars_present(d,('T','I'))
    d=d.dropna(subset=list(use)).copy()
    d['dnum']=(pd.to_datetime(d['day'])-pd.to_datetime(d['day']).min()).dt.days
    X=np.column_stack([np.ones(len(d)),d['months'].values]+[d[c].values for c in use])
    return d,X,d['y'].values,use

def corr(a,b,w=None):
    if w is None: return float(np.corrcoef(a,b)[0,1])
    w=np.asarray(w,float); ma=(w*a).sum()/w.sum(); mb=(w*b).sum()/w.sum()
    return float((w*(a-ma)*(b-mb)).sum()/np.sqrt((w*(a-ma)**2).sum()*(w*(b-mb)**2).sum()))

def daymeans(dnum,r):
    s=pd.Series(r).groupby(dnum).mean()
    return s.index.values.astype(int), s.values

def analyse(ycol,icol,seeds=(1,2,3,42)):
    d,X,y,use=design(ycol,icol)
    n,p=X.shape; dn=d['dnum'].values
    beta=np.linalg.lstsq(X,y,rcond=None)[0]; e=y-X@beta
    t,r=daymeans(dn,e); G=len(t)
    out=dict(n=int(n),G=int(G),p=int(p),use=use,ols_months=float(beta[1]))
    D=np.abs(t[:,None]-t[None,:]); iu=np.triu_indices(G,1); dist=D[iu]
    ri=r[iu[0]]; rj=r[iu[1]]
    out['rho']={}
    for g in (1,2,3):
        m=dist==g; out['rho'][g]=(corr(ri[m],rj[m]),int(m.sum()))
    m=(dist>=1)&(dist<=3); out['rho']['1-3']=(corr(ri[m],rj[m]),int(m.sum()))
    bins=[(1,1),(2,2),(3,4),(5,7),(8,14),(15,10**9)]
    sq=0.5*(ri-rj)**2
    out['vario']=[]
    for lo,hi in bins:
        m=(dist>=lo)&(dist<=hi); out['vario'].append((f"{lo}-{hi}",float(sq[m].mean()) if m.any() else None,int(m.sum())))
    out['sill']=float(np.var(r,ddof=1))
    # HAC
    XtXi=np.linalg.inv(X.T@X)
    S=np.zeros((G,p)); idx={tt:i for i,tt in enumerate(t)}
    for k in range(n): S[idx[dn[k]]]+=X[k]*e[k]
    fac=G/(G-1)*(n-1)/(n-p)
    out['hac']={}
    for L in (3,7,14):
        W=np.where(D<=L,1-D/(L+1),0.0)
        meat=S.T@W@S
        V=fac*XtXi@meat@XtXi
        out['hac'][L]=float(np.sqrt(V[1,1]))
    # cluster-robust CR1 (L=0) for reference
    meat0=S.T@S; out['hac'][0]=float(np.sqrt((fac*XtXi@meat0@XtXi)[1,1]))
    # AR1 GLS on day means
    dfm=pd.DataFrame(X); dfm['y']=y; dfm['d']=dn
    g=dfm.groupby('d').mean(); Xd=g[list(range(p))].values; yd=g['y'].values; td=g.index.values
    Dd=np.abs(td[:,None]-td[None,:]); nd=len(td)
    def fit(rho):
        R=rho**Dd; Ri=np.linalg.inv(R)
        A=Xd.T@Ri@Xd; b=np.linalg.solve(A,Xd.T@Ri@yd); res=yd-Xd@b
        s2=res@Ri@res/(nd-p)
        reml=-0.5*(np.linalg.slogdet(R)[1]+np.linalg.slogdet(A)[1]+(nd-p)*np.log(s2))
        return reml,b,s2,A
    rr=minimize_scalar(lambda r_:-fit(r_)[0],bounds=(0,0.95),method='bounded',options=dict(xatol=1e-8))
    rho=rr.x; reml,b,s2,A=fit(rho)
    # check boundaries
    grid=[(x,fit(x)[0]) for x in np.linspace(0,0.95,20)]
    se=float(np.sqrt((s2*np.linalg.inv(A))[1,1]))
    out['ar1']=dict(rho=float(rho),slope=float(b[1]),se=se,n_days=int(nd),reml_at0=float(fit(0.0)[0]),reml_at_hat=float(reml),reml_at095=float(fit(0.95)[0]))
    # bootstrap
    dts=pd.to_datetime(d['day']); wk=(dts.dt.isocalendar().year.astype(int)*100+dts.dt.isocalendar().week.astype(int)).values
    weeks=np.unique(wk); nw=len(weeks); wi=np.searchsorted(weeks,wk)
    # day -> week of day (a day belongs to exactly one week)
    dayweek=pd.Series(wi).groupby(dn).first()
    pairs1=np.where(dist==1)[0]
    ia=iu[0][pairs1]; ib=iu[1][pairs1]   # t sorted ascending so ia is first day
    pwk=dayweek.loc[t[ia]].values
    res={}
    for seed in seeds:
        rng=np.random.default_rng(seed); vals=[]
        for b_ in range(4000):
            cnt=rng.multinomial(nw,np.ones(nw)/nw)
            w=cnt[wi].astype(float)
            sw=np.sqrt(w); 
            bb=np.linalg.lstsq(X*sw[:,None],y*sw,rcond=None)[0]
            ee=y-X@bb
            _,rb=daymeans(dn,ee)
            pw=cnt[pwk].astype(float)
            if pw.sum()==0: continue
            vals.append(corr(rb[ia],rb[ib],pw))
        vals=np.array(vals)
        res[seed]=dict(lo=float(np.percentile(vals,2.5)),hi=float(np.percentile(vals,97.5)),med=float(np.median(vals)),nvalid=int(np.isfinite(vals).sum()),nan=int((~np.isfinite(vals)).sum()))
    out['boot']=res; out['n_weeks']=int(nw)
    out['dist1_pairs']=int(len(pairs1))
    return out

if __name__=="__main__":
    R={}
    R['spread']=analyse('cell_spread_loaded_p95_mv','peak_I_discharge')
    R['resist']=analyse('vreg_R_pack_mohm','vreg_I_p95_A')
    json.dump(R,open(ROOT+r"\analyses\M410_audit\out.json","w",encoding="utf-8"),indent=1,default=str)
    print(json.dumps(R,indent=1,default=str))
