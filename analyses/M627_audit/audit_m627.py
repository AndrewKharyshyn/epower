import pandas as pd, numpy as np, json, os
R='raw_only/'
dm=pd.read_csv('drive_master.csv',usecols=['file','date'])
dm['d']=dm['date'].astype(str).str[:10]
KI,KO='[BMS] Input possible power (kW)','[BMS] Output possible power (kW)'
HI,HO='[BMS] Input possible power (hp)','[BMS] Output possible power (hp)'
IC,VC='[BMS] HV Battery Current (A)','[BMS] HV Battery voltage (V)'
def tsec(s):
    t=pd.to_timedelta(s.astype(str),errors='coerce').dt.total_seconds().to_numpy()
    return t
def nn(tq,ts,max_s):
    # nearest index in sorted ts for each tq; returns idx, ok
    i=np.searchsorted(ts,tq); i0=np.clip(i-1,0,len(ts)-1); i1=np.clip(i,0,len(ts)-1)
    d0=np.abs(tq-ts[i0]); d1=np.abs(tq-ts[i1])
    idx=np.where(d1<d0,i1,i0); d=np.minimum(d0,d1)
    return idx,d<=max_s
era={};stats={}
ev={e:{'c':[], 'd':[]} for e in ('hp','kW')}
q={e:dict(n=0,g=0,g2=0) for e in ('hp','kW')}
ceil={e:{'in':[0,0],'out':[0,0]} for e in ('hp','kW')}
dates={'hp':[], 'kW':[]}; none=0; nodata=[]
for f,d in zip(dm.file,dm.d):
    p=R+f
    if not os.path.exists(p): nodata.append(f); continue
    hdr=pd.read_csv(p,nrows=0).columns
    if KI in hdr and KO in hdr: e='kW'
    elif HI in hdr and HO in hdr: e='hp'
    else: none+=1; continue
    ci,co=(KI,KO) if e=='kW' else (HI,HO)
    df=pd.read_csv(p,usecols=['time',IC,VC,ci,co],low_memory=False)
    dates[e].append((d,f))
    t=tsec(df['time']); 
    # midnight wrap
    ok=~np.isnan(t); t=t.copy()
    tt=t[ok]; wraps=np.cumsum(np.r_[0,(np.diff(tt)<-43200)]); t[ok]=tt+86400*wraps
    df['t']=t
    k=1.0 if e=='kW' else 0.73549875
    I=pd.to_numeric(df[IC],errors='coerce'); V=pd.to_numeric(df[VC],errors='coerce')
    ic=df[I.notna()&(I.abs()<900)&df.t.notna()]; ic=ic.assign(I=I[ic.index])
    vc=df[V.notna()&(V>=200)&(V<=450)&df.t.notna()]; vc=vc.assign(V=V[vc.index])
    pk=None
    if len(ic) and len(vc):
        vc=vc.sort_values('t',kind='stable'); ic=ic.sort_values('t',kind='stable')
        idx,m=nn(ic.t.to_numpy(),vc.t.to_numpy(),1.5)
        pt=ic.t.to_numpy()[m]; pk=ic.I.to_numpy()[m]*vc.V.to_numpy()[idx[m]]/1000
    for dirn,col in (('in',ci),('out',co)):
        x=pd.to_numeric(df[col],errors='coerce'); mk=np.isfinite(x)&df.t.notna()
        raw=x[mk].to_numpy(); kw=raw*k; tq=df.t[mk].to_numpy()
        # quant
        q[e]['n']+=len(kw)
        q[e]['g']+=int((np.abs(kw/0.05-np.round(kw/0.05))*0.05<=1e-6).sum())
        if e=='hp':
            k2=raw*0.745699872; q[e]['g2']+=int((np.abs(k2/0.05-np.round(k2/0.05))*0.05<=1e-6).sum())
        ceil[e][dirn][0]+=int((kw>=63.70).sum()); ceil[e][dirn][1]+=len(kw)
        if pk is None or len(pt)==0 or len(kw)==0: continue
        o=np.argsort(pt,kind='stable'); pts=pt[o]; pks=pk[o]
        idx2,m2=nn(tq,pts,2.0)
        P=pks[idx2][m2]; K=kw[m2]
        if dirn=='in': s=P>0.1; meas=P[s]
        else: s=P<-0.1; meas=-P[s]
        u=meas/K[s]
        ev[e]['c' if dirn=='in' else 'd'].append((u,f,d))
out={'drives_per_era':{e:len(dates[e]) for e in dates},'none':none,'missing_files':len(nodata),
 'date_range':{e:[min(x[0] for x in dates[e]),max(x[0] for x in dates[e])] for e in dates if dates[e]},
 'quant':{e:{'n':q[e]['n'],'on_0.05':q[e]['g'],**({'on_0.05_alt':q[e]['g2']} if e=='hp' else {})} for e in q},
 'ceil63.7':{e:{k:{'ge':v[0],'tot':v[1]} for k,v in ceil[e].items()} for e in ceil}}
def summ(L):
    if not L: return None
    u=np.concatenate([a for a,_,_ in L]); 
    ff=[f for a,f,_ in L if len(a)]; dd={d for a,_,d in L if len(a)}
    return dict(n=len(u),drives=len(ff),days=len(dd),med=round(float(np.median(u)),3),p95=round(float(np.percentile(u,95)),3),max=round(float(u.max()),3),gt1=int((u>1).sum()))
for key,nm in (('c','charge'),('d','discharge')):
    out[nm]={'hp':summ(ev['hp'][key]),'kW':summ(ev['kW'][key]),'pooled':summ(ev['hp'][key]+ev['kW'][key])}
print(json.dumps(out))
