import pandas as pd, numpy as np, json, re, glob, os
C='Оберти двигуна (rpm)'
S=json.load(open('analyses/M543_audit_sample.json',encoding='utf-8'))['files']
def key(n): return re.sub(r'\D','',n)[:14]
raw={key(os.path.basename(p)):p for p in glob.glob('raw/*.csv')}
rule=pd.read_csv('engine_on_rule_sidecar.csv'); rule['k']=rule.file.map(key)
band=pd.read_csv('rpm_opt_band_sidecar.csv'); band['k']=band.file.map(key)
def grid(p):
    d=pd.read_csv(p,usecols=['time',C]); s=d[C].copy()
    s=s.ffill(limit=15); s[s<0]=np.nan
    t=pd.to_timedelta(d['time'])
    s.index=t; s=s[~s.index.isna()]
    g=s.resample('1s').mean().ffill(limit=15).dropna()
    return g
out=[];mm=[]
for f in S:
    k=key(f); g=grid(raw[k])
    on=int((g>400).sum()); bd=int(((g>=1850)&(g<=2150)).sum())
    r=rule[rule.k==k].iloc[0]; b=band[band.k==k].iloc[0]
    row=dict(file=f,on=on,band=bd,side_gt400=int(r.gt400),eq_hi=int(b.eq_hi),n_rr=int(b.n_rr),bins={c:int(b[c]) for c in band.columns if re.fullmatch(r'b\d+',c)})
    row['onMatch']=on==row['side_gt400']; out.append(row)
    if not row['onMatch']: mm.append(f)
json.dump(out,open('audit/m543_task1_raw.json','w',encoding='utf-8'),indent=1)
for r in out: print(r['file'],r['on'],r['band'],r['side_gt400'],r['eq_hi'],r['n_rr'],r['onMatch'],list(r['bins'].values()))
