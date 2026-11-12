import pandas as pd, numpy as np, os, json, glob
R='C:/Users/AndriiKharyshyn/Downloads/X-Trail Investigation/Repo/xtrail-repo/'
dm=pd.read_csv(R+'drive_master.csv',usecols=['file','date'])
raw={}
for f in os.listdir(R+'raw'):
    raw.setdefault(''.join(c for c in f if c.isdigit())[:14],f)
COOL='Температура охолодної рідини (℃)'; OIL='Температура олії у двигуні (℃)'
edges=[0,30,60,120,180,240,300,420,600,900]
import sys; sys.path.insert(0,R); os.chdir(R); import drive_raw_cache
LOAD=drive_raw_cache.make_frame_loader(raw_dir=os.path.abspath('raw_only'))
res={COOL:{},OIL:{}}; miss=0
def tsec(s):
    h=pd.to_datetime(s.astype(str).str.strip(),format='%H:%M:%S.%f',errors='coerce')
    x=(h.dt.hour*3600+h.dt.minute*60+h.dt.second+h.dt.microsecond/1e6).values
    x=np.asarray(x,float); d=np.diff(x); w=np.cumsum(np.r_[0,(d<-43200)])
    return x+86400*w
for _,r in dm.iterrows():
    k=''.join(c for c in str(r['file']) if c.isdigit())[:14]
    if k not in raw: miss+=1; continue
    fr=LOAD(r['file'])
    if fr is None: miss+=1; continue
    df=fr
    tt0=pd.to_datetime(fr['time']); t=(tt0-tt0.iloc[0]).dt.total_seconds().values
    d=np.diff(t); t=t+86400*np.cumsum(np.r_[0,(d<-43200)])
    day=str(r['date'])[:10]
    if COOL not in df.columns: continue
    def grid(col):
        s=pd.Series(pd.to_numeric(df[col],errors='coerce').values,index=pd.DatetimeIndex(pd.to_datetime(fr['time']).values))
        s=s[s.index.notna()]
        return s.resample('1s').mean().ffill(limit=3).values
    vc=grid(COOL); fc=np.isfinite(vc)
    if fc.sum()<30 or not vc[fc][0]<60: continue
    for col in (COOL,OIL):
        if col not in df.columns: continue
        s=pd.Series(pd.to_numeric(df[col],errors='coerce').values,index=pd.DatetimeIndex(pd.to_datetime(fr['time']).values))
        s=s[s.index.notna()]
        g=s.resample('1s').mean().ffill(limit=3)
        v=g.values
        fin=np.isfinite(v)
        if fin.sum()<30: continue
        first=v[fin][0]
        tt=np.arange(len(v))
        for i in range(9):
            m=fin&(tt>=edges[i])&(tt<edges[i+1])
            if m.any(): res[col].setdefault(i,[]).append((np.median(v[m]),day))
out={}
for col,n in ((COOL,'coolant'),(OIL,'oil')):
    L=[]
    for i in range(9):
        a=res[col].get(i,[]); 
        if not a: L.append(None); continue
        vals=[x[0] for x in a]; nd=len({x[1] for x in a})
        L.append([len(a),nd,round(float(np.median(vals)),1),round(float(np.percentile(vals,25)),1),round(float(np.percentile(vals,75)),1),bool(len(a)>=10 and nd>=5)])
    out[n]=L
print('missing',miss,'rows',len(dm)); print(json.dumps(out,ensure_ascii=False))
