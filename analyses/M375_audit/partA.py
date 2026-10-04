import pandas as pd, numpy as np, json
dm=pd.read_csv('drive_master.csv'); fr=pd.read_csv('fuel_recon_master.csv'); sd=pd.read_csv('seasonal_drive_master.csv')
out={}
print(len(fr), fr.file.nunique(), len(dm), dm.file.nunique())
m=fr.merge(dm[['file','date','ens_outlier_v2','ens_invalid']],on='file',how='left',suffixes=('','_dm'))
print('missing in dm',m.ens_outlier_v2.isna().sum(), m.ens_invalid.isna().sum())
print('disagree',(m.ens_outlier_v2!=m.ens_invalid).sum())
print(dm.ens_outlier_v2.value_counts(dropna=False).to_dict(), dm.ens_invalid.value_counts(dropna=False).to_dict())
m=m.merge(sd[['file','thermal_regime']],on='file',how='left')
print('date mismatch',(m.date!=m.date_dm).sum() if 'date_dm' in m else 'nodm')
excl=(m.ens_outlier_v2==True)|(m.ens_invalid==True)
print(m[excl][['file','drive_type','date','distance_km','f_gen','thermal_regime']])
print('n fuel',len(m),'clean',(~excl).sum(),'days dm',dm.date.nunique(),'days fuel',m.date.nunique(),'km',m.distance_km.sum(), 'km clean',m[~excl].distance_km.sum())
print('thermal nan',m.thermal_regime.isna().sum(), m.thermal_regime.value_counts(dropna=False).to_dict())
def wm(d,c):
    w=d.distance_km; return float((d[c]*w).sum()/w.sum())  # skipna numer, denom not
def head(d):
    c=d[d.f_gen.notna()]
    r=dict(nProduction=len(d),nDrives=len(c),km=round(c.distance_km.sum(),1))
    for k,n in [('generator_kWh_100',2),('traction_gross_kWh_100',2),('fuel_L_per_100km',2),('fuel_chem_kWh_100',2),('eta_eng',3),('eta_fuel_bus',3)]:
        r[k]=round(wm(c,k),n)
    r['f_gen']=round(float((c.gen_to_traction_kWh_100*c.distance_km).sum()/(c.traction_gross_kWh_100*c.distance_km).sum()),3)
    # alt denominators
    return r
def views(d):
    o={}
    for v,mask in [('All',d.thermal_regime.notna()|True),('Warm',d.thermal_regime=='warm'),('Shoulder',d.thermal_regime=='shoulder')]:
        o[v]=head(d[mask])
    c=d[d.f_gen.notna()]
    o['types']={}
    for t in ['urban','mixed','mixed_highway','highway']:
        x=c[c.drive_type==t]
        o['types'][t]=dict(n=len(x),km=round(x.distance_km.sum(),1),f_gen=round(float((x.gen_to_traction_kWh_100*x.distance_km).sum()/(x.traction_gross_kWh_100*x.distance_km).sum()),4))
    return o
out['canonical_clean']=views(m[~excl]); out['old_all_rows']=views(m)
out['excluded']=m[excl][['file','drive_type','date','distance_km','f_gen','thermal_regime']].astype(str).to_dict('records')
out['n']=dict(fuel=len(m),clean=int((~excl).sum()),days_dm=int(dm.date.nunique()),days_fuel=int(m.date.nunique()),km_all=float(m.distance_km.sum()),km_clean=float(m[~excl].distance_km.sum()))
print(m.drive_type.value_counts().to_dict())
print(json.dumps(out,indent=1,default=str))
json.dump(out,open('analyses/M375_audit/partA.json','w'),indent=1,default=str)
