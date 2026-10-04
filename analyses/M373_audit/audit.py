import os,sys,json
os.environ['PYTHONUTF8']='1'
R=os.getcwd(); os.environ['XT_RAW_DIR']=R+'/raw_only'
sys.path.insert(0,R)
import numpy as np,pandas as pd
import recon_engine as RE, fuel_recon as FR, model_constants as MC
dm=pd.read_csv('raw_only/drive_master.csv')
const=FR.corpus_offset(dm)[0]
frm=set(pd.read_csv('fuel_recon_master.csv')['file'])
elig=[];clean=[];sim={};sp={};rows=[]
BINS=[(0,20),(20,60),(60,90),(90,120),(120,999)]
spacc={b:dict(g=0.,b=0.,km=0.,drv=set()) for b in BINS}
spdays=set(); spdrv=set()
simacc={}
for _,m in dm.iterrows():
    f=m['file']; fp=RE.BASE+f
    if not os.path.exists(fp) or not FR._has_fuel(fp): continue
    if not (m['distance_km']>0): continue
    off=FR.resolve_offset(m,const)[0]
    g=RE.load_drive(f,off)
    if g is None: continue
    elig.append(f)
    day=str(m['time_start'])[:10]
    pc=RE.precompute(g)
    agg,ps=RE.central_estimate_v2_persample(pc,m,'central')
    isclean=not np.isnan(agg['f_gen'])
    if isclean:
        clean.append(f)
        ce={s:RE.central_estimate_v2(pc,m,s) for s in ['central','optimistic']}
        old=MC.P_AUX_KW; MC.P_AUX_KW=(1.2,)+tuple(old[1:])
        try: ce['paux']=RE.central_estimate_v2(pc,m,'central')
        finally: MC.P_AUX_KW=old
        rows.append(dict(file=f,day=day,dist=m['distance_km'],**{f'{k}_{n}':v[n] for k,v in ce.items() for n in ['E_gen','E_trac_gross','E_gen_to_trac','eta_fuel_bus','f_gen']}))
        dt_=m['drive_type']
        if dt_ in ('urban','mixed','mixed_highway','highway'):
            P=ps['Ptrac'];Pg=ps['Pgen_t'];Pb=ps['Pbatt_anch'];dt=ps['dt']
            eon=Pg>0
            if eon.any():
                fb=eon&(P<0.5); hi=eon&(P>=0.5)
                gb=hi&(Pb>0.5); cd=hi&(Pb<-0.5); ga=hi&~gb&~cd
                a=simacc.setdefault(dt_,dict(fb=0.,gb=0.,cd=0.,ga=0.,n=0,days=set(),drv=[]))
                a['fb']+=dt[fb].sum();a['gb']+=dt[gb].sum();a['cd']+=dt[cd].sum();a['ga']+=dt[ga].sum()
                a['n']+=1;a['days'].add(day);a['drv'].append(f)
    if f in frm:
        spdrv.add(f);spdays.add(day)
        sped=pd.to_numeric(g['speed'],errors='coerce').values
        P=ps['Ptrac'];Pg=ps['Pgen_t'];dt=ps['dt']
        tp=np.maximum(P,0);gt=np.minimum(Pg,tp);bt=tp-gt
        for b in BINS:
            k=np.isfinite(sped)&(sped>=b[0])&(sped<b[1])&(dt>0)
            if k.any():
                a=spacc[b];a['drv'].add(f)
                a['g']+=(gt[k]*dt[k]).sum()/3600;a['b']+=(bt[k]*dt[k]).sum()/3600;a['km']+=(sped[k]/3600*dt[k]).sum()
out={}
dfc=pd.DataFrame(rows)
cd=dm.set_index('file')
out['n_eligible']=len(elig);out['n_clean']=len(clean)
out['eligible_not_clean']=[f for f in elig if f not in clean]
out['eligible_days']=len({str(cd.loc[f,'time_start'])[:10] for f in elig})
out['clean_days']=dfc['day'].nunique()
out['clean_ids']=clean
o={}
for t,a in simacc.items():
    tot=a['fb']+a['gb']+a['cd']+a['ga']
    o[t]=dict(n=a['n'],days=len(a['days']),eon_h=round(tot/3600,1),**{k:round(a[k]/tot*100,1) for k in['fb','gb','cd','ga']})
out['sim']=o
out['sim_n']=sum(a['n'] for a in simacc.values()); out['sim_days']=len(set().union(*[a['days'] for a in simacc.values()]))
out['speed']={f'{b[0]}-{b[1]}':dict(n=len(a['drv']),km=round(a['km'],1),gen100=round(a['g']/a['km']*100,2),batt100=round(a['b']/a['km']*100,2),f_gen=round(a['g']/(a['g']+a['b']),4)) for b,a in spacc.items()}
out['speed_n_drives']=len(spdrv);out['speed_n_days']=len(spdays)
def wm(x,w): return x.fillna(0).mul(w).sum()/w.sum() if False else (x*w).sum()/w.sum()
sens={}
for key,k in [('BASE','central'),('BSFC optimistic','optimistic'),('P_aux high','paux')]:
    w=dfc['dist']
    gen=dfc[f'{k}_E_gen']/w*100;tr=dfc[f'{k}_E_trac_gross']/w*100;g2=dfc[f'{k}_E_gen_to_trac']/w*100
    sens[key]=dict(gen100=round((gen*w).sum()/w.sum(),2),trac100=round((tr*w).sum()/w.sum(),2),f_gen=round((g2*w).sum()/(tr*w).sum(),3),eta=round((dfc[f'{k}_eta_fuel_bus']*w).sum()/w.sum(),3))
out['sens']=sens
json.dump(out,open('analyses/M373_audit/audit_result.json','w'),indent=1,ensure_ascii=False)
print(json.dumps({k:v for k,v in out.items() if k!='clean_ids'},indent=1))
