import pandas as pd,numpy as np,json,sys
VC='[VCM] Vehicle Speed (km/h)';OB='\u0428\u0432\u0438\u0434\u043a\u0456\u0441\u0442\u044c \u0430\u0432\u0442\u043e\u043c\u043e\u0431\u0456\u043b\u044f (km/h)'
IC='[BMS] HV Battery Current (A)';VV='[BMS] HV Battery voltage (V)'
m=pd.read_csv('drive_master.csv',usecols=['file','date']);s=pd.read_csv('seasonal_drive_master.csv',usecols=['file','thermal_regime'])
m=m.merge(s,on='file')
def grid(f):
    d=pd.read_csv('raw_only/'+f,usecols=lambda c:c in('time',VC,OB,IC,VV))
    t=pd.to_timedelta(d['time'].astype(str)).dt.total_seconds().values
    t=t+86400*np.cumsum(np.r_[0,(np.diff(t)<-43200)])
    d['sec']=np.floor(t-t[0]).astype(int)
    src='obd'
    if VC in d and d[VC].notna().sum()>0: src='vcm'
    sp=d[VC] if src=='vcm' else d[OB]
    x=pd.DataFrame({'sp':pd.to_numeric(sp,errors='coerce'),'I':pd.to_numeric(d[IC],errors='coerce') if IC in d else np.nan,'V':pd.to_numeric(d[VV],errors='coerce') if VV in d else np.nan}).groupby(d['sec']).mean()
    x=x.reindex(np.arange(x.index.max()+1)).ffill(limit=3)
    return x,src
def stops(sp):
    low=np.isfinite(sp)&(sp<1.5);out=[];i=0;n=len(sp)
    while i<n:
        if low[i]:
            j=i
            while j+1<n and low[j+1]:j+=1
            if j-i+1>=3:out.append((i,j))
            i=j+1
        else:i+=1
    return out
def W(p,a,b):
    q=p[a:b+1];q=q[np.isfinite(q)]
    return (q.sum()/3.6,np.maximum(q,0).sum()/3.6,np.maximum(-q,0).sum()/3.6)
rows=[];used=0;nsrc={'vcm':0,'obd':0};bad=0
for f,dt,reg in m[['file','date','thermal_regime']].itertuples(index=False):
    x,src=grid(f);sp=x.sp.values;I=x.I.values;V=x.V.values
    if np.isfinite(sp).sum()<120 or np.isfinite(I).sum()<=60 or np.isfinite(V).sum()<=60:continue
    used+=1;nsrc[src]+=1;p=(-I)*V/1000;st=stops(sp)
    for k in range(len(st)-1):
        e=st[k][1];s_=st[k+1][0]
        if s_-e<2:continue
        seg=sp[e:s_+1]
        if not np.isfinite(seg).any():continue
        vpk=np.nanmax(seg)
        if not(1.5<=vpk<=30):continue
        tgt=min(15,vpk);rel=sp[e+1:s_]
        if len(rel)==0 or not np.isfinite(rel).any():continue
        up=np.where(rel>=tgt)[0]
        if len(up)==0:continue
        le=e+1+up[0];ab=e+1+up[-1]
        w={'launch':W(p,e,min(le,s_)),'approach':W(p,max(ab,e),s_),'cycle':W(p,e,s_)}
        if le+1<=ab-1:w['creep']=W(p,le+1,ab-1)
        c=W(p,e,s_)
        if abs(w['cycle'][0]-(w['cycle'][1]-w['cycle'][2]))>1e-6:bad+=1
        rows.append(dict(date=dt,reg=reg,add=min(le,s_)<max(ab,e),empty=('creep' not in w),**{f'{k}_{n}':w[k][i] for k in w for i,n in enumerate(['net','dis','reg'])}))
R=pd.DataFrame(rows)
def summ(r):
    o={'n_cycles':len(r),'empty_creep':int(r.creep_net.isna().sum()),'additiveShare':round(float(r['add'].mean()),2)}
    for k in['launch','creep','approach','cycle']:
        for n in['net','dis','reg']:
            v=r[f'{k}_{n}'].dropna()
            o[f'{k}_{n}']=dict(n=len(v),med=round(v.median(),2),p25=round(v.quantile(.25),2),p75=round(v.quantile(.75),2))
            if n!='net':o[f'{k}_{n}']['share_le0']=round(float((v<=0).mean()),2)
    return o
out={'drives_used':used,'speed_src':nsrc,'net_ne_dis_minus_reg':bad,'days':int(R.date.nunique())}
out['all']=summ(R)
for g in['warm','shoulder']:out[g]=summ(R[R.reg==g])
rng=np.random.default_rng(42);days=R.date.unique();grp={d:g.cycle_net.values for d,g in R.groupby('date')}
bs=[np.median(np.concatenate([grp[d] for d in rng.choice(days,len(days))])) for _ in range(4000)]
out['boot_median_cycle_net']=[round(float(np.percentile(bs,2.5)),2),round(float(np.percentile(bs,97.5)),2)]
json.dump(out,open('analyses/M356_audit/result.json','w'),indent=1);print(json.dumps(out))
