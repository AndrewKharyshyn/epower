import os,re,json,numpy as np,pandas as pd
os.chdir(r"C:/Users/AndriiKharyshyn/Downloads/X-Trail Investigation/Repo/xtrail-repo")
C='Температура охолодної рідини (℃)';O='Температура олії у двигуні (℃)'
m=pd.read_csv('drive_master.csv',usecols=['file'])['file'].tolist()
dig=lambda s:re.sub(r'\D','',s)
rawmap={}
for f in os.listdir('raw'):
    rawmap.setdefault(dig(f),[]).append(f)
def grid(path):
    d=pd.read_csv(path,encoding='utf-8',dtype=str)
    if 'time' not in d.columns or C not in d.columns: return None,'cols'
    cols=['time',C]+([O] if O in d.columns else [])
    d=d[cols].copy()
    ts=d['time'].astype(str).str.strip()
    # clock only vs with date
    hasdate=ts.str.contains(r'\d{4}-\d{2}-\d{2}|\d{2}[./]\d{2}[./]\d{4}',regex=True).any()
    if hasdate:
        t=pd.to_datetime(ts,errors='coerce')
    else:
        td=pd.to_timedelta(ts,errors='coerce')
        # handle midnight crossing: cumulative day offset on decreases
        s=td.dt.total_seconds().to_numpy()
        ok=~np.isnan(s)
        s2=s.copy();off=0;prev=None
        for i in range(len(s)):
            if np.isnan(s[i]): continue
            if prev is not None and s[i]<prev-3600: off+=86400
            prev=s[i];s2[i]=s[i]+off
        t=pd.Timestamp('2000-01-01')+pd.to_timedelta(s2,unit='s')
    d['t']=t;d=d.dropna(subset=['t'])
    for c in cols[1:]: d[c]=pd.to_numeric(d[c],errors='coerce')
    d=d.set_index('t')[cols[1:]]
    g=d.resample('1s').mean().ffill(limit=3)
    return g,None
rows=[];excl=[];missing=[]
for k in m:
    r=rawmap.get(dig(k))
    if not r: missing.append(k);excl.append((k,'nofile'));continue
    try: g,err=grid(os.path.join('raw',r[0]))
    except Exception as e: g,err=None,str(e)[:60]
    if g is None: excl.append((k,err));continue
    span=int((g.index[-1]-g.index[0]).total_seconds())
    sec=((g.index-g.index[0]).total_seconds()).astype(int)
    c=g[C].to_numpy();o=g[O].to_numpy() if O in g else np.full(len(g),np.nan)
    rows.append(dict(k=k,span=span,sec=sec,c=c,o=o,nc=int((~np.isnan(c)).sum()),no=int((~np.isnan(o)).sum()),nrawfiles=len(r)))
print('multi-file keys',[x['k'] for x in rows if x['nrawfiles']>1])
valid=[x for x in rows if x['nc']>=30]
excl+= [(x['k'],'<30 coolant s') for x in rows if x['nc']<30]
res={'n_candidates':len(m),'n_excluded':len(excl),'excluded_reasons':{}}
for _,e in excl: res['excluded_reasons'][e]=res['excluded_reasons'].get(e,0)+1
res['n_valid']=len(valid)
def first(x,a): 
    i=np.where(~np.isnan(a))[0];return a[i[0]]
warm=[x for x in valid if first(x,x['c'])>=60];cold=[x for x in valid if first(x,x['c'])<60]
res['n_warm']=len(warm);res['n_cold']=len(cold)
def ttt(x,a,T):
    i=np.where(a>=T)[0]  # NaN compares False
    return int(x['sec'][i[0]]) if len(i) else None
res['coolant']={}
tt80={}
for T in (60,70,80):
    reach=[];cens=[]
    for x in cold:
        v=ttt(x,x['c'],T)
        (reach if v is not None else cens).append((x,v))
        if T==80: tt80[x['k']]=v
    sp=np.array([x['span'] for x,_ in cens])
    res['coolant'][T]=dict(reached=len(reach),censored=len(cens),
      censored_span_p25_med_p75_max=[float(np.percentile(sp,25)),float(np.median(sp)),float(np.percentile(sp,75)),int(sp.max())] if len(sp) else None,
      reached_time_median=float(np.median([v for _,v in reach])) if reach else None)
res['risk80']={}
for t in (60,120,300,600,900,1800):
    ar=0;rb=0;cb=0
    for x in cold:
        v=tt80[x['k']];tm=v if v is not None else x['span']
        ar+=tm>=t;rb+=(v is not None and v<=t);cb+=(v is None and x['span']<t)
    res['risk80'][t]=dict(atRisk=int(ar),reachedByT=int(rb),censoredBeforeT=int(cb))
oc=[x for x in cold if x['no']>=30]
res['oil']={'n':len(oc),'n_cold_without_oil_col_or_<30':len(cold)-len(oc)}
for T in (60,70,80):
    st=0;re_=0;ce=0
    for x in oc:
        os_=first(x,x['o'])
        if os_>=T: st+=1;re_+=1
        elif ttt(x,x['o'],T) is not None: re_+=1
        else: ce+=1
    res['oil'][T]=dict(reached_incl_start=re_,atOrAboveAtStart=st,censored=ce)
# sensitivity: warm-start boundary and valid-coolant-sec definitions
res['sens_cold_n_if_first_valid_raw_unfilled']=None
json.dump(res,open('analyses/M418_audit/result.json','w',encoding='utf-8'),indent=1,ensure_ascii=False)
print(json.dumps(res,indent=1,ensure_ascii=False));print(excl[:30])
