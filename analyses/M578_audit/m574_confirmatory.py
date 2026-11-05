import pandas as pd, numpy as np, json, statsmodels.api as sm
from scipy import stats
d=pd.read_csv('drive_master.csv',encoding='utf-8')
d['date']=pd.to_datetime(d['date'])
print(d.ens_outlier_v2.value_counts(dropna=False).to_dict())
y,T,I,S='cell_spread_loaded_p95_mv','T_pack_mean_avg','peak_I_discharge','rf_socmean_wtd_pct'
e=d[(d.ens_outlier_v2!=True)&d[y].notna()].copy()
e=e[e[[T,I,S]].notna().all(axis=1)]
e['months']=(e.date-e.date.min()).dt.days/30.4375
e['day']=e.date.dt.strftime('%Y-%m-%d')
pre=e[e.date<'2026-10-01'];post=e[e.date>'2026-10-17']
X=lambda f:sm.add_constant(f[[T,I,S]],has_constant='add')
m=sm.OLS(pre[y],X(pre)).fit()
def cl(res,idx,j=None):
    pass
def resid_ci(p):
    r=(p[y]-m.predict(X(p))).values
    g=p.day.values;ds=pd.Series(r).groupby(g)
    # intercept-only cluster regression
    f=sm.OLS(r,np.ones(len(r))).fit(cov_type='cluster',cov_kwds={'groups':pd.factorize(g)[0]},use_t=False)
    G=len(set(g));se=f.bse[0];t=stats.t.ppf(.975,G-1)
    return dict(n=len(r),G=G,mean=float(r.mean()),ci=[float(r.mean()-t*se),float(r.mean()+t*se)])
# also manual CR1 w/ small-sample is in statsmodels cluster default (use_correction)
def resid_ci_cr1(p):
    r=(p[y]-m.predict(X(p))).values
    f=sm.OLS(r,np.ones(len(r))).fit(cov_type='cluster',cov_kwds={'groups':pd.factorize(p.day.values)[0],'use_correction':True,'df_correction':True})
    G=p.day.nunique();t=stats.t.ppf(.975,G-1);se=f.bse[0]
    return dict(n=len(r),G=G,mean=float(r.mean()),ci=[float(r.mean()-t*se),float(r.mean()+t*se)])
res=resid_ci_cr1(post)
s=e[e.date>='2026-10-01']
f=sm.OLS(s[y],sm.add_constant(s[['months',T,I,S]])).fit(cov_type='cluster',cov_kwds={'groups':pd.factorize(s.day.values)[0]})
G=s.day.nunique();t=stats.t.ppf(.975,G-1);b=f.params['months'];se=f.bse['months']
slope=dict(n=len(s),G=G,b=float(b),ci=[float(b-t*se),float(b+t*se)])
tmin=pre[T].min();p5=pre[T].quantile(.05)
below=int((post[T]<tmin).sum())
inr=post[(post[T]>=tmin)&(post[T]<=pre[T].max())]
out=dict(pre_n=len(pre),pre_days=pre.day.nunique(),post=dict(n=len(post),days=post.day.nunique()),resid=res,resid_naive_nocorr=resid_ci(post),slope=slope,Tmin=float(tmin),T_p5=float(p5),Tmax_pre=float(pre[T].max()),post_T_below_min=below,resid_inrange=resid_ci_cr1(inr) if inr.day.nunique()>1 else None)
lo,hi=res['ci'];sl=slope['ci']
out['labels_fit']=dict(raised_flat=lo>0 and sl[0]<=0<=sl[1],back=lo<=0<=hi,rise=sl[0]>0)
print(json.dumps(out,indent=1))
json.dump(out,open('analyses/M578_audit/m574_confirmatory.json','w',encoding='utf-8'),indent=1)
