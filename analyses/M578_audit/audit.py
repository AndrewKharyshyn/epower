import pandas as pd, json, sys
old_path=sys.argv[1]
m=pd.read_csv('drive_master.csv',usecols=['file','date','I_sample_period_s'])
s=pd.read_csv('cadence_regime.csv',dtype=str,keep_default_na=False)
o=pd.read_csv(old_path,dtype=str,keep_default_na=False)
def rule(p,t): 
    if pd.isna(p): return None
    return 'fast' if p<t else 'slow'
m['new']=m.I_sample_period_s.apply(lambda p:rule(p,1.10))
m['old']=m.I_sample_period_s.apply(lambda p:rule(p,1.05))
r={}
r['n_master']=len(m);r['n_sidecar']=len(s);r['n_old_sidecar']=len(o)
sm=s.set_index('file')
r['sidecar_files_match_master']=set(s.file)==set(m.file)
dis=[]
for _,x in m.iterrows():
    sr=sm.regime.get(x.file); sr=None if sr in ('','nan','None') else sr
    if sr!=x.new: dis.append([x.file,sr,x.new])
r['rule_disagreements']=dis
# (2)
oo=o.set_index('file')
common=[f for f in o.file if f in sm.index]
r['old_rows_missing_in_new']=len(o)-len(common)
r['pre_batch_diff_rows']=sum(1 for f in common if (oo.loc[f,'regime'],oo.loc[f,'I_sample_period_s'])!=(sm.loc[f,'regime'],sm.loc[f,'I_sample_period_s']))
r['pre_batch_byte_identical_full_row']=sum(1 for f in common if list(oo.loc[f])==list(sm.loc[f]))
newf=[f for f in s.file if f not in oo.index]
r['n_new_rows']=len(newf)
r['new_rows_regimes']=sm.loc[newf,'regime'].value_counts().to_dict()
r['new_rows_min_file']=min(newf);r['new_rows_ge_20261103_19-55-57']=sum(1 for f in newf if f>='2026-11-03_19-55-57')
p=m.I_sample_period_s
r['n_in_1.06_1.135']=int(((p>=1.06)&(p<1.135)).sum())
r['counts']={'fast':int((m.new=='fast').sum()),'slow':int((m.new=='slow').sum()),'null':int(m.new.isna().sum())}
d=m[m.old!=m.new]
r['old_vs_new_diff']=d[['file','date','I_sample_period_s','old','new']].values.tolist()
newset=set(newf)
older=m[~m.file.isin(newset)]
r['max_period_older_fast']=float(older[older.new=='fast'].I_sample_period_s.max())
r['min_period_slow']=float(m[m.new=='slow'].I_sample_period_s.min())
r['max_period_all_fast']=float(m[m.new=='fast'].I_sample_period_s.max())
json.dump(r,open('analyses/M578_audit/audit.json','w',encoding='utf-8'),indent=1)
print(json.dumps(r,indent=1))
