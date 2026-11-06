import json,re,numpy as np,pandas as pd
P=pd.read_csv('analyses/M578_audit/m505_r3_proxies.csv');M=pd.read_csv('drive_master.csv',usecols=['file','date','vreg_R_pack_mohm'])
R=pd.read_csv('cadence_regime.csv')
nk=lambda x:re.sub(r'\D','',x)[:14]
for d in(P,M,R):d['k']=d.file.map(nk)
D=M.merge(P.drop(columns='file'),on='k').merge(R[['k','regime']],on='k',how='left')
D['absdiff']=(D.A0-D.vreg_R_pack_mohm).abs()
s=D[D.A0.notna()|D.vreg_R_pack_mohm.notna()]
new=D[D.date>='2026-10-18']
print(len(new),new.A0.notna().sum(),D.regime.value_counts(dropna=False).to_dict())
print('all nonnull drives',len(s),'maxdiff',s.absdiff.max(),'miss mismatch',(D.A0.isna()!=D.vreg_R_pack_mohm.isna()).sum())
print(s.groupby('regime',dropna=False).size(), s.date.str[:7].value_counts().sort_index().to_dict())
print('new drives w/ proxy by regime',new[new.A0.notna()].regime.value_counts(dropna=False).to_dict())
D.to_csv('analyses/M578_audit/m505_r3_perdrive.csv',index=False,encoding='utf-8')
