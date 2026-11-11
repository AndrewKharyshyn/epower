import json, warnings
import numpy as np, pandas as pd, statsmodels.api as sm, statsmodels.formula.api as smf
from scipy import stats
warnings.filterwarnings('ignore')
import sys
METH=int(sys.argv[1]) if len(sys.argv)>1 else 1
d=pd.read_csv('drive_master.csv',encoding='utf-8')
d['date']=pd.to_datetime(d['date'])
d=d.sort_values(['date','file'],kind='stable').reset_index(drop=True)
d['row']=np.arange(1,len(d)+1)
flag=d['ens_outlier_v2'].astype(str).str.lower().isin(['true','1','1.0'])
cols=['vreg_R_pack_mohm','T_pack_mean_avg','vreg_I_p95_A']
el=d[~flag & d[cols].notna().all(axis=1)].copy()
def fit(e):
    e=e.copy(); e['months']=(e['date']-e['date'].min()).dt.days/30.4375
    e['g']=e['date'].dt.strftime('%Y%m%d'); e=e.rename(columns={'vreg_R_pack_mohm':'y','T_pack_mean_avg':'T','vreg_I_p95_A':'I'})
    G=e.g.nunique()
    X=sm.add_constant(e[['months','T','I']])
    o=sm.OLS(e.y,X).fit(cov_type='cluster',cov_kwds={'groups':pd.factorize(e.g)[0],'use_correction':True,'df_correction':True},use_t=False)
    b,se=o.params['months'],o.bse['months']
    t=stats.t.ppf(.975,G-1); out=dict(n=len(e),G=G,ols=b,ols_se=se,ols_ci=[b-t*se,b+t*se])
    try:
        m=smf.mixedlm('y~months+T+I',e,groups=e.g).fit(reml=True,method=['lbfgs'] if METH==1 else ['bfgs','lbfgs','nm'])
        out.update(m_conv=bool(m.converged),m=m.params['months'],m_se=m.bse['months'],gv=float(m.cov_re.iloc[0,0]),rv=float(m.scale))
        m_ci=[out['m']-1.96*out['m_se'],out['m']+1.96*out['m_se']]; out['m_ci']=m_ci
    except Exception as ex:
        out.update(m_conv=False,m=np.nan,m_se=np.nan,gv=np.nan,rv=np.nan,m_ci=[np.nan,np.nan],err=str(ex))
    return out
full=fit(el)
res={'claim1_3':full}
res['ratio_gv_rv']=full['gv']/full['rv']; res['se_ratio']=full['m_se']/full['ols_se']
res['signed_diff']=(full['m']-full['ols'])/full['ols_se']
cum=el.groupby('date').size().cumsum()
pts=[]
for k in list(range(100,291,10)):
    ds=cum[cum>=k]
    if len(ds): pts.append(ds.index[0])
pts.append(el['date'].max())
rep=[]
def ok(o): return bool(o['m_conv'] and o['gv']>1e-8 and np.isfinite(o['m_se']) and o['m_se']<=25*o['ols_se'])
for p in pts:
    o=fit(el[el.date<=p]); 
    rep.append(dict(end=str(p.date()),n=o['n'],G=o['G'],conv=o['m_conv'],singular=bool(o['gv']<=1e-8),se_ratio=o['m_se']/o['ols_se'],sdiff=(o['m']-o['ols'])/o['ols_se'],ok=ok(o),ok_noSingular=bool(o['m_conv'] and o['m_se']<=25*o['ols_se']),excl0_ols=not(o['ols_ci'][0]<=0<=o['ols_ci'][1]),excl0_m=not(o['m_ci'][0]<=0<=o['m_ci'][1])))
res['replay']=rep
for key in ('ok','ok_noSingular'):
    s=[r[key] for r in rep]; res['flips_'+key]=sum(a!=b for a,b in zip(s,s[1:]))
res['max_abs_sdiff_G30']=max([abs(r['sdiff']) for r in rep if r['G']>=30 and np.isfinite(r['sdiff'])])
res['full_excl0']=(rep[-1]['excl0_ols'],rep[-1]['excl0_m'])
p632=d.loc[631,'date']; p665=d.loc[len(d)-1,'date']
res['p632']=str(p632.date()); res['p665']=str(p665.date()); res['n_master']=len(d)
for nm,p in (('p632',p632),('p665',p665)):
    o=fit(el[el.date<=p]); res[nm+'_fit']=dict(n=o['n'],conv=o['m_conv'],gv=o['gv'],se_ratio=o['m_se']/o['ols_se'],ok=ok(o))
json.dump(res,open('analyses/M614_blind_audit/result.json' if METH==1 else 'analyses/M614_blind_audit/result_alt_optimizer.json','w',encoding='utf-8'),indent=1,default=str)
print(json.dumps(res,indent=1,default=str))
