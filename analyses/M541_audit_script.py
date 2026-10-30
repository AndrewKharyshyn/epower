import json,re,sys,pandas as pd,numpy as np
base='raw/'
files=json.load(open('analyses/M541_audit_sample.json',encoding='utf-8'))['files']
def rawname(f):
    m=re.match(r'(\d{4})-?(\d{2})-?(\d{2})[_ ](\d{2})-?(\d{2})-?(\d{2})\.csv',f)
    return '%s-%s-%s %s-%s-%s.csv'%m.groups()
def run(f,agg):
    rn=rawname(f); df=pd.read_csv(base+rn,usecols=lambda c:c in('time','Оберти двигуна (rpm)'))
    col='Оберти двигуна (rpm)'
    t=pd.to_datetime(rn[:10]+' '+df['time'].astype(str),errors='coerce')
    d=(t.diff().dt.total_seconds()<-3600).cumsum(); t=t+pd.to_timedelta(d,unit='D')
    s=pd.Series(pd.to_numeric(df[col],errors='coerce').values,index=t)
    s=s[~s.index.duplicated(keep='last')]
    s=s.where(~(s<0))
    s=s[s.index.notna()]
    s=s.ffill(limit=15)
    # native-row ffill limit 15 applied on raw series: raw rows with NaN already dropped, so ffill happens on grid
    g=getattr(s.resample('1s'),agg)()
    g=g.ffill(limit=15)
    v=g.dropna()
    return dict(file=f,n_valid=int(len(v)),ge300=int((v>=300).sum()),gt400=int((v>400).sum()),band=int(((v>=300)&(v<=400)).sum()))
out={}
for agg in('mean','last'):
    out[agg]=[run(f,agg) for f in files]
json.dump({'perDrive':out['mean'],'perDrive_lastAgg':out['last']},open('analyses/M541_audit.json','w',encoding='utf-8'),indent=1)
sc=pd.read_csv('engine_on_rule_sidecar.csv').set_index('file')
for agg in out:
    mm=0
    for r in out[agg]:
        a=sc.loc[r['file']]
        ok=(a.n_valid==r['n_valid'],a.ge300==r['ge300'],a.gt400==r['gt400'])
        if not all(ok): mm+=1; print(agg,r,dict(a[['n_valid','ge300','gt400']]))
    print(agg,'mismatch files',mm)
