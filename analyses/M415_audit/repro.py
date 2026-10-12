import pandas as pd, numpy as np, json
m=pd.read_csv('drive_master.csv'); a=pd.read_csv('ah_throughput.csv')
d=m.merge(a[['file','ah_discharge','ah_charge','ah_throughput']],on='file',how='left')
assert len(d)==554
d['clean']=d.ens_outlier_v2.fillna(False).astype(bool)==False
d['gtcR']=d.ah_throughput/5; d['fceR']=d.ah_throughput/10; d['efcR']=d.ah_discharge/5
R={}
fin=d.ah_throughput.notna()
def S(mask,name):
    x=d[mask]; o={'n':int(len(x)),'n_days':int(x.date.nunique()),
     'gtcR':x.gtcR.sum(),'fceR':x.fceR.sum(),'efcR':x.efcR.sum(),
     'gtc_leg_sameset':x.gtc.sum(),'fce_leg_sameset':x.fce.sum(),
     'gtc_leg_finite_n':int(x.gtc.notna().sum()),
     'agg_factor':x.gtcR.sum()/x.gtc.sum(),
     'ch_dis_Ah':x.ah_charge.abs().sum()/x.ah_discharge.sum(),
     'ch_dis_kWh':x.gross_charge_kwh.sum()/x.gross_discharge_kwh.sum(),
     'fceR_over_efcR':x.fceR.sum()/x.efcR.sum()}
    mk=x.rf_efc.notna()&x.fceR.notna(); y=x[mk]
    o['rf_vs_fceR_n']=int(len(y)); o['rf_over_fceR']=y.rf_efc.sum()/y.fceR.sum(); o['rf_excess_pct_rated']=(o['rf_over_fceR']-1)*100
    mk=x.rf_efc.notna()&x.fce.notna(); y=x[mk]
    o['rf_vs_fce_leg_n']=int(len(y)); o['rf_excess_pct_leg']=(y.rf_efc.sum()/y.fce.sum()-1)*100
    mk=x.rf_efc.notna()&x.fce.notna()&x.fceR.notna(); y=x[mk]
    o['both_matched_n']=int(len(y)); o['rf_excess_pct_leg_onmatched']=(y.rf_efc.sum()/y.fce.sum()-1)*100
    o['rf_excess_pct_rated_onmatched']=(y.rf_efc.sum()/y.fceR.sum()-1)*100
    R[name]=o
S(fin,'all_finite'); S(fin&d.clean,'clean_finite')
# legacy over whole master
R['legacy_all_master']={'n':554,'gtc':m.gtc.sum(),'fce':m.fce.sum(),'gtc_n':int(m.gtc.notna().sum())}
c=m[m.ens_outlier_v2.fillna(False).astype(bool)==False]
R['legacy_clean_master']={'n':len(c),'gtc':c.gtc.sum(),'fce':c.fce.sum()}
# C-rate
for k,col in [('dual','dual'),('regen','regen'),('eng','eng_charge')]:
    p=d[f'{col}_peak_A'];cr=d[f'{col}_peak_Crate']; mk=cr.notna()
    v=(p[mk].abs()/5).round(1); i=v.idxmax()
    R[f'crate_{k}']={'n':int(mk.sum()),'n_peakA_nan_among':int(p[mk].isna().sum()),'median_rated':float(v.median()),'max_rated':float(v.max()),'max_file':d.file[i],
      'median_leg':float(cr[mk].median()),'max_leg':float(cr[mk].max()),'max_leg_file':d.file[cr[mk].idxmax()],'leg_over_rated_check':float((cr[mk]/(p[mk].abs()/5)).median()) if (p[mk].abs()>0).any() else None}
# drive type
x=d[d.clean&fin]; R['bytype']={}
for t,g in x.groupby('drive_type',dropna=False):
    gk=g[g.distance_km>0]
    r=lambda s:(s/gk.distance_km*100)
    R['bytype'][str(t)]={'n':int(len(g)),'n_days':int(g.date.nunique()),'ros_rated':g.gtcR.sum()/g.distance_km.sum()*100,'mean_rated':float(r(gk.gtcR).mean()),'med_rated':float(r(gk.gtcR).median()),
     'ros_leg':g.gtc.sum()/g.distance_km.sum()*100,'mean_leg':float(r(gk.gtc).mean()),'med_leg':float(r(gk.gtc).median()),'n_dist_pos':int(len(gk))}
# cumulative
z=d[fin].sort_values(['date','file']); cs=z.gtcR.cumsum()
R['cum']={'final':float(cs.iloc[-1]),'n':int(len(z)),
 'at_2026-06-30':float(cs[z.date<='2026-06-30'].iloc[-1]),'last_file_0630':z[z.date<='2026-06-30'].file.iloc[-1],'last_date_le_0630':z[z.date<='2026-06-30'].date.iloc[-1],
 'at_2026-08-31':float(cs[z.date<='2026-08-31'].iloc[-1]),'last_file_0831':z[z.date<='2026-08-31'].file.iloc[-1],'last_date_le_0831':z[z.date<='2026-08-31'].date.iloc[-1],
 'any_date_eq_0630':bool((z.date=='2026-06-30').any()),'any_date_eq_0831':bool((z.date=='2026-08-31').any()),'date_range':[z.date.min(),z.date.max()]}
R['dup_dates_sorted_ok']=bool((m.date.values==np.sort(m.date.values)).all())
json.dump(R,open('analyses/M415_audit/result.json','w',encoding='utf-8'),indent=1,default=float)
print(json.dumps(R,indent=1,default=float))
