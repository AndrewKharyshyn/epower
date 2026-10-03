import pandas as pd, numpy as np
I='[BMS] HV Battery Current (A)';V='[BMS] HV Battery voltage (V)'
f=pd.read_csv('fuel_recon_master.csv')
def integ(fn,off):
    d=pd.read_csv('raw_only/'+fn,usecols=['time',I,V])
    t=pd.to_datetime(d.time,format='%H:%M:%S.%f',errors='coerce')
    s=(t-t.iloc[0]).dt.total_seconds().values
    s=np.where(np.diff(s,prepend=s[0])<-1000,s+86400,s)
    dt=np.clip(np.diff(s,prepend=s[0]),0,5)  # dt of sample i = t_i - t_{i-1}
    ok=d[I].notna()&d[V].notna()
    P=(d[V]*(-d[I]-off)/1000).values
    P=np.where(ok,P,0.0)  # rows without both signals contribute 0
    e=P*dt/3600
    nn=int(ok.sum()); 
    return dict(n_valid=nn,n_rows=len(d),pos=e[e>0].sum(),neg=e[e<0].sum(),dur_s=float(dt.sum()),dt_valid_s=float(dt[ok.values].sum()))
off=-0.3858
for fn in['20260813_145651.csv','20260813_150341.csv']:
    r=integ(fn,off); fr=f[f.file==fn]
    print(fn,r,fr[['distance_km','batt_to_traction_kWh_100','regen_to_batt_kWh_100']].to_dict('records'))
    if len(fr): print(' pos/100km',r['pos']/fr.distance_km.iloc[0]*100)
    d=pd.read_csv('raw_only/'+fn,usecols=[I,V]);print(' NaN offset ->',np.isnan(np.nan*d[I]).sum(),'all-NaN power')
g=f[f.f_gen.notna()];w=g.distance_km
print(len(g),w.sum())
fg=lambda x:(x.gen_to_traction_kWh_100*x.distance_km).sum()/(x.traction_gross_kWh_100*x.distance_km).sum()
print(fg(g),[(g[c]*w).sum()/w.sum() for c in['gen_to_traction_kWh_100','batt_to_traction_kWh_100','traction_gross_kWh_100']])
days={k:v for k,v in g.groupby('date')};ks=list(days);rng=np.random.default_rng(42);b=[]
for _ in range(4000):
    x=pd.concat([days[ks[i]] for i in rng.integers(0,len(ks),len(ks))]);b.append(fg(x))
print(len(ks),np.percentile(b,[2.5,97.5]))
print(f[(f.batt_to_traction_kWh_100==0)&(f.f_gen==1)][['file','f_gen','distance_km']])
print(f.f_gen.isna().sum(),f[f.f_gen.isna()].file.tolist())
