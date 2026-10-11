import re, json, sys, os
import numpy as np, pandas as pd
ROOT = os.getcwd()
CI="[BMS] HV Battery Current (A)"; CV="[BMS] HV Battery voltage (V)"; CS="[BMS] HV State of charge (%)"
def key(fn): return re.sub(r"\D","",fn)
rawmap = {key(f): f for f in os.listdir("raw") if f.endswith(".csv")}
def tsec(s):
    p = s.str.extract(r"^(\d+):(\d+):(\d+(?:\.\d+)?)$").astype(float)
    t = (p[0]*3600+p[1]*60+p[2]).to_numpy()
    # unwrap midnight
    out = t.copy(); off=0.0; last=None
    for k in range(len(t)):
        if np.isnan(t[k]): continue
        if last is not None and t[k] < last-3600: off += 86400
        last = t[k]; out[k]=t[k]+off
    return out
def load(fname):
    f = rawmap[key(fname)]
    d = pd.read_csv(os.path.join("raw",f), usecols=lambda c: c in ("time",CI,CV,CS), encoding="utf-8")
    for cc in (CI,CV,CS):
        if cc not in d.columns: d[cc]=np.nan
    d["t"] = tsec(d["time"].astype(str))
    return d
def pairs(d, cap=5.0):
    c = d[["t",CI]].dropna(); c = c[c[CI].abs()<900]
    v = d[["t",CV]].dropna(); v = v[(v[CV]>=200)&(v[CV]<=450)]
    if len(c)==0 or len(v)==0: return None
    ct=c["t"].to_numpy(); ci=c[CI].to_numpy()
    o=np.argsort(v["t"].to_numpy(),kind="stable"); vt=v["t"].to_numpy()[o]
    idx=np.searchsorted(vt,ct); a=np.clip(idx-1,0,len(vt)-1); b=np.clip(idx,0,len(vt)-1)
    nn=np.where(np.abs(vt[a]-ct)<=np.abs(vt[b]-ct),a,b)
    ok=np.abs(vt[nn]-ct)<=1.5
    pt=ct[ok]; pi=ci[ok]
    return pt,pi
def integ(pt,pi,cap=5.0):
    if len(pt)<2: return None
    dt=np.diff(pt); dt=np.clip(dt,0,cap) if cap else np.clip(dt,0,None)
    dth=dt/3600; i0=pi[:-1]; i1=pi[1:]
    I2=np.sum(dth*(i0*i0+i0*i1+i1*i1)/3); q=np.sum(dth*(i0+i1)/2)
    return I2,q
m=pd.read_csv("drive_master.csv",dtype={"ens_outlier_v2":str})
m=m.copy(); m["dt0"]=pd.to_datetime(m["date"]+" "+m["time_start"])
cache={}
for _,r in m.iterrows():
    try: d=load(r["file"])
    except KeyError: continue
    cache[r["file"]]=(d,pairs(d))
def claim12(cap=5.0, drop_odd=False):
    rows=[]
    for _,r in m.iterrows():
        if r.ens_outlier_v2!="False": continue
        if r[["net_draw_kwh","soc_start","soc_end","V_pack_median","integr_time_h"]].isna().any(): continue
        if r.file not in cache or cache[r.file][1] is None: continue
        pt,pi=cache[r.file][1]
        if len(pt)<2: continue
        if drop_odd and len(pt)%2==1: continue
        I2,q=integ(pt,pi,cap)
        rows.append(dict(file=r.file,y=r.net_draw_kwh,z=(r.soc_start-r.soc_end)/100,off=r.V_pack_median*r.integr_time_h/1000,loss=I2/1000,q=q,
            dt0=r.dt0,dur=r.duration_s,s0=r.soc_start,s1=r.soc_end,npair=len(pt)))
    D=pd.DataFrame(rows)
    X=D[["z","off","loss"]].to_numpy().copy(); X[:,2]*=-1
    beta=np.linalg.lstsq(X,D.y.to_numpy(),rcond=None)[0]
    c1=dict(K=beta[0],c=beta[1],R=beta[2],n=len(D))
    D=D.sort_values("dt0").reset_index(drop=True)
    J=[];Q=[]
    for k in range(len(D)-1):
        i,j=D.iloc[k],D.iloc[k+1]
        rest=(j.dt0-(i.dt0+pd.Timedelta(seconds=i.dur))).total_seconds()
        if rest>=30: J.append(j.s0-i.s1); Q.append(i.q)
    J=np.array(J);Q=np.array(Q)
    A=np.c_[np.ones(len(Q)),Q]; a,b=np.linalg.lstsq(A,J,rcond=None)[0]
    c2=dict(b=b,a=a,n=len(J))
    return c1,c2,D
