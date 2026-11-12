import pandas as pd,numpy as np,os,re,json,sys
sys.stdout.reconfigure(encoding='utf-8')
d=pd.read_csv('drive_master.csv'); amb=json.load(open('summary_config.json',encoding='utf-8'))['ambientByDrive']
k=lambda s:''.join(re.findall(r'\d',s))[:14]
raw={k(f):f for f in os.listdir('raw')}
d['day']=d.date.astype(str).str[:10]
# A
rows=[]
for _,r in d.iterrows():
    a=amb.get(r.file)
    if pd.notna(r.standstill_draw_kw) and isinstance(a,list) and len(a)>0 and a[0] is not None:
        rows.append((float(a[0]),r.standstill_draw_kw,r.day))
a=pd.DataFrame(rows,columns=['t','v','day']);print('A pop',len(a))
edges=[-np.inf,5,10,15,20,25,30,np.inf];labs=['<5','5-10','10-15','15-20','20-25','25-30','>=30']
a['b']=pd.cut(a.t,edges,right=False,labels=labs)
A=[]
for l in labs:
    s=a[a.b==l]
    if len(s)>=5:
        p=np.percentile(s.v,[25,50,75]);A.append(dict(label=l,n=len(s),nDays=s.day.nunique(),median=round(p[1],3),p25=round(p[0],3),p75=round(p[2],3)))
print(json.dumps(A))
# B
C='Температура охолодної рідини (℃)';O='Температура олії у двигуні (℃)'
bins=[(0,30),(30,60),(60,120),(120,180),(180,240),(240,300),(300,420),(420,600),(600,900)]
res={C:[[] for _ in bins],O:[[] for _ in bins]};days={C:[set() for _ in bins],O:[set() for _ in bins]}
npop=0
for _,r in d.iterrows():
    x=pd.read_csv('raw/'+raw[k(r.file)])
    if C not in x.columns: continue
    t=pd.to_datetime(x.time,format='%H:%M:%S.%f',errors='coerce')
    el=t.diff().dt.total_seconds().fillna(0);el[el<-43200]+=86400;el=el.clip(lower=0) if False else el
    ts=pd.Timestamp('2000-01-01')+pd.to_timedelta(el.cumsum(),unit='s')
    x=x.assign(_t=ts).dropna(subset=['_t']).set_index('_t')
    cv=pd.to_numeric(x[C],errors='coerce').dropna()
    if len(cv)==0 or cv.iloc[0]>=60: continue
    npop+=1
    for col in (C,O):
        if col not in x.columns: continue
        s=pd.to_numeric(x[col],errors='coerce')
        if col==O and s.notna().sum()<30: continue
        g=s.resample('1s').mean().ffill(limit=3)
        tt=(g.index-g.index[0]).total_seconds()
        for i,(lo,hi) in enumerate(bins):
            v=g.values[(tt>=lo)&(tt<hi)];v=v[np.isfinite(v)]
            if len(v): res[col][i].append(np.median(v));days[col][i].add(r.day)
print('B pop',npop)
out={}
for col in (C,O):
    out[col]=[dict(bin=b,med=round(float(np.median(res[col][i])),1),n=len(res[col][i]),nDays=len(days[col][i])) for i,b in enumerate(bins)]
print(json.dumps(out,ensure_ascii=False))
