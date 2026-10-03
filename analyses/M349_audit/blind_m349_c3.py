import pandas as pd, numpy as np
I='[BMS] HV Battery Current (A)';V='[BMS] HV Battery voltage (V)'
dist={'20260813_145651.csv':2.2,'20260813_150341.csv':4.6}
off=-0.3858
for fn,km in dist.items():
    d=pd.read_csv('raw_only/'+fn,usecols=['time',I,V])
    t=pd.to_datetime(d.time,format='%H:%M:%S.%f',errors='coerce')
    s=(t-t.iloc[0]).dt.total_seconds().values
    s=np.where(s<-1000,s+86400,s)
    mi=d[I].notna().values; mv=d[V].notna().values
    ti,ii=s[mi],d[I].values[mi]; tv,vv=s[mv],d[V].values[mv]
    j=np.searchsorted(tv,ti); j0=np.clip(j-1,0,len(tv)-1); j1=np.clip(j,0,len(tv)-1)
    pick=np.where(abs(tv[j0]-ti)<=abs(tv[j1]-ti),j0,j1)
    ok=abs(tv[pick]-ti)<=1.5
    P=vv[pick]*(-ii-off)/1000
    dt=np.minimum(np.diff(ti,append=ti[-1]),5.0)  # dt to next valid I sample (any, even unpaired); last=0
    e=(P*dt/3600)[ok]
    print(fn,'nI',mi.sum(),'nV',mv.sum(),'paired',ok.sum(),'dur',round(s[-1]-s[0]),
      'dis',round(e[e>0].sum(),4),'chg',round(e[e<0].sum(),4),'dis/100km',round(e[e>0].sum()/km*100,3),'chg/100km',round(e[e<0].sum()/km*100,3),'net/100km',round(e.sum()/km*100,3),'Vmed',np.median(vv))
print('--gaps')
for fn,km in dist.items():
    d=pd.read_csv('raw_only/'+fn,usecols=['time',I,V])
    t=pd.to_datetime(d.time,format='%H:%M:%S.%f');s=(t-t.iloc[0]).dt.total_seconds().values
    mi=d[I].notna().values; mv=d[V].notna().values
    ti,tv=s[mi],s[mv]; g=np.abs(ti[:,None]-tv[None,:]).min(1)
    print(fn,'nearest-V gap quantiles',np.round(np.percentile(g,[0,25,50,75,100]),2),'dtI median',np.median(np.diff(ti)),'dtI max',np.diff(ti).max())
    for tol in(1.5,2.5,5):
        ok=g<=tol; Pm=None
        j=np.abs(ti[:,None]-tv[None,:]).argmin(1); vv=d[V].values[mv][j]; ii=d[I].values[mi]
        P=vv*(-ii-off)/1000; dtt=np.minimum(np.diff(ti,append=ti[-1]),5.0); e=(P*dtt/3600)[ok]
        print(' tol',tol,'paired',ok.sum(),'dis/100km',round(e[e>0].sum()/km*100,3),'chg/100km',round(e[e<0].sum()/km*100,3))
    # all, no tol, 
    j=np.abs(ti[:,None]-tv[None,:]).argmin(1); vv=d[V].values[mv][j]; ii=d[I].values[mi]
    P=vv*(-ii-off)/1000; dtt=np.minimum(np.diff(ti,append=ti[-1]),5.0); e=P*dtt/3600
    print(' notol dis',round(e[e>0].sum(),4),'chg',round(e[e<0].sum(),4),'dis/100km',round(e[e>0].sum()/km*100,3))
