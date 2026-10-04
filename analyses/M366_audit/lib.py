import pandas as pd, numpy as np, json, re, os, glob
ROOT="C:/Users/AndriiKharyshyn/Downloads/X-Trail Investigation/"
NEW=ROOT+"Repo/xtrail-repo/raw/"; ARC=ROOT+"raw_reexports_archived_2026-10-04/"
def key(n):
    m=re.search(r'(\d{4})-?(\d{2})-?(\d{2})[ _](\d{2})-?(\d{2})-?(\d{2})',n); return ''.join(m.groups())
def index(d): 
    return {key(f):d+f for f in os.listdir(d) if f.endswith('.csv') and re.search(r'\d{4}-?\d{2}-?\d{2}[ _]\d{2}-?\d{2}-?\d{2}',f)}
def tsec(s):
    p=s.astype(str).str.extract(r'(\d+):(\d+):(\d+(?:\.\d+)?)').astype(float)
    t=(p[0]*3600+p[1]*60+p[2]).values
    return np.unwrap(t,period=86400)
def load(path,ratecol):
    d=pd.read_csv(path,low_memory=False)
    t=tsec(d.iloc[:,0])
    cc=[c for c in d.columns if c=="Використане паливо (L)"]
    cnt=pd.to_numeric(d[cc[0]],errors='coerce').values if cc else None
    rate=pd.to_numeric(d[ratecol],errors='coerce').values if ratecol in d.columns else None
    return t,cnt,rate
RIGHT=True
def trip(path,ratecol,cap=5.0,trap=False):
    t,cnt,rate=load(path,ratecol)
    if cnt is None or rate is None: return None
    vc=np.where(~np.isnan(cnt))[0]
    if len(vc)<2: return None
    t0,t1=t[vc[0]],t[vc[-1]]; vcnt=cnt[vc[-1]]-cnt[vc[0]]
    vr=np.where(~np.isnan(rate))[0]
    tt=t[vr]; rr=rate[vr]
    dt=np.minimum(np.diff(tt,prepend=np.nan),cap)  # dt to previous valid rate sample
    inw=(tt>=t0)&(tt<=t1)&~np.isnan(dt)
    if trap:
        rp=np.concatenate([[np.nan],rr[:-1]]); v=np.sum((dt*(rr+rp)/2)[inw])/3600
    else: v=np.sum((dt*rr)[inw])/3600
    return vcnt,v
def boot(days,num,den,seed=42,B=4000):
    ud=sorted(set(days)); idx={d:i for i,d in enumerate(ud)}
    N=np.zeros(len(ud));D=np.zeros(len(ud))
    for d,n,m in zip(days,num,den): N[idx[d]]+=n; D[idx[d]]+=m
    rng=np.random.default_rng(seed); k=len(ud)
    est=N.sum()/D.sum(); out=[]
    for _ in range(B):
        s=rng.integers(0,k,k); out.append(N[s].sum()/D[s].sum())
    lo,hi=np.percentile(out,[2.5,97.5]); return est,lo,hi,k
