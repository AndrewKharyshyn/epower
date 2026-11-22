import sys, numpy as np, pandas as pd
sys.path.insert(0,'analyses/M731_frozen_engine/root/tools'); sys.path.insert(0,'analyses/M731_frozen_engine/root')
import restart_census as RC, park_model as PM, exposure_state as ES
E=pd.read_csv('analyses/M732/p1_basis_replay_sidecar_planted.csv',dtype={'key':str})
bad=E[E['error'].notna()|E.utc0.isna()] if 'error' in E else E[E.utc0.isna()]
dropk=list(bad.key); E=E.drop(bad.index).reset_index(drop=True); E=E.sort_values('key').reset_index(drop=True)
BRK=set()
for z in dropk:
    nx=E[E.key>z.rstrip('z')+'z']; BRK.add(nx.key.iloc[0]) if len(nx) else None
print('dropped',dropk,'break at',BRK)
E['local0']=pd.to_datetime(E['local0'],format='ISO8601'); E['key']=E['key'].astype(str)
E['utc0']=E['utc0'].astype(float);E['utc1']=E['utc1'].astype(float)
E=E.sort_values('utc0').reset_index(drop=True)
E=E.rename(columns={'odo_start':'odo_start','soc_first':'soc_first'})
E['day']=E['local0'].dt.strftime('%Y-%m-%d'); E['month']=E['local0'].dt.month
E['h0']=E.local0.dt.hour+E.local0.dt.minute/60+E.local0.dt.second/3600; E['h1']=E.h0+E.dur_s/3600
AMP,HPK,TAU,OFF=5.8,15.543,9.105,0.469
E['Abar_s']=E.A0-AMP*np.cos(PM.W*(E.h0-HPK)); E['Abar_e']=E.A1-AMP*np.cos(PM.W*(E.h1-HPK))
prm=dict(c0=23.87691,c1=0.220106,tau_d=0.986873,alpha=0.013093,EaR=17.582)
P=RC.build_pairs(E,dict(zip(E.key,E.A0)))
I2=E[[f'i2_{i}' for i in range(16)]].values
Ts=E[[f'T{i}_s' for i in range(1,5)]].values; Te=E[[f'T{i}_e' for i in range(1,5)]].values
Tstart=np.where(np.isfinite(Ts).all(1),Ts.mean(1),np.nan); Tend=np.where(np.isfinite(Te).all(1),Te.mean(1),np.nan)
def boot(day,cols,seed=42):
    d=pd.DataFrame(cols); d['c']=np.asarray(day); g=d.groupby('c').agg(['sum','count']); n=len(g)
    W=np.random.default_rng(seed).multinomial(n,np.ones(n)/n,size=4000).astype(float)
    out={}
    for c in cols:
        out[c]=np.percentile((W@g[c]['sum'].values)/(W@g[c]['count'].values),[2.5,97.5])
    return out,n
def rep(name,day,cols,tol):
    b,n=boot(day,cols); print(name,'n',len(day),'nDays',n,{c:(round(float(np.mean(v)),6),[round(x,6) for x in b[c]]) for c,v in cols.items()})
# Part A
mask=E.month.isin([10,11]).values; idx=np.where(mask)[0]
err=[];days=[];reanch=0;prev=None;Tsim=None
for k in idx:
    ok=np.isfinite(Tstart[k]) and np.isfinite(E.A0[k]) and np.isfinite(E.A1[k]) 
    if prev is None or not ok:
        Tsim=Tstart[k] if ok else np.nan
        if not np.isfinite(Tsim) : prev=None; continue
        prev=k; reanch+=1 if prev!=idx[0] else 0; continue
    p=prev
    if E.key[k] in BRK:
        Tsim=Tstart[k];prev=k;continue
    gap=(E.utc0[k]-E.utc1[p])/3600
    if gap<0 or E.utc0[k]==E.utc0[p] or not np.isfinite(Tsim) or not np.isfinite(E.A0[p]):
        Tsim=Tstart[k];prev=k;reanch+=1;continue
    _,Tend_s=ES.drive_path(np.array([Tsim]),I2[p:p+1],np.array([E.dur_s[p]/3600/16]),np.array([(E.A0[p]+E.A1[p])/2]),prm)
    slope=(E.Abar_s[k]-E.Abar_e[p])/max(gap,1e-3)
    Tn=PM.park_T(Tend_s[0],gap,E.h1[p]%24,E.Abar_e[p],slope,AMP,HPK,TAU,OFF)
    if not np.isfinite(Tn): Tsim=Tstart[k];prev=k;reanch+=1;continue
    if np.isfinite(Tstart[k]) and E.icov[k]>=0.8: err.append(Tn-Tstart[k]);days.append(E.day[k])
    Tsim=Tn;prev=k
err=np.array(err);print('reanchors',reanch)
rep('A',days,{'bias':err,'mae':np.abs(err)},None)
# Part B
P['brk']=P.n_key.isin(BRK);print('B-pair across drop elig/flag',P[P.brk][['elig','flagged','gap_h']].to_dict('records'));P=P[~P.brk&P.elig&~P.flagged&P.n_local0.dt.month.isin([10,11])].copy()
pe=P[[f'p_T{i}_e' for i in range(1,5)]].values; ns=P[[f'n_T{i}_s' for i in range(1,5)]].values
Ab=E.set_index('key')
P['x0']=pe.mean(1);P['y']=ns.mean(1)
P['pAe']=P.p_key.map(Ab.Abar_e);P['nAs']=P.n_key.map(Ab.Abar_s);P['ph1']=P.p_key.map(Ab.h1)
P=P.dropna(subset=['x0','y','pAe','nAs','ph1'])
sl=(P.nAs-P.pAe)/P.gap_h.clip(lower=1e-3)
P['pred']=PM.park_T(P.x0.values,P.gap_h.values,(P.ph1%24).values,P.pAe.values,sl.values,AMP,HPK,TAU,OFF)
P['bias']=P.pred-P.y
for nm,m in [('B1',P.gap_h>=12),('B2',(P.y>=7)&(P.y<=13)),('B3',(P.y>=12)&(P.y<=18))]:
    q=P[m]; rep(nm,q.day,{'bias':q.bias.values},None)
