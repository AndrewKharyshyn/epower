import pandas as pd, numpy as np, json, os
R='raw_only/'
files=json.load(open('analyses/M544_audit_sample.json',encoding='utf-8'))['files']
RPM='Оберти двигуна (rpm)'; BOOST='Розрахунковий наддув (bar)'
def runs(on):
    a=np.concatenate([[0],on.astype(np.int8),[0]]); d=np.diff(a)
    s=np.where(d==1)[0]; e=np.where(d==-1)[0]; return s,e
out={}
for f in files:
    df=pd.read_csv(R+f,encoding='utf-8',usecols=lambda c:c in ('time',RPM,BOOST))
    t=pd.to_datetime(df['time'],errors='coerce')
    sec=(t-t.dt.normalize()).dt.total_seconds().to_numpy()
    # unwrap midnight
    sec=np.where(np.isnan(sec),np.nan,sec)
    ok=~np.isnan(sec)
    sec=sec[ok]; df=df[ok].reset_index(drop=True)
    sec=sec+86400*np.cumsum(np.r_[0,(np.diff(sec)<-43200)])
    rpm=pd.to_numeric(df[RPM],errors='coerce').ffill(limit=15)
    rpm=rpm.where(~(rpm<0))
    boost=pd.to_numeric(df[BOOST],errors='coerce').ffill(limit=15) if BOOST in df else None
    s=pd.Series(rpm.to_numpy(),index=np.floor(sec).astype(np.int64))
    g=s.groupby(level=0).mean()
    g=g.reindex(np.arange(g.index.min(),g.index.max()+1)).ffill(limit=15)
    v=g.to_numpy(); r={}
    for T in (300,400):
        on=np.nan_to_num(v,nan=-1)>T
        a,b=runs(on); L=b-a
        r[f't{T}']=dict(nSegments=int(len(L)),sumSeconds=int(L.sum()),medianSeconds=float(np.median(L)) if len(L) else None)
    if boost is not None:
        m=(rpm>300)&(rpm<=400)&boost.notna(); r['boostRows']=int(m.sum())
    else: r['boostRows']=0
    r['hasBoost']=BOOST in df.columns
    out[f]=r
json.dump(out,open('audit/own_numbers.json','w',encoding='utf-8'),indent=1)
for f,r in out.items(): print(f,r)

# ---- taxonomy
tax=dict(unchanged=0,shortened=0,split=0,dropped=0,subRuns=0,runsLow=0)
for f in files:
    df=pd.read_csv(R+f,encoding='utf-8',usecols=lambda c:c in ('time',RPM))
    t=pd.to_datetime(df['time'],errors='coerce',format='mixed')
    sec=(t-t.dt.normalize()).dt.total_seconds().to_numpy(); ok=~np.isnan(sec)
    sec=sec[ok]; df=df[ok].reset_index(drop=True)
    sec=sec+86400*np.cumsum(np.r_[0,(np.diff(sec)<-43200)])
    rpm=pd.to_numeric(df[RPM],errors='coerce').ffill(limit=15); rpm=rpm.where(~(rpm<0))
    g=pd.Series(rpm.to_numpy(),index=np.floor(sec).astype(np.int64)).groupby(level=0).mean()
    v=g.reindex(np.arange(g.index.min(),g.index.max()+1)).ffill(limit=15).to_numpy()
    v=np.nan_to_num(v,nan=-1)
    a3,b3=runs(v>300); a4,b4=runs(v>400)
    for s,e in zip(a3,b3):
        sub=[(x,y) for x,y in zip(a4,b4) if x>=s and y<=e]
        tax['runsLow']+=1; tax['subRuns']+=len(sub)
        if not sub: tax['dropped']+=1
        elif len(sub)>1: tax['split']+=1
        elif sub[0]==(s,e): tax['unchanged']+=1
        else: tax['shortened']+=1
print('TAX',tax)
