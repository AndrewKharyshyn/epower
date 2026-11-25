import os,re,csv,json,bisect,collections
import pandas as pd, numpy as np
from zoneinfo import ZoneInfo
K=ZoneInfo('Europe/Kyiv');U=ZoneInfo('UTC')
R=r"C:/Users/AndriiKharyshyn/Downloads/X-Trail Investigation/Repo/xtrail-repo/"
S=r"C:/Users/AndriiKharyshyn/Downloads/X-Trail Investigation/mynissan_store/"
P=45;SHIFT=0;SW=25;FLOOR=2;GAP=35
def ep(x):
    return (pd.to_datetime(x)-pd.Timestamp('1970-01-01')).dt.total_seconds().values
def tod(s):
    h,m,x=s.split(':');return int(h)*3600+int(m)*60+float(x)
wins=[]  # (utc_start,utc_end,name,kyiv_start)
for f in sorted(os.listdir(R+'raw')):
    m=re.match(r'^(\d{4}-\d\d-\d\d) (\d\d)-(\d\d)-(\d\d)\.csv$',f)
    if not m: continue
    st=pd.Timestamp(f"{m[1]} {m[2]}:{m[3]}:{m[4]}").tz_localize(K,ambiguous=True).timestamp()
    with open(R+'raw/'+f,'r',encoding='utf-8',errors='replace') as fh:
        fh.readline();first=None;last=None
        for l in fh:
            c=l.split(',',1)[0]
            if not c or ':' not in c: continue
            if first is None:first=c
            last=c
    d=tod(last)-tod(first)
    if d<0:d+=86400
    wins.append((st,st+d,f))
wins.sort()
print(len(wins))
dm=pd.read_csv(R+'drive_master.csv',usecols=['file','date','time_start','duration_s','distance_km'])
mfiles=set(dm.file)
notinmaster=[w[2] for w in wins if w[2].replace(' ','_').replace('-','')  not in {x.replace('-','') for x in mfiles}]
conf=pd.read_csv(S+'conflicts.csv');conf=conf[conf.stream=='Odometer']
cts=set(ep(conf.timestamp_utc))
od=pd.read_csv(S+'streams/Odometer.csv.gz',usecols=['StatusDistanceTotalizerComputed','Timestamp'])
od['t']=ep(od.Timestamp)
dups=int(od.t.duplicated().sum())
od=od[~od.t.isin(cts)].dropna(subset=['StatusDistanceTotalizerComputed']).sort_values('t')
od=od.drop_duplicates('t',keep='first')
sp=pd.read_csv(S+'streams/Trip_Information.csv.gz',usecols=['SpeedDisplayedValueinkmh','Timestamp'])
sp['t']=ep(sp.Timestamp)
sp=sp.dropna().sort_values('t')
spt=sp.t.values+SHIFT;spv=sp.SpeedDisplayedValueinkmh.values
# fast: speed-supported flag per time via max over window
t=od.t.values;o=od.StatusDistanceTotalizerComputed.values
ws=np.array([w[0]-P for w in wins]);we=np.array([w[1]+P for w in wins])
# windows may overlap -> overlap test by checking any
def overlap(a,b):
    # any window with ws<b and we>a
    i=np.searchsorted(ws,b,side='left')  # windows with ws<b : indices <i
    if i==0:return False
    return bool((cummax[i-1]>a))
cummax=np.maximum.accumulate(we)
def mon(x):
    d=pd.Timestamp(x,unit='s',tz='UTC').tz_convert(K);return d.strftime('%Y-%m'),d.strftime('%Y-%m-%d')
def supported(mid):
    i=bisect.bisect_left(spt,mid-SW);j=bisect.bisect_right(spt,mid+SW)
    return j>i and spv[i:j].max()>FLOOR
M=collections.defaultdict(lambda:collections.defaultdict(float))
C=collections.defaultdict(lambda:collections.defaultdict(float))
D=collections.defaultdict(lambda:collections.defaultdict(float))
days=collections.defaultdict(set)
rej=collections.Counter()
for k in range(len(t)-1):
    a,b=t[k],t[k+1];inc=o[k+1]-o[k];dt=b-a
    if a<wins[0][0]: continue
    if inc<0: rej['neg']+=1;continue
    if inc==0: continue
    ma,da=mon(a);mb,db=mon(b)
    key=ma if ma==mb else 'unknown'
    ov=overlap(a,b)
    if dt<=GAP:
        if inc/dt*3600>180: rej['fast']+=1;continue
        if not supported((a+b)/2): rej['nosup']+=1;continue
        if not ov:
            M[key]['km']+=inc;M[key]['n']+=1;days[key].add(da);D[da]['E2']+=inc
    else:
        cl='G2' if ov else 'G1'
        M[key][cl]+=inc;D[da][cl]+=inc
print(rej,dups,len(od))
span=(t[0],t[-1])
# E1
dm['st']=[pd.Timestamp(f"{d} {s}").tz_localize(K,ambiguous=True).timestamp() if False else 0 for d,s in zip(dm.date,dm.time_start)]
def pf(f):
    f=f.replace('.csv','')
    return pd.Timestamp(f.replace('_',' ').replace('-','')) if False else pd.to_datetime(f,format='%Y-%m-%d %H-%M-%S' if '-' in f else '%Y%m%d_%H%M%S')
dm['start']=[pf(f) for f in dm.file.str.replace('_',' ',regex=False).where(dm.file.str.contains('-'),dm.file)]
dm['ts']=[x.tz_localize(K,ambiguous=True).timestamp() for x in dm.start]
dm['in']=(dm.ts>=span[0])&(dm.ts<=span[1])
dd=dm[dm['in']].copy();dd['m']=dd.start.dt.strftime('%Y-%m');dd['d']=dd.start.dt.strftime('%Y-%m-%d')
out={}
for m,g in dd.groupby('m'):
    out[m]=dict(E1_km=round(g.distance_km.sum(),1),drives=len(g),days=g.d.nunique())
for k in sorted(set(M)|set(out)):
    r=out.setdefault(k,{});x=M.get(k,{})
    r.update(E2=round(x.get('km',0),1),steps=int(x.get('n',0)),E2days=len(days.get(k,())),G1=round(x.get('G1',0),1),G2=round(x.get('G2',0),1))
dayout={}
for d in ['2026-10-17','2026-10-18']:
    g=dd[dd.d==d];dayout[d]=dict(obd=round(g.distance_km.sum(),1),drives=len(g),E2=round(D[d]['E2'],1),G1=round(D[d]['G1'],1),G2=round(D[d]['G2'],1))
res=dict(n_windows=len(wins),not_in_master=notinmaster,span=[pd.Timestamp(x,unit='s',tz='UTC').isoformat() for x in span],months=out,days=dayout)
json.dump(res,open(R+'analyses/M776_audit/audit_out.json','w'),indent=1)
print(json.dumps(res,indent=0)[:6000])
