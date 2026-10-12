import numpy as np, pandas as pd, json
CUR='[BMS] HV Battery Current (A)'; VOL='[BMS] HV Battery voltage (V)'
m=pd.read_csv('drive_master.csv',encoding='utf-8',usecols=['file','date','gross_discharge_kwh','gross_charge_kwh'])
m=m[np.isfinite(m.gross_discharge_kwh)].reset_index(drop=True)

def tsec(s):
    p=s.str.split(':',expand=True).astype(float)
    t=(p[0]*3600+p[1]*60+p[2]).to_numpy()
    # midnight unwrap: a backwards jump > 12 h means day rollover
    d=np.diff(t,prepend=t[0]); wraps=np.cumsum(d<-43200)
    return t+86400*wraps

def load(f):
    r=pd.read_csv('raw_only/'+f,encoding='utf-8',usecols=['time',CUR,VOL])
    t=tsec(r['time'])
    ci=r[CUR].notna().to_numpy(); vi=r[VOL].notna().to_numpy()
    tc=t[ci]; c=r[CUR].to_numpy(float)[ci]
    k=np.abs(c)<900; tc,c=tc[k],c[k]
    o=np.argsort(tc,kind='stable'); tc,c=tc[o],c[o]
    tv=t[vi]; v=r[VOL].to_numpy(float)[vi]
    k=(v>=200)&(v<=450); tv,v=tv[k],v[k]
    o=np.argsort(tv,kind='stable'); tv,v=tv[o],v[o]
    return tc,c,tv,v

def match(tc,tv,v,mode):
    n=len(tv)
    if n==0: return np.zeros(len(tc),bool),np.zeros(len(tc))
    j=np.searchsorted(tv,tc,side='right')  # tv[j-1]<=tc
    if mode=='back':
        jb=j-1; ok=jb>=0
        jj=np.clip(jb,0,n-1); ok&=(tc-tv[jj])<=1.5
        return ok,v[jj]
    jb=np.clip(j-1,0,n-1); jf=np.clip(j,0,n-1)
    db=np.where(j-1>=0,np.abs(tc-tv[jb]),np.inf); df=np.where(j<n,np.abs(tv[jf]-tc),np.inf)
    use_b=db<=df  # tie -> earlier sample
    jj=np.where(use_b,jb,jf); d=np.where(use_b,db,df)
    return d<=1.5,v[jj]

def energy(t,P,cap=5.0,scheme='lin',nobridge=False):
    if len(t)<2: return 0.0,0.0
    diff=np.diff(t); dt=np.minimum(diff,cap)/3600.0
    if nobridge: dt=np.where(diff>5.0,0.0,diff/3600.0)
    p0=P[:-1]; p1=P[1:]
    if scheme=='left':
        return float(np.sum(dt*np.where(p0>0,p0,0))),float(np.sum(dt*np.where(p0<0,-p0,0)))
    if scheme=='right':
        return float(np.sum(dt*np.where(p1>0,p1,0))),float(np.sum(dt*np.where(p1<0,-p1,0)))
    cross=(p0*p1)<0
    s=dt*(p0+p1)/2
    dis=np.where(~cross&(s>0),s,0.0); chg=np.where(~cross&(s<0),-s,0.0)
    den=2*(np.abs(p0)+np.abs(p1)); den=np.where(den==0,1,den)
    pp=np.where(p0>0,p0,p1); pn=np.where(p0<0,p0,p1)
    dis=dis+np.where(cross,dt*pp**2/den,0.0); chg=chg+np.where(cross,dt*pn**2/den,0.0)
    return float(dis.sum()),float(chg.sum())

SC={'S0':{}, 'A3':{'mode':'back'}, 'B1':{'scheme':'left'}, 'B2':{'scheme':'right'},
    'C1':{'nobridge':True}, 'cap3':{'cap':3.0}, 'cap10':{'cap':10.0}, 'D1':{'off':-0.3834}}
res={k:np.zeros((len(m),2)) for k in SC}
gaps={'n5':0,'d5':0.0,'n10':0,'d10':0.0,'n30':0,'d30':0.0,'beyond5':0.0}
for i,f in enumerate(m.file):
    tc,c,tv,v=load(f)
    cache={}
    for name,o in SC.items():
        mode=o.get('mode','near')
        if mode not in cache: cache[mode]=match(tc,tv,v,mode)
        ok,vv=cache[mode]
        t=tc[ok]; cc=c[ok]; V=vv[ok]
        Id=-cc-o.get('off',0.0)
        P=Id*V/1000.0
        res[name][i]=energy(t,P,o.get('cap',5.0),o.get('scheme','lin'),o.get('nobridge',False))
        if name=='S0' and len(t)>1:
            d=np.diff(t)
            for th in (5,10,30):
                g=d[d>th]; gaps['n%d'%th]+=len(g); gaps['d%d'%th]+=float(g.sum())
            gaps['beyond5']+=float((d[d>5]-5).sum())
S0=res['S0']
dev=np.maximum(np.abs(S0[:,0]-m.gross_discharge_kwh.values),np.abs(S0[:,1]-m.gross_charge_kwh.values))
out={'n_drives':len(m),'n_days':int(m.date.nunique()),
     'baseline_vs_master':{'max_abs_dev_kwh':float(dev.max()),'n_above_5e-4':int((dev>5e-4).sum()),
        'worst_files':m.file[np.argsort(-dev)[:5]].tolist(),'worst_devs':np.sort(dev)[::-1][:5].tolist()},
     'gaps_baseline':{k:(round(v,3) if isinstance(v,float) else v) for k,v in gaps.items()}}
thr0=S0.sum(1)
days=m.date.values; ud,inv=np.unique(days,return_inverse=True)
b_day=np.bincount(inv,weights=thr0,minlength=len(ud))
rng=np.random.default_rng(42)
idx=rng.integers(0,len(ud),size=(4000,len(ud)))
sc_out={}
big=thr0>=0.1
for k in SC:
    r=res[k]; thr=r.sum(1)
    s_day=np.bincount(inv,weights=thr,minlength=len(ud))
    boot=s_day[idx].sum(1)/b_day[idx].sum(1)
    lo,hi=np.percentile(boot,[2.5,97.5])
    sc_out[k]={'discharge_kwh':round(float(r[:,0].sum()),4),'charge_kwh':round(float(r[:,1].sum()),4),
      'throughput_kwh':round(float(thr.sum()),4),'ratio':round(float(thr.sum()/thr0.sum()),6),
      'median_drive_ratio':round(float(np.median(thr[big]/thr0[big])),6),'n_drives_ge_0.1':int(big.sum()),
      'ratio_ci95':[round(float(lo),6),round(float(hi),6)]}
out['scenarios']=sc_out
out['readings']=['time unwrapped across midnight then stable sort','nearest-voltage tie -> earlier sample; |dt|<=1.5 s inclusive',
 'first matched sample dt=0; dt for interval = diff to previous matched sample','D1 offset: Id=-I+0.3834',
 'bootstrap: rng.integers(0,ndays,(4000,ndays)), ratio of sums, np.percentile 2.5/97.5']
json.dump(out,open('analyses/M420_audit/result.json','w',encoding='utf-8'),indent=1)
print(json.dumps(out,indent=1))
