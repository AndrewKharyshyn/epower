import pandas as pd, numpy as np, json, warnings
import statsmodels.formula.api as smf, statsmodels.api as sm
from statsmodels.regression.mixed_linear_model import MixedLMParams
warnings.filterwarnings('ignore')
d=pd.read_csv('drive_master.csv')
print(d.ens_outlier_v2.value_counts(dropna=False).to_dict())
d['dt']=pd.to_datetime(d['date'])
M={'A':('vreg_R_pack_mohm','vreg_I_p95_A'),'B':('cell_spread_loaded_p95_mv','peak_I_discharge')}
def elig(m):
    y,i=M[m]
    e=d[(d.ens_outlier_v2.astype(str).str.lower()=='false')].dropna(subset=[y,i,'T_pack_mean_avg']).copy()
    return e
def fit(e,m):
    y,i=M[m]
    e=e.copy(); e['months']=(e.dt-e.dt.min()).dt.days/30.4375
    e['yy']=e[y];e['T']=e.T_pack_mean_avg;e['I']=e[i];e['day']=e['date'].astype(str)
    f='yy ~ months + T + I'
    g=pd.factorize(e.day)[0]
    o=smf.ols(f,e).fit(cov_type='cluster',cov_kwds={'groups':g})
    ols=(o.params['months'],o.bse['months'])
    res={}
    md=smf.mixedlm(f,e,groups=e.day)
    for s in ['lbfgs','bfgs','nm']:
        r={'stage':None}
        try:
            fr=md.fit(method=s,reml=True,disp=False,maxiter=100)
            b=fr.params['months'];se=fr.bse['months'];ci=fr.conf_int().loc['months'].values
            dv=float(fr.cov_re.iloc[0,0]);sc=float(fr.scale)
            r.update(conv=bool(fr.converged),slope=b,se=se,ci=list(ci),dv=dv,sc=sc,llf=float(fr.llf))
            r['stage']='fitted' if r['conv'] else 'returned not converged'
            cand=r['conv'] and np.isfinite(se) and se>0
            r['sn']=None
            if s=='nm' and cand:
                rr=dv/sc; fe=fr.fe_params
                def L(x): return md.loglike(MixedLMParams.from_components(fe_params=fe,cov_re=np.array([[x]])),profile_fe=True)
                if rr>0:
                    h=1e-4*rr; lr=lambda t:L(np.exp(t))
                    t0=np.log(rr);hh=1e-4
                    r['sn']=float(abs((lr(t0+hh)-lr(t0-hh))/(2*hh)))
                cand = dv<=1e-8 or (r['sn'] is not None and r['sn']<=1e-3)
            r['cand']=bool(cand)
        except Exception as ex:
            r.update(stage='optimiser raised',err=repr(ex),cand=False)
        res[s]=r
    c=[s for s in res if res[s]['cand']]
    cnt=[];rep=None;agree='none'
    if c:
        best=max(res[s]['llf'] for s in c)
        cnt=[s for s in c if res[s]['llf']>=best-1e-4]
        rep=cnt[0]
        if len(cnt)==1: agree='single solver'
        else:
            sl=[res[s]['slope'] for s in cnt];dv=[res[s]['dv'] for s in cnt]
            ok=(max(sl)-min(sl))/ols[1]<=0.05 and (max(dv)-min(dv))/res[rep]['sc']<=0.005 \
              and len({x<=1e-8 for x in dv})==1 and len({(res[s]['ci'][0]>0 or res[s]['ci'][1]<0) for s in cnt})==1
            agree='agree' if ok else 'disagree'
    return dict(n=len(e),days=e.day.nunique(),ols=ols,res=res,counting=cnt,reported=rep,agree=agree)
out={}
for m in 'AB':
    e=elig(m).sort_values('dt')
    out[m]={'full':fit(e,m)}
    print(m,json.dumps(out[m]['full'],default=float)[:1500])
    cum=e.dt.dt.normalize()
    days=sorted(e.dt.unique());cc=e.groupby('dt').size().cumsum()
    ends=[];seen=set();N=len(e)
    for t in range(100,N+1,10):
        ed=cc[cc>=t].index[0]
        if ed not in seen: seen.add(ed);ends.append(ed)
    if cc.index[-1] not in seen: ends.append(cc.index[-1])
    pf=[]
    for ed in ends:
        r=fit(e[e.dt<=ed],m);pf.append((str(ed.date()),r))
    out[m]['prefix']=pf
    from collections import Counter
    print(m,len(pf),Counter(r['agree'] for _,r in pf),'lbfgs raised',sum(r['res']['lbfgs']['stage']=='optimiser raised' for _,r in pf))
    for ed,r in pf:
        if r['n']==154: print('154',ed,json.dumps(r['res'],default=float))
json.dump(out,open('analyses/M619_blind_audit/full_out.json','w',encoding='utf-8'),default=float,indent=1)
