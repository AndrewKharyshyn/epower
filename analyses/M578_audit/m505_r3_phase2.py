import json,re,numpy as np,pandas as pd
r=json.load(open('analyses/M505_result_r3.json',encoding='utf-8'))
nk=lambda x:re.sub(r'\D','',x)[:14]
pdv={nk(k):v for k,v in r['perDrive'].items()}
P=pd.read_csv('analyses/M578_audit/m505_r3_proxies.csv');P['k']=P.file.map(nk)
res={}
for v in['A0','A1','A2','A3','A4']:
    m=0;mm=0;n=0
    for _,row in P.iterrows():
        a=pdv.get(row.k,{}).get(v);b=row[v]
        if a is None and pd.isna(b):continue
        if a is None or pd.isna(b):mm+=1;continue
        n+=1;m=max(m,abs(a-b))
    res[v]=dict(n=n,maxabs=round(m,4),missing_mismatch=mm)
print(res)
# S1 own refit
M=pd.read_csv('drive_master.csv',usecols=['file','date','T_pack_mean_avg','ens_outlier_v2']);M['k']=M.file.map(nk)
Dn=pd.read_csv('powerfade_density.csv');Dn['k']=Dn.file.map(nk)
D=M.merge(P.drop(columns='file'),on='k').merge(Dn[['k','eff_dt_s','coverage_frac']],on='k',how='left')
clean=D.ens_outlier_v2.astype(str)!='True'
out={}
for v in['A0','A1','A4']:
  for des in['S0','S1']:
    cov=[v+'_p95','T_pack_mean_avg']+(['eff_dt_s','coverage_frac'] if des=='S1' else [])
    u=D[v].notna()&clean&D[cov].notna().all(axis=1)
    d=D[u].copy()
    mo=(pd.to_datetime(d.date)-pd.to_datetime(d.date).min()).dt.days/(30.44 if des=='S1' else 30.4375)
    X=np.c_[np.ones(len(d)),mo,d[cov].values];y=d[v].values
    b=np.linalg.lstsq(X,y,rcond=None)[0][1]
    ud=d.date.values;ds=np.unique(ud);idx=[np.where(ud==k)[0] for k in ds]
    rng=np.random.default_rng(42);bs=[]
    for _ in range(4000):
        ii=np.concatenate([idx[j] for j in rng.integers(0,len(ds),len(ds))])
        bs.append(np.linalg.lstsq(X[ii],y[ii],rcond=None)[0][1])
    lo,hi=np.percentile(bs,[2.5,97.5]);a=r['own'][v][des]
    out[des+'/'+v]=dict(n=int(u.sum()),days=len(ds),slope=round(float(b),4),ci=[round(lo,4),round(hi,4)],author=[a['n'],a['nDays'],a['slope'],a['dayCi95']],dslope=round(abs(b-a['slope']),4),dci=round(max(abs(lo-a['dayCi95'][0]),abs(hi-a['dayCi95'][1])),4))
    print(des,v,out[des+'/'+v])
json.dump(dict(perDriveCompare=res,refits=out),open('analyses/M578_audit/m505_r3_phase2.json','w',encoding='utf-8'),indent=1)
