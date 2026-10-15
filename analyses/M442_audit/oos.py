import sys,pickle
sys.path.insert(0,'analyses/M442_audit')
import ext, numpy as np, pandas as pd
res=pickle.load(open('analyses/M442_audit/res.pkl','rb'))
dm=pd.read_csv('drive_master.csv').set_index('file')
rows=[]
for f,v in res.items():
    q=v['q90']; 
    rows.append((f,v['known'],q['speed'],q['I'],q['V'],v['nat'][0][2]+v['nat'][0][3],v['nat'][0][1],dm.loc[f,'ev_rpm_dt_med_s']))
d=pd.DataFrame(rows,columns=['f','known','qs','qI','qV','n','ke','cad'])
bad=d[(d[['qs','qI','qV']].isna().any(axis=1))|(d[['qs','qI','qV']].max(axis=1)>3)]
print(len(bad)); print(bad.to_string())
# native KE per drive
L=ext.drc.make_frame_loader(raw_dir='raw_only')
nk={}
for f in d.f:
    nat,t0,tl=ext.load_native(L(f))
    r=ext.extract(nat,ext.csa._mass_for_drive(dm.loc[f,'drive_type'],f))
    nk[f]=0 if r is None else r['ke'].sum()
d['nke']=d.f.map(nk)
b=d.f.isin(bad.f)
print('native KE total',d.nke.sum(),'oos share', d.nke[b].sum()/d.nke.sum(), 'oos known', d.nke[b&d.known].sum()/d.nke[d.known].sum())
bb=d[(d[['qs','qI','qV']].max(axis=1)>3)]
print('finite>3 only:',len(bb), d.nke[d.f.isin(bb.f)].sum()/d.nke.sum())
bb=d[(d[['qs','qI','qV']].max(axis=1)>3)&d.known]
print('finite>3 known:',len(bb), d.nke[d.f.isin(bb.f)].sum()/d.nke[d.known].sum())