c1,c2,D=claim12(5.0)
c1n,c2n,_=claim12(None)
c1o,c2o,_=claim12(5.0,True)
# bootstrap-free; claim 3
def claim3():
    E=[]; nseg=0
    for _,r in m.iterrows():
        if r.ens_outlier_v2!="False" or r.file not in cache: continue
        d=cache[r.file][0]
        c=d[["t",CI]].dropna().sort_values("t",kind="stable"); 
        s=d[["t",CS]].dropna(); s=s[s[CS]>0].sort_values("t",kind="stable")
        if len(c)<=20 or len(s)==0: continue
        ct=c.t.to_numpy(); ci=c[CI].to_numpy(); st=s.t.to_numpy(); sv=s[CS].to_numpy()
        br=np.where(np.diff(ct)>10)[0]+1
        starts=np.r_[0,br]; ends=np.r_[br,len(ct)]
        for a,b in zip(starts,ends):
            if b-a<=20: continue
            t=ct[a:b]; i=ci[a:b]
            Q=np.r_[0,np.cumsum(np.diff(t)/3600*(i[1:]+i[:-1])/2)]
            msk=(st>=t[0])&(st<=t[-1])
            tt=st[msk]; vv=sv[msk]
            if len(vv)<10: continue
            ev=[]
            for k in range(len(vv)-1):
                if abs(abs(vv[k+1]-vv[k])-0.5)<1e-6:
                    te=(tt[k]+tt[k+1])/2
                    ev.append(((vv[k]+vv[k+1])/2,np.interp(te,t,Q),(te-t[0])/3600))
            if len(ev)<3: continue
            ev=np.array(ev); cen=ev[:,0].mean()
            lv=ev[:,0]-ev[:,0].mean(); q=ev[:,1]-ev[:,1].mean(); th=ev[:,2]-ev[:,2].mean()
            E.append(np.c_[q,lv,th,lv*(cen-55)/10]); nseg+=1
    E=np.vstack(E)
    beta=np.linalg.lstsq(E[:,1:],E[:,0],rcond=None)[0]
    return dict(ah_per100=100*beta[0],slope_per10=100*beta[2],n_events=len(E),n_segments=nseg,c_th=beta[1])
c3=claim3()
res=dict(claim1=c1,claim2=c2,claim3={k:c3[k] for k in("ah_per100","slope_per10","n_events")},
 extra=dict(n_segments=c3["n_segments"],no_dt_cap=dict(c1=c1n,c2=c2n),drop_odd_pairs=dict(c1=c1o,c2=c2o,n_dropped=c1["n"]-c1o["n"])),
 choices="Midnight-unwrapped times; nearest-V by abs time diff (tie->earlier); SoC samples restricted to [first,last] current time of segment; segments need >20 current samples and >=10 SoC samples in-segment; events detected on consecutive SoC samples (sorted); demeaning over events; claim2 population = claim1 population, consecutive in sorted order, gaps over dropped drives bridged only if adjacent in population; q uses trapezoid with dt cap 5 s; SoC sample must be >0.")
json.dump(res,open("analyses/M404_audit/auditor_results.json","w",encoding="utf-8"),indent=1,default=float)
print(json.dumps(res,indent=1,default=float))
