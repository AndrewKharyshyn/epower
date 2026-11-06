import sys, json, numpy as np, pandas as pd, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0,'.')
from soc_spike import soc_spike_mask
from sklearn.linear_model import HuberRegressor
CI,CV,CS='[BMS] HV Battery Current (A)','[BMS] HV Battery voltage (V)','[BMS] HV State of charge (%)'
man=json.load(open('raw_manifest.json',encoding='utf-8'))
files=[f for f in man['files'] if f['role']=='canonical']
VAR=['A0','A1','A2','A3','A4','V1']
def tsec(s):
    t=pd.to_datetime(s,format='%H:%M:%S.%f',errors='coerce')
    x=(t-t.dt.normalize().iloc[0] if t.notna().any() else t).dt.total_seconds().values*1.0 if False else None
    sec=(t.dt.hour*3600+t.dt.minute*60+t.dt.second+t.dt.microsecond/1e6).values
    sec=np.asarray(sec,float)
    d=np.diff(sec); roll=np.concatenate([[0],np.cumsum(d<-43200)])  # midnight
    return sec+86400*roll
def near(tc,ts,vs,tol,mode):
    # ts sorted; returns values/NaN
    i=np.searchsorted(ts,tc)
    out=np.full(len(tc),np.nan)
    lo=np.clip(i-1,0,len(ts)-1); hi=np.clip(i,0,len(ts)-1)
    dl=tc-ts[lo]; dh=ts[hi]-tc
    dl=np.where(i-1>=0,dl,np.inf); dh=np.where(i<len(ts),dh,np.inf)
    # exact match counts as both
    if mode=='nearest':
        usel=dl<=dh; d=np.where(usel,dl,dh); idx=np.where(usel,lo,hi)
    elif mode=='back':
        # last sample at or before
        j=np.searchsorted(ts,tc,side='right')-1; ok=j>=0; jj=np.clip(j,0,None)
        d=np.where(ok,tc-ts[jj],np.inf); idx=jj
    else:
        j=np.searchsorted(ts,tc,side='left'); ok=j<len(ts); jj=np.clip(j,0,len(ts)-1)
        d=np.where(ok,ts[jj]-tc,np.inf); idx=jj
    m=d<=tol
    out[m]=vs[idx[m]]; return out
def interp(tc,ts,vs,gap):
    i=np.searchsorted(ts,tc); out=np.full(len(tc),np.nan)
    ex=(i<len(ts))&(ts[np.clip(i,0,len(ts)-1)]==tc)
    out[ex]=vs[np.clip(i,0,len(ts)-1)][ex]
    ok=(~ex)&(i>0)&(i<len(ts))
    a=np.clip(i-1,0,None); b=np.clip(i,0,len(ts)-1)
    ok&=(ts[b]-ts[a])<=gap
    w=(tc-ts[a])/np.where(ts[b]-ts[a]>0,ts[b]-ts[a],1)
    out[ok]=(vs[a]+w*(vs[b]-vs[a]))[ok]; return out
def est(I,V,S):
    Id=-I; k=Id>-5.0
    Id,V,S=Id[k],V[k],S[k]
    if len(Id)<300: return None
    p95=np.percentile(Id,95)
    if p95<40: return None
    h=HuberRegressor(epsilon=1.35,max_iter=500).fit(np.c_[S,Id],V)
    R=-h.coef_[1]
    return (round(R*1000,2) if 0<R<0.5 else np.nan), p95
rows=[]
for f in files:
    c=f['canonical']; p='raw/%s-%s-%s %s-%s-%s.csv'%(c[0:4],c[4:6],c[6:8],c[9:11],c[11:13],c[13:15])
    try: d=pd.read_csv(p,usecols=['time',CI,CV,CS])
    except Exception as e: continue
    d['t']=tsec(d['time']); d=d[d.t.notna()]
    def ser(c,lo=None,hi=None):
        x=d[['t',c]].dropna(); x=x[~x.t.duplicated(keep='first')]
        return x.t.values,x[c].values.astype(float)
    ti,I=ser(CI); m=np.abs(I)<900; ti,I=ti[m],I[m]
    tv,V=ser(CV); m=(V>=200)&(V<=450); tv,V=tv[m],V[m]
    ts,S=ser(CS); sp=soc_spike_mask(S,ts); ts,S=ts[~sp],S[~sp]
    r={'file':f['canonical']}
    if len(ti)<3 or len(tv)<2 or len(ts)<2:
        rows.append(r); continue
    for v in VAR:
        if v=='A0': Vv=near(ti,tv,V,1.5,'nearest'); Ss=near(ti,ts,S,1.5,'nearest')
        elif v=='A1': Vv=interp(ti,tv,V,3.0); Ss=interp(ti,ts,S,3.0)
        elif v=='V1': Vv=interp(ti,tv,V,3.0); Ss=near(ti,ts,S,1.5,'nearest')
        elif v=='A2': Vv=near(ti,tv,V,.3,'nearest'); Ss=near(ti,ts,S,.3,'nearest')
        elif v=='A3': Vv=near(ti,tv,V,1.5,'back'); Ss=near(ti,ts,S,1.5,'back')
        else: Vv=near(ti,tv,V,1.5,'fwd'); Ss=near(ti,ts,S,1.5,'fwd')
        ok=~(np.isnan(Vv)|np.isnan(Ss))
        e=est(I[ok],Vv[ok],Ss[ok])
        if e: r[v]=e[0]; r[v+'_p95']=e[1]
    rows.append(r)
pd.DataFrame(rows).to_csv('analyses/M578_audit/m505_r3_proxies.csv',index=False,encoding='utf-8')
