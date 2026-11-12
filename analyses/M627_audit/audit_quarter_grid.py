import pandas as pd, numpy as np, json
R='raw_only/'
dm=pd.read_csv('drive_master.csv',usecols=['file','date']); dm['d']=dm['date'].astype(str).str[:10]
P={'kW':('[BMS] Input possible power (kW)','[BMS] Output possible power (kW)',1.0),
   'hp':('[BMS] Input possible power (hp)','[BMS] Output possible power (hp)',0.73549875)}
res={e:dict(n=0,on=0,off_drives=[]) for e in P}
for f,d in zip(dm.file,dm.d):
    hdr=pd.read_csv(R+f,nrows=0).columns
    for e,(a,b,k) in P.items():
        if a in hdr and b in hdr:
            df=pd.read_csv(R+f,usecols=[a,b],low_memory=False)
            x=pd.concat([pd.to_numeric(df[a],errors='coerce'),pd.to_numeric(df[b],errors='coerce')]).to_numpy()*k
            x=x[np.isfinite(x)]
            on=int((np.abs(x/0.25-np.round(x/0.25))*0.25<=1e-6).sum())
            res[e]['n']+=len(x); res[e]['on']+=on
            if on<len(x): res[e]['off_drives'].append(d)
out={}
for e,r in res.items():
    o=r['off_drives']
    out[e]={'finite_samples':r['n'],'on_0.25_grid':r['on'],'share':round(r['on']/r['n'],6),
            'drives_with_off_grid':len(o),'first_date':min(o) if o else None,'last_date':max(o) if o else None}
json.dump(out,open('analyses/M627_audit/audit_quarter_grid.json','w'),indent=1)
