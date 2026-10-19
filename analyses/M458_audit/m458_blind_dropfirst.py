import sys, json
import numpy as np, pandas as pd
mode = sys.argv[1] if len(sys.argv)>1 else 'wrap'
d = pd.read_csv('drive_master.csv', encoding='utf-8')
d = d[['date','time_start','time_end','soc_start','soc_end','odo_start','odo_end']].copy()
d = d.dropna(subset=['soc_start','soc_end']); d = d.sort_values(['date','time_start'], kind='stable').reset_index(drop=True)
st = pd.to_datetime(d['date']+' '+d['time_start'])
en = pd.to_datetime(d['date']+' '+d['time_end'])
if mode=='wrap':
    en = en.where(en>=st, en+pd.Timedelta(days=1))
gap = (st.shift(-1)-en).dt.total_seconds()/3600
draw = d['soc_end']-d['soc_start'].shift(-1)
odj = d['odo_start'].shift(-1)-d['odo_end']
arr = d['date'].shift(-1)
dep = en.dt.strftime('%Y-%m-%d')
G = pd.DataFrame(dict(gap=gap,draw=draw,odj=odj,arr=arr,dep=dep,arrstart=st.shift(-1),endt=en))
tot=len(G)-1
G = G.iloc[:-1]
print('pairs total',tot,'nan draw/gap',G[['gap','draw']].isna().any(axis=1).sum(),'gap<=0',(G.gap<=0).sum())
G = G.dropna(subset=['gap','draw'])
G = G[G.gap>0].reset_index(drop=True)
print('n gaps',len(G))
def sen(x,y):
    dx = x[None,:]-x[:,None]; dy=y[None,:]-y[:,None]
    iu = np.triu_indices(len(x),1)
    dx=dx[iu];dy=dy[iu]; m=dx!=0
    return np.median(dy[m]/dx[m]) if m.any() else np.nan
x=G.gap.values; y=G.draw.values
s=sen(x,y); print('slope',s,'watts',s/100*2100)
def boot(cl, B=4000, x=x, y=y):
    u,inv = np.unique(cl, return_inverse=True)
    members=[np.where(inv==k)[0] for k in range(len(u))]
    rng=np.random.default_rng(42); out=np.empty(B)
    for b in range(B):
        ch=rng.choice(len(u), size=len(u), replace=True)
        idx=np.concatenate([members[k] for k in ch])
        out[b]=sen(x[idx],y[idx])
    sizes=np.array([len(m) for m in members])
    kish = sizes.sum()**2/(sizes**2).sum()
    f=out[np.isfinite(out)]
    lo,hi=np.percentile(f,[2.5,97.5],method='linear')
    return dict(nclu=len(u),kish=kish,slope_ci=[lo,hi],watts_ci=[lo/100*2100,hi/100*2100],p=float((f*21>0).mean()),undef=int((~np.isfinite(out)).sum()))
res={}
res['arrival']=boot(G.arr.values)
print('arrival',res['arrival'])
print('departure',boot(G.dep.values))
iw = pd.to_datetime(G.arr).dt.isocalendar()
print('isoweek',boot((iw.year.astype(str)+'-'+iw.week.astype(str)).values))
# iid
rng=np.random.default_rng(42); n=len(x); o=np.empty(4000)
for b in range(4000):
    i=rng.integers(0,n,n); o[b]=sen(x[i],y[i])
lo,hi=np.nanpercentile(o,[2.5,97.5]); print('iid',lo*21,hi*21, (o>0).mean())
# jump per key cycle: median? print candidates
print('odo jump >0.5:',(G.odj>0.5).sum())
print('span midnight (arr date != dep date of end):',(G.arr!=G.dep).sum(), ' (start-date vs arr):',(G.arr!=pd.to_datetime(G.arrstart).dt.strftime('%Y-%m-%d')).sum())
# LOO
ds=np.unique(G.arr.values); w=[]
for dday in ds:
    k=G.arr.values!=dday; w.append(sen(x[k],y[k])*21)
w=np.array(w); print('LOO',w.min(),ds[w.argmin()],w.max(),ds[w.argmax()])
# jump_pp per keycycle: intercept of Sen? try median(draw - s*gap)
print('intercept median', np.median(y-s*x), 'mean draw short gaps', )
