import os,sys,json,warnings
os.environ['PYTHONUTF8']='1'; os.environ['XT_RAW_DIR']=os.path.abspath('raw_only')
sys.path.insert(0,os.path.abspath('.'))
import numpy as np, pandas as pd
import model_constants as MC, recon_engine as RE, fuel_recon as FR
print(RE.BASE)
dm=pd.read_csv('drive_master.csv'); fr=pd.read_csv('fuel_recon_master.csv')
const=FR.corpus_offset(dm)[0]
excl=set(dm.loc[(dm.ens_outlier_v2==True)|(dm.ens_invalid==True),'file'])
ORIG={k:getattr(MC,k) for k in ['ETA_GEN','P_AUX_KW','COLD_MULT','OPT_LO','OPT_HI']}
def rep(t,v): return (v,)+tuple(t[1:])
axes={'BASE':('central',{}),'optimistic':('optimistic',{}),'conservative':('conservative',{}),
 'ETA_GEN0=0.90':('central',{'ETA_GEN':rep(ORIG['ETA_GEN'],0.90)}),'ETA_GEN0=0.97':('central',{'ETA_GEN':rep(ORIG['ETA_GEN'],0.97)}),
 'P_AUX0=0.2':('central',{'P_AUX_KW':rep(ORIG['P_AUX_KW'],0.2)}),'P_AUX0=1.2':('central',{'P_AUX_KW':rep(ORIG['P_AUX_KW'],1.2)}),
 'COLD_MULT0=1.00':('central',{'COLD_MULT':rep(ORIG['COLD_MULT'],1.00)}),'COLD_MULT0=1.45':('central',{'COLD_MULT':rep(ORIG['COLD_MULT'],1.45)}),
 'OPT1750_2250':('central',{'OPT_LO':1750.0,'OPT_HI':2250.0})}
res={a:{} for a in axes}   # a -> file -> dict
base_ps={}
for i,r in fr.iterrows():
    f=r.file; mrow=dm[dm.file==f].iloc[0]
    off=FR.resolve_offset(mrow,const)[0]
    g=RE.load_drive(f,off)
    if g is None:
        for a in axes: res[a][f]=None
        continue
    for a,(sc,ov) in axes.items():
        for k,v in ov.items(): setattr(MC,k,v)
        try:
            pc=RE.precompute(g); ce=RE.central_estimate_v2(pc,mrow,sc)
            dist=float(mrow['distance_km'])
            res[a][f]=dict(dist=dist,E_gen=ce['E_gen'],E_trac=ce['E_trac_gross'],E_g2t=ce['E_gen_to_trac'],eta_bus=ce['eta_fuel_bus'],f_gen=ce['f_gen'])
            if a=='BASE':
                agg,ps=RE.central_estimate_v2_persample(pc,mrow,'central')
                sp=pd.to_numeric(g['speed'],errors='coerce').values
                base_ps[f]=(ps,sp,agg['f_gen'])
        finally:
            for k,v in ORIG.items(): setattr(MC,k,v)
    if i%50==0: print(i,flush=True)
out={'unfiltered':{}, 'clean259':{}}
base_nn={f for f,v in res['BASE'].items() if v and v['f_gen']==v['f_gen']}
f0='20260513_182950.csv'
out['drive_20260513_182950']={a:(None if res[a][f0] is None else res[a][f0]['f_gen']) for a in axes}
for a in axes:
    nn={f for f,v in res[a].items() if v and v['f_gen']==v['f_gen']}
    none=[f for f,v in res[a].items() if v is None]
    out['unfiltered'][a]=dict(n_notna=len(nn),n_loadfail=len(none),differs_from_BASE=sorted(nn^base_nn))
    rows=[v for f,v in res[a].items() if v and f not in excl]
    d=pd.DataFrame(rows); d['g100']=d.E_gen/d.dist*100; d['t100']=d.E_trac/d.dist*100; d['gt100']=d.E_g2t/d.dist*100
    c=d[d.f_gen.notna()]
    w=d.dist  # weights over all clean rows, pandas skipna semantic
    out['clean259'][a]=dict(n_rows=len(d),n_fgen=len(c),
      gen100=round(float((d.g100*d.dist).sum()/d.dist.sum()),2),trac100=round(float((d.t100*d.dist).sum()/d.dist.sum()),2),
      f_gen=round(float((c.gt100*c.dist).sum()/(c.t100*c.dist).sum()),3),
      eta_bus=round(float((d.eta_bus*d.dist).sum()/d.dist.sum()),3),
      # variant: restricted to f_gen notna rows
      gen100_fgenrows=round(float((c.g100*c.dist).sum()/c.dist.sum()),2),trac100_fgenrows=round(float((c.t100*c.dist).sum()/c.dist.sum()),2),
      eta_bus_fgenrows=round(float((c.eta_bus*c.dist).sum()/c.dist.sum()),3),
      f_gen_allclean_rows_nan0=round(float((d.gt100.fillna(0)*d.dist).sum()/(d.t100*d.dist).sum()),3))
# Part C
types=dict(zip(dm.file,dm.drive_type))
sim={}
for t in ['urban','mixed','mixed_highway','highway']:
    s=dict(fully=0.,gpb=0.,cad=0.,neut=0.,eon=0.); n=0
    for f,(ps,sp,fg) in base_ps.items():
        if f in excl or fg!=fg or types[f]!=t: continue
        dt=ps['dt'];eon=ps['Pgen_t']>0; P=ps['Ptrac']; B=ps['Pbatt_anch']
        full=eon&(P<0.5); rest=eon&~full
        s['fully']+=dt[full].sum(); s['gpb']+=dt[rest&(B>0.5)].sum(); s['cad']+=dt[rest&(B<-0.5)].sum()
        s['neut']+=dt[rest&(B>=-0.5)&(B<=0.5)].sum(); s['eon']+=dt[eon].sum()
        if dt[eon].sum()>0: n+=1
    e=s['eon']
    sim[t]=dict(n_drives=n,eon_hours=round(e/3600,3),fullyBanked=round(100*s['fully']/e,1),genPlusBattDischarge=round(100*s['gpb']/e,1),chargesAndDrives=round(100*s['cad']/e,1),genAloneNeutral=round(100*s['neut']/e,1))
out['simultaneity']=sim
bins=[(0,20),(20,60),(60,90),(90,120),(120,999)]
ss={}
for lo,hi in bins:
    G=B_=K=0.;n=0
    for f,(ps,sp,fg) in base_ps.items():
        if f in excl: continue
        dt=ps['dt']; m=np.isfinite(sp)&(sp>=lo)&(sp<hi)&(dt>0)
        if not m.any(): continue
        n+=1
        tp=np.maximum(ps['Ptrac'],0); gt=np.minimum(ps['Pgen_t'],tp); bt=tp-gt
        G+=(gt[m]*dt[m]).sum()/3600; B_+=(bt[m]*dt[m]).sum()/3600; K+=(sp[m]/3600*dt[m]).sum()
    ss[f'{lo}-{hi}']=dict(n_drives=n,km=round(K,1),gen100=round(G/K*100,2),batt100=round(B_/K*100,2),f_gen=round(G/(G+B_),4))
out['speedSplit']=ss
json.dump(out,open('analyses/M375_audit/audit_result_raw.json','w'),indent=1)
print(json.dumps(out,indent=1))
