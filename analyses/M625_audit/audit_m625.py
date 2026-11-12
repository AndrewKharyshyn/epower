import os,re,json,sys
import numpy as np,pandas as pd,warnings
warnings.filterwarnings('ignore')
sys.stdout.reconfigure(encoding='utf-8')
R='.'
d=pd.read_csv('drive_master.csv'); s=pd.read_csv('seasonal_drive_master.csv')
amb=json.load(open('summary_config.json',encoding='utf-8'))['ambientByDrive']
def a0(f):
    v=amb.get(f)
    if isinstance(v,list) and len(v)>0 and v[0] is not None and np.isfinite(v[0]): return float(v[0])
d['dt']=d.date.str[:10]
def key(n): return re.sub(r'\D','',n)[:14]
raw={}
for n in os.listdir('raw'):
    if n.endswith('.csv'): raw.setdefault(key(n),[]).append(n)
COL='Температура охолодної рідини (℃)'
p1=[];nomatch=0
for f in d.file:
    k=key(f); c=raw.get(k)
    if not c: nomatch+=1; continue
    df=pd.read_csv('raw/'+c[0],usecols=lambda x:x in('time',COL))
    if COL not in df: continue
    t=pd.to_datetime(df['time'],errors='coerce'); v=pd.to_numeric(df[COL],errors='coerce')
    m=t.notna(); ser=pd.Series(v[m].values,index=t[m].values)
    g=ser.resample('1s').mean().ffill(limit=3)
    g=g[np.isfinite(g)]
    if len(g)>=30 and g.iloc[0]<60: p1.append(f)
def rng(fs):
    dd=d[d.file.isin(fs)].dt; return dd.min(),dd.max()
def mm(fs):
    a=[x for x in map(a0,fs) if x is not None]; return len(a),(min(a),max(a)) if a else None
out={'nomatch_raw':nomatch,'P1':{'n':len(p1),'dates':rng(p1),'amb':mm(p1)}}
cold=s[s.thermal_regime=='cold'].file.tolist()
out['P2']={'n':len(cold),'in_master':int(d.file.isin(cold).sum()),'dates_seasonal':(s[s.thermal_regime=='cold'].date.str[:10].min(),s[s.thermal_regime=='cold'].date.str[:10].max()),'dates_master':rng(cold),'amb':mm(cold)}
out['P3']={'n':len(d),'dates':(d.dt.min(),d.dt.max())}
for c in['cell_spread_loaded_p95_mv','vreg_R_pack_mohm']:
    x=d[np.isfinite(pd.to_numeric(d[c],errors='coerce'))]; out['P4_'+c]={'n':len(x),'dates':(x.dt.min(),x.dt.max())}
out['P5']=int(d.dt.str[5:7].isin(['12','01','02']).sum())
print(json.dumps(out,ensure_ascii=False,default=str))
