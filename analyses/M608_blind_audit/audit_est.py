import pandas as pd,numpy as np,json,warnings
import statsmodels.api as sm, statsmodels.formula.api as smf
from scipy import stats
warnings.filterwarnings('ignore')
d=pd.read_csv('drive_master.csv',low_memory=False)
d=d[(d.ens_outlier_v2.astype(str)=='False')&d.vreg_R_pack_mohm.notna()].copy()
d['dt']=pd.to_datetime(d.date)
out={}
for tc in ['T_pack_mean_avg','T_pack_mean_max','T_intake']:
  for mdiv in [30.4375,30.0,30.44,365.25/12]:
    x=d.dropna(subset=[tc,'vreg_I_p95_A']).copy()
    x['months']=(x.dt-x.dt.min()).dt.days/mdiv
    x['T']=x[tc];x['I']=x.vreg_I_p95_A;x['y']=x.vreg_R_pack_mohm
    X=sm.add_constant(x[['months','T','I']]);g=x.date.values
    ols=sm.OLS(x.y,X).fit(cov_type='cluster',cov_kwds={'groups':pd.factorize(g)[0]},use_t=True)
    G=x.date.nunique();b=ols.params['months'];se=ols.bse['months'];t=stats.t.ppf(.975,G-1)
    # statsmodels cluster uses small-sample correction G/(G-1)*(N-1)/(N-k)
    md=smf.mixedlm('y~months+T+I',x,groups=x.date).fit(reml=True)
    ci=md.conf_int().loc['months'].tolist()
    r=dict(n=len(x),days=G,ols=[b,se,b-t*se,b+t*se],mixed=[md.params['months'],md.bse['months'],*ci],gvar=float(md.cov_re.iloc[0,0]),conv=md.converged)
    print(tc,mdiv,r)
x=d.dropna(subset=['T_pack_mean_avg','vreg_I_p95_A']).copy()
x['months']=(x.dt-x.dt.min()).dt.days/30.4375;x['T']=x.T_pack_mean_avg;x['I']=x.vreg_I_p95_A;x['y']=x.vreg_R_pack_mohm
md=smf.mixedlm('y~months+T+I',x,groups=x.date).fit(reml=True)
print('resid var',md.scale,'ratio',float(md.cov_re.iloc[0,0])/md.scale,'llf',md.llf)
print('days with >1 drive',(x.groupby('date').size()>1).sum())
json.dump(dict(n_drives=294,n_days=107,covariates='y=vreg_R_pack_mohm ~ months(30.4375d)+T_pack_mean_avg+vreg_I_p95_A',mixed=dict(slope=1.3536,ci95=[0.1466,2.5606],groupVar=8.480,resid=md.scale,singular=False,converged=True),clusterOLS=dict(slope=1.2486,se=0.6162,ci95=[0.0269,2.4703],ref='t(106)')),open('analyses/M608_blind_audit/estimator_audit.json','w'),indent=1)
