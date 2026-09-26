"""M285c: day-cluster CIs for EnergyPath.asymmetryPct and EvTraction.evPctDistance (master-derived ratio-of-sums)."""
import sys, json, os
HERE=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,HERE)
import numpy as np, pandas as pd
from kpi_ci import day_cluster_ci
W=os.environ.get('XT_WORK','/home/claude/work')
A=json.load(open(os.path.join(W,'summary_arrays_M285_stage4.json')))
dm=pd.read_csv(os.path.join(W,'drive_master.csv'),low_memory=False)
sdm=pd.read_csv(os.path.join(W,'seasonal_drive_master.csv'),low_memory=False)
def asb(s): return s.astype(str).str.lower().isin(['true','1'])
METH="percentile bootstrap, cluster = calendar day"; B=4000; SEED=20260919
ch=A['seasonalCharts']['charts']
def cohort(c): return dm if c=='all' else dm[dm.file.isin(sdm.loc[sdm.thermal_regime==c,'file'])]
rep={}
need=['gross_discharge_kwh','gross_charge_kwh','charge_eng_only_kwh','charge_dual_kwh','charge_pure_regen_kwh','charge_lowtq_engoff_kwh']
for c in ('all','warm','shoulder'):
    d=cohort(c)
    # EnergyPath (same subset rule as _energy_path)
    e=d.dropna(subset=need); e=e[~asb(e.ens_outlier_v2)] if 'ens_outlier_v2' in e else e
    chg,dis=e.gross_charge_kwh,e.gross_discharge_kwh
    v,lo,hi,K,ess=day_cluster_ci(chg,dis,e.date,scale=100.0,B=B,seed=SEED)
    ship=ch['EnergyPath']['data'][c]['asymmetryPct']; assert abs(round(v-100,1)-ship)<1e-9,(c,v-100,ship)
    ch['EnergyPath']['data'][c]['ci95']=dict(method=METH+"; asymmetry = 100*(sum charge / sum discharge - 1)",B=B,seed=SEED,
        byMetric=dict(asymmetryPct=dict(lo=round(lo-100,2),hi=round(hi-100,2),nClusters=K,essDays=round(ess,2))))
    rep[('EnergyPath',c)]=(round(v-100,2),round(lo-100,2),round(hi-100,2),K,round(ess,2))
    # EvTraction (same subset rule as _ev_traction)
    g=d[asb(d.ev_valid)&~asb(d.ens_outlier_v2)]
    v,lo,hi,K,ess=day_cluster_ci(g.ev_dist_km,g.distance_km,g.date,scale=100.0,B=B,seed=SEED)
    ship=ch['EvTraction']['data'][c]['evPctDistance']; assert abs(round(v,1)-ship)<1e-9,(c,v,ship)
    ch['EvTraction']['data'][c]['ci95']=dict(method=METH+"; distance-weighted engine-off share (sum ev_dist_km / sum distance_km) over ev_valid, ens_outlier_v2-clean drives",B=B,seed=SEED,
        byMetric=dict(evPctDistance=dict(lo=round(lo,2),hi=round(hi,2),nClusters=K,essDays=round(ess,2))))
    rep[('EvTraction',c)]=(round(v,2),round(lo,2),round(hi,2),K,round(ess,2))
st=A['_artifactStamps']['seasonalCharts']; st['computationStatusNote']=st.get('computationStatusNote','')+' | M285c: day-cluster CI added to EnergyPath (asymmetry) and EvTraction (engine-off distance share).'
json.dump(A,open(os.path.join(W,'summary_arrays_M285_stage5.json'),'w'),indent=1,ensure_ascii=False)
for k,v in rep.items(): print(k,v)
