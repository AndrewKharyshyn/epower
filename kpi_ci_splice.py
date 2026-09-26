import sys, json, copy
sys.path.insert(0,'/home/claude/work/code')
import numpy as np, pandas as pd
from kpi_ci import day_cluster_ci
A=json.load(open('/home/claude/work/summary_arrays_M285_stage3.json'))
dm=pd.read_csv('/home/claude/work/drive_master.csv',low_memory=False)
sdm=pd.read_csv('/home/claude/work/seasonal_drive_master.csv',low_memory=False)
fr=pd.read_csv('/home/claude/work/fuel_recon_master.csv')
m=fr.merge(sdm[['file','thermal_regime']],on='file',how='left')
assert m.thermal_regime.isna().sum()==0
METH="percentile bootstrap, cluster = calendar day"; B=4000; SEED=20260919
def rnd(x,n): return round(float(x),n)
charts=A['seasonalCharts']['charts']
report={}
# ---- GeneratorTractionRecon ----
G=charts['GeneratorTractionRecon']['data']
subs={'all':m,'warm':m[m.thermal_regime=='warm'],'shoulder':m[m.thermal_regime=='shoulder']}
spec={ # key: (numerator, denominator, scale, digits, shipped key)
 'generator':(lambda c:c.generator_kWh_100*c.distance_km, lambda c:c.distance_km,1,2),
 'tractionGross':(lambda c:c.traction_gross_kWh_100*c.distance_km, lambda c:c.distance_km,1,2),
 'fGen':(lambda c:c.gen_to_traction_kWh_100*c.distance_km, lambda c:c.traction_gross_kWh_100*c.distance_km,1,3),
 'fuelL':(lambda c:c.fuel_L_per_100km*c.distance_km, lambda c:c.distance_km,1,2),
 'etaEng':(lambda c:c.eta_eng*c.distance_km, lambda c:c.distance_km,1,3)}
for coh,sub in subs.items():
    clean=sub[sub.f_gen.notna()]
    by={}
    for k,(nf,df_,sc,dg) in spec.items():
        v,lo,hi,K,ess=day_cluster_ci(nf(clean),df_(clean),clean.date,scale=sc,B=B,seed=SEED)
        shipped=G[coh]['corpus'][k]
        assert abs(round(v,dg)-shipped)<1e-9,(coh,k,round(v,dg),shipped)
        by[k]=dict(lo=rnd(lo,dg+1),hi=rnd(hi,dg+1),nClusters=K,essDays=rnd(ess,2))
    G[coh]['ci95']=dict(method=METH+"; ratio-of-sums weighted by drive distance (as the point estimate)",B=B,seed=SEED,
        nDrivesClean=int(len(clean)),byMetric=by,
        note="Sampling interval over calendar days for the fuel-instrumented, clean subset; model-derived quantities (BSFC surface, efficiencies) carry additional structural uncertainty not in this interval (see GTR sensitivity block).")
    report[coh]=by
# ---- StartsPer100km (proxy) ----
S_=charts['StartsPer100km']['data']
smap={'all':dm,'warm':dm[dm.file.isin(sdm.loc[sdm.thermal_regime=='warm','file'])],'shoulder':dm[dm.file.isin(sdm.loc[sdm.thermal_regime=='shoulder','file'])]}
for coh,d in smap.items():
    e=d[d.n_sign_crossings.notna()&(d.distance_km>0)]
    v,lo,hi,K,ess=day_cluster_ci(e.n_sign_crossings,e.distance_km,e.date,scale=100.0,B=B,seed=SEED)
    print(coh,'starts',round(v,3),S_[coh]['value'],len(e),S_[coh]['nEligible'])
    S_[coh]['ci95']=dict(lo=rnd(lo,1),hi=rnd(hi,1),method=METH,B=B,seed=SEED,nClusters=K,essDays=rnd(ess,2))
    report[coh]['starts']=S_[coh]['ci95']
json.dump(report,open('/home/claude/work/kpi_ci_report.json','w'),indent=1)
# stamps / meta note
st=A['_artifactStamps']['seasonalCharts']; st['computationStatusNote']=(st.get('computationStatusNote','')+' | M285b: day-cluster CI added to GeneratorTractionRecon and StartsPer100km (kpi_ci_splice.py).').strip(' |')
json.dump(A,open('/home/claude/work/summary_arrays_M285_stage4.json','w'),indent=1,ensure_ascii=False)
print(json.dumps(report,indent=0)[:3000])
