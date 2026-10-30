import pandas as pd, numpy as np, json, re, os
COL='Оберти двигуна (rpm)'
def key(n): return ''.join(re.findall(r'\d+',n))[:14]
def rawpath(k):
    for f in os.listdir('raw'):
        if f.endswith('.csv') and key(f)==k: return 'raw/'+f
def secs(t):
    p=t.str.split(':',expand=True).astype(float); s=p[0]*3600+p[1]*60+p[2]
    return s+86400*(s.diff()<-43200).cumsum()
def grid(path,agg):
    df=pd.read_csv(path,usecols=['time',COL],encoding='utf8')
    s=secs(df['time']); r=pd.to_numeric(df[COL],errors='coerce')
    r=r.ffill(limit=15); r=r.where(~(r<0))
    b=np.floor(s).astype(int)
    g=r.groupby(b).mean() if agg=='mean' else r.groupby(b).last()
    g=g.reindex(range(g.index.min(),g.index.max()+1)).ffill(limit=15).dropna()
    return int(len(g)),int((g>=300).sum()),int((g>400).sum()),int(((g>=300)&(g<=400)).sum())
sm=pd.read_csv('seasonal_drive_master.csv'); sm['k']=sm.file.map(key); coh=dict(zip(sm.k,sm.thermal_regime))
sc=pd.read_csv('engine_on_rule_sidecar.csv'); sc['k']=sc.file.map(key); sc=sc.set_index('k')
sample=json.load(open('analyses/M542_audit_sample.json',encoding='utf-8'))['files']
rows=[];em=el=0;sums={a:np.zeros(2) for a in('mean','last')}
for f in sample:
    k=key(f); p=rawpath(k); m=grid(p,'mean'); l=grid(p,'last')
    sums['mean']+=[m[2],m[3]]; sums['last']+=[l[2],l[3]]
    s=sc.loc[k]; okm=tuple(m[:3])==(s.n_valid,s.ge300,s.gt400); okl=tuple(l[:3])==(s.n_valid_last,s.ge300_last,s.gt400_last)
    em+=okm; el+=okl
    rows.append(dict(f=f,cohort=coh.get(k),mean=m,last=l,okm=bool(okm),okl=bool(okl),side=[int(s.n_valid),int(s.ge300),int(s.gt400),int(s.n_valid_last),int(s.ge300_last),int(s.gt400_last)]))
    print(rows[-1])
t1=dict(n=len(sample),exactMean=int(em),exactLast=int(el),mismatches=[r['f'] for r in rows if not(r['okm'] and r['okl'])])
# task2
cold=sm[sm.thermal_regime=='cold']; eon=bd=0
for f in cold.file:
    g=grid(rawpath(key(f)),'mean'); eon+=g[2]; bd+=g[3]
A=json.load(open('summary_arrays.json',encoding='utf8'))['engineOnRule']; c=A['byCohort']['cold']
t2=dict(nCold=len(cold),engineOnH=round(eon/3600,4),bandH=round(bd/3600,4),ref=[c['engineOnHours'],c['lowRpmBandHours']],
 match=[round(eon/3600,4)==c['engineOnHours'],round(bd/3600,4)==c['lowRpmBandHours']],nDays=int(cold.date.nunique()),refDays=c['nDays'],daysMatch=int(cold.date.nunique())==c['nDays'],eonSec=int(eon),bandSec=int(bd))
# task3
sm2=sm.copy()
sc2=sc.join(sm2.set_index('k').thermal_regime)
cnt=sc2.thermal_regime.value_counts().to_dict(); es=int(sc2.gt400.sum())
bc={k:v['nDrives'] for k,v in A['byCohort'].items()}
ps={k:int(sc2[sc2.thermal_regime==k].gt400.sum()) for k in bc}
P=A['pooled']
sg=lambda x:int(np.sign(x))
own_e=(sums['last'][0]-sums['mean'][0])/sums['mean'][0]; own_b=(sums['last'][1]-sums['mean'][1])/sums['mean'][1]
S=A['aggregatorSensitivity']['pooled']
t3=dict(sidecarRows=len(sc),cohortCounts=cnt,reportedCounts=bc,countsMatch=cnt==bc,sumEngineOn=es,pooledEngineOn=P['engineOnSeconds'],sumMatch=es==P['engineOnSeconds'],sumByCohort=ps,
 cohortSecMatch={k:ps[k]==A['byCohort'][k]['engineOnSeconds'] for k in bc},nDrivesMatch=len(sc)==P['nDrives'],
 own20RelDiffPct=[round(100*own_e,3),round(100*own_b,3)],reported=[S['engineOnRelDiffPct'],S['bandRelDiffPct']],signMatch=[sg(own_e)==sg(S['engineOnRelDiffPct']),sg(own_b)==sg(S['bandRelDiffPct'])])
out=dict(convention='mean (record): ffill15 native, neg->NaN, floor-second bins MEAN, grid ffill15, dropna; last = last of ffilled native per bin',task1=t1,task2=t2,task3=t3,rows=rows)
json.dump(out,open('analyses/M542_audit.json','w',encoding='utf-8'),ensure_ascii=False,indent=1,default=str)
print(t1);print(t2);print(t3)
