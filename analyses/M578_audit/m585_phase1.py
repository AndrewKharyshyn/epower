import pandas as pd,numpy as np,json
m=pd.read_csv('drive_master.csv',encoding='utf-8')
p=m['I_sample_period_s']
def new(x): return None if np.isnan(x) else ('fast' if x<1.10 else 'slow')
def old(x): return None if np.isnan(x) else ('fast' if x<1.05 else 'slow')
m['rn']=p.map(new);m['ro']=p.map(old)
out={'n_drives':len(m),'n_days':int(m['date'].nunique())}
out['new_counts']=m['rn'].value_counts(dropna=False).astype(int).to_dict()
out['old_counts']=m['ro'].value_counts(dropna=False).astype(int).to_dict()
out['differ']=sorted(m.loc[m.rn.fillna('NA')!=m.ro.fillna('NA'),'file'].tolist())
out['missing']=int(p.isna().sum())
g=(p>=1.06)&(p<1.135);out['guard']=int(g.sum());out['guard_files']=m.loc[g,'file'].tolist()
c=pd.read_csv('cadence_regime.csv',encoding='utf-8')
j=c.merge(m[['file','rn']],on='file',how='outer',indicator=True)
out['sidecar_rows']=len(c);out['sidecar_merge']=j['_merge'].value_counts().astype(int).to_dict()
b=j[j._merge=='both']
out['sidecar_mismatch']=int((b.regime.fillna('NA')!=b.rn.fillna('NA')).sum())
out['sidecar_mismatch_files']=b.loc[b.regime.fillna('NA')!=b.rn.fillna('NA'),'file'].tolist()
t=pd.read_csv('timing_support.csv',encoding='utf-8')
pre=sorted({x[:-len('_win_dt_min')] for x in t.columns if x.endswith('_win_dt_min') and x[:-3]+'max' in t.columns})
out['prefixes']=pre;dif=set();nm=0
for q in pre:
    a=t[q+'_win_dt_min'];z=t[q+'_win_dt_max']
    co=(a<1.05)&(z>=1.05);cn=(a<1.10)&(z>=1.10)
    dif|=set(t.loc[co!=cn,'file'])
    for s in(a,z): nm+=int(((s>=1.06)&(s<1.135)).sum())
out['timing_flag_differ']=sorted(dif);out['timing_medians_in_guard']=nm
ok=m['ens_outlier_v2'].astype(str).str.lower().ne('true')&m.cell_spread_loaded_p95_mv.notna()&m.peak_I_discharge.notna()&m.T_pack_mean_avg.notna()
s=m[ok];out['stratum_rows']=len(s)
for nme,col in(('old','ro'),('new','rn')):
    out['strata_'+nme]={r:{'drives':int((s[col]==r).sum()),'days':int(s.loc[s[col]==r,'date'].nunique())} for r in('fast','slow')}
    out['strata_'+nme]['missing']=int(s[col].isna().sum())
json.dump(out,open('analyses/M578_audit/m585_phase1.json','w',encoding='utf-8'),indent=1)
print(json.dumps(out,indent=0)[:5000])
