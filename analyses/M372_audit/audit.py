import re,os,sys,json,numpy as np,pandas as pd
sys.path.insert(0,'.')
import recon_engine as RE, fuel_recon as FR
dm=pd.read_csv('drive_master.csv',low_memory=False)
fm=pd.read_csv('fuel_recon_master.csv')
base=RE.BASE
import glob
def key(n): return re.sub(r'\D','',n)
rawmap={}
for p_ in glob.glob(base+'*.csv'):
    k=key(os.path.basename(p_)); rawmap.setdefault(k,p_)
def path(f): return rawmap.get(key(f))
RE.BASE=''
dm['has_fuel']=[(path(f) is not None) and FR._has_fuel(path(f)) for f in dm['file']]
ol=~(dm['ens_outlier_v2']==False)  # NaN treated as not-clean (strict ==False)
nanb=dm[['I_offset_A_applied','charge_eng_only_kwh','charge_dual_kwh']].isna().any(axis=1)
dm['elig']=(~ol)&(dm.distance_km>0)&dm.has_fuel&(~nanb)
el=dm[dm.elig].copy()
rows=[]
for _,r in el.iterrows():
    g=RE.load_drive(path(r['file']),float(r['I_offset_A_applied']))
    if g is None: rows.append(dict(file=r['file'],fail=True));continue
    pc=RE.precompute(g); agg,_=RE.central_estimate_v2_persample(pc,r,'central')
    rows.append(dict(file=r['file'],date=r['date'],km=r['distance_km'],Eg=agg['E_gen'],Egt=agg['E_gen_to_trac'],Et=agg['E_trac_gross'],
      ceo=r['charge_eng_only_kwh'],cd=r['charge_dual_kwh'],fail=False))
d=pd.DataFrame(rows); d.to_csv('analyses/M372_audit/perdrive.csv',index=False)
fails=d[d.fail].file.tolist(); d=d[~d.fail].copy()
d['f1']=0.0
def stats(x):
    S=x[['Eg','Egt','Et','ceo','cd']].sum()
    return np.array([S.Egt/S.Et,(S.Egt+S.ceo+S.cd-S.Eg)/S.Eg,(S.Egt+S.ceo-S.Eg)/S.Eg])
pt=stats(d)
days=sorted(d.date.unique()); grp={k:v for k,v in d.groupby('date')}
rng=np.random.default_rng(42); B=[]
for _ in range(4000):
    s=rng.integers(0,len(days),len(days)); B.append(stats(pd.concat([grp[days[i]] for i in s])))
B=np.array(B); ci=np.percentile(B,[2.5,97.5],axis=0)
hs=fm[fm.f_gen.notna()].file; 
hs_not=sorted(set(hs)-set(el.file)); el_not=sorted(set(el.file)-set(fm.file))
why={}
for f in hs_not:
    r=dm[dm.file==f]
    if r.empty: why[f]='not in drive_master';continue
    r=r.iloc[0]; rs=[]
    if str(r.ens_outlier_v2).lower() in('true','1','1.0'): rs.append('canonical outlier')
    if not r.distance_km>0: rs.append('dist<=0')
    if not r.has_fuel: rs.append('no fuel PID')
    for c in ['I_offset_A_applied','charge_eng_only_kwh','charge_dual_kwh']:
        if pd.isna(r[c]): rs.append('NaN '+c)
    why[f]=rs or ['other']
# also compare with published f_gen on eligible
m=d.merge(fm[['file','f_gen']],on='file',how='left'); m['mine']=m.Egt/m.Et
res=dict(n_drives=len(d),n_days=len(days),km=float(d.km.sum()),f_gen=[pt[0],*ci[:,0]],rel_excess_full=[pt[1],*ci[:,1]],rel_excess_noDual=[pt[2],*ci[:,2]],
 n_eligible_before_load_fail=int(len(el)),load_fail=fails,headline_n=int(len(hs)),headline_not_eligible=why,eligible_not_in_fuelmaster=el_not,
 max_abs_fgen_diff_vs_fuel_master=float((m.mine-m.f_gen).abs().max()),
 types=d.merge(dm[['file','drive_type']]).drive_type.value_counts().to_dict(),dm_rows=len(dm),
 dm_days=int(dm.date.nunique()))
json.dump(res,open('analyses/M372_audit/audit_result.json','w'),indent=1,default=str)
print(json.dumps(res,indent=1,default=str))
