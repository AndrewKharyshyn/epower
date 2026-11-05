import pandas as pd, json, re, csv, numpy as np
IAT='[BMS] HV Battery Intake Air Temperature (℃)'; MPC='[VCM] Motor Power Consumption (%)'
m=pd.read_csv('drive_master.csv',encoding='utf-8')
def raw(f):
    s=f[:-4]
    mm=re.fullmatch(r'(\d{4})(\d\d)(\d\d)_(\d\d)(\d\d)(\d\d)',s)
    if mm: return '%s-%s-%s %s-%s-%s.csv'%mm.groups()
    mm=re.fullmatch(r'(\d{4}-\d\d-\d\d)_(\d\d)-(\d\d)-(\d\d)',s)
    return '%s %s-%s-%s.csv'%mm.groups()
rows=[]
for _,r in m.iterrows():
    p='raw/'+raw(r.file)
    df=pd.read_csv(p,encoding='utf-8',encoding_errors='replace',low_memory=False,usecols=lambda c:c in(IAT,MPC))
    with open(p,encoding='utf-8',errors='replace',newline='') as fh: h=next(csv.reader(fh))
    ia=IAT in h; mp=MPC in h
    c='D' if ia and mp else 'A' if ia else 'B' if mp else 'C'
    rows.append(dict(file=r.file,date=r.date,ts=r.time_start,per=r.I_sample_period_s,cls=c,
      iatnn=float(df[IAT].notna().mean()) if ia else None, mpcnn=float(df[MPC].notna().mean()) if mp else None,
      nh=len(h)))
d=pd.DataFrame(rows)
def q(s):
    s=s.dropna(); return dict(n=int(len(s)),median=float(s.median()),q1=float(s.quantile(.25)),q3=float(s.quantile(.75))) if len(s) else dict(n=0)
out={'perClass':{}}
for c,g in d.groupby('cls'):
    out['perClass'][c]=dict(drives=len(g),days=int(g.date.nunique()),first=g.date.min(),last=g.date.max(),period=q(g.per),
      iatNonNull=q(g.iatnn),mpcNonNull=q(g.mpcnn),
      iatNonNullMean=None if g.iatnn.isna().all() else float(g.iatnn.mean()),mpcNonNullMean=None if g.mpcnn.isna().all() else float(g.mpcnn.mean()))
d['k']=d.date+' '+d.ts.astype(str); d=d.sort_values('k').reset_index(drop=True)
print('sorted==master order',(d.file.values==pd.Series([r['file'] for r in rows]).values).all())
cl=d.cls.tolist(); i=len(cl)
while i>0 and cl[i-1]=='B': i-=1
run=d.iloc[i:]
earlier=d.iloc[:i][d.cls.iloc[:i]=='B']
out['finalBrun']=dict(drives=len(run),days=int(run.date.nunique()),start=run.iloc[0].file)
out['earlierB']=earlier[['date','ts','file']].to_dict('records')
out['earliestEarlierB']=out['earlierB'][0] if out['earlierB'] else None
out['CD']=d[d.cls.isin(['C','D'])].groupby('cls').size().to_dict()
w=[]
for dt,g in d.groupby('date'):
    if set(g.cls)>={'A','B'}:
        w.append(dict(date=dt,A=q(g[g.cls=='A'].per),B=q(g[g.cls=='B'].per)))
out['withinDay']=w
json.dump(out,open('analyses/M578_audit/m582_phase1.json','w',encoding='utf-8'),indent=1,default=str)
d.drop(columns=['k']).to_csv('analyses/M578_audit/m582_phase1_rows.csv',index=False,encoding='utf-8')
print(json.dumps(out,indent=1,default=str))
