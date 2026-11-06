import numpy as np, pandas as pd, json
P=pd.read_csv('analyses/M578_audit/m505_r3_proxies.csv')
M=pd.read_csv('drive_master.csv',usecols=['file','date','vreg_R_pack_mohm','vreg_I_p95_A','T_pack_mean_avg','ens_outlier_v2'])
import re
nk=lambda x:re.sub(r'\D','',x)[:14]
M['k']=M.file.map(nk);P['k']=P.file.map(nk);P=P.drop(columns='file')
D=M.merge(P,on='k',how='left')
a=D.A0.notna()
print('master n',D.vreg_R_pack_mohm.notna().sum(),'A0 n',a.sum(),'A0 nonnan',D.A0.notna().sum())
both=D.vreg_R_pack_mohm.notna()&D.A0.notna()
print('both',both.sum(),'equal(0.01)',(abs(D.A0-D.vreg_R_pack_mohm)[both]<=0.011).sum(),'equal(0.1)',(abs(D.A0-D.vreg_R_pack_mohm)[both]<=0.1).sum())
print('master only',(D.vreg_R_pack_mohm.notna()&D.A0.isna()).sum(),'mine only',(D.vreg_R_pack_mohm.isna()&D.A0.notna()).sum())
print('p95 diff max',abs(D.A0_p95-D.vreg_I_p95_A)[both].max())
print(D[both&(abs(D.A0-D.vreg_R_pack_mohm)>0.011)][['file','vreg_R_pack_mohm','A0']].head(10))
D['months']=(pd.to_datetime(D.date)-pd.to_datetime(D.date).min()).dt.days/30.4375
clean=D.ens_outlier_v2.astype(str)!='True'
rng=np.random.default_rng(42)
out={}
for v in ['A0','A1','A2','A3','A4','V1']:
    q=D[v]; u=q.notna()&clean&D.T_pack_mean_avg.notna()&D[v+'_p95'].notna()
    d=D[u]; X=np.c_[np.ones(len(d)),d.months,d.T_pack_mean_avg,d[v+'_p95']]; y=d[v].values
    b=np.linalg.lstsq(X,y,rcond=None)[0][1]
    days=d.date.values; ud=np.unique(days); idx={k:np.where(days==k)[0] for k in ud}
    bs=[]
    for _ in range(4000):
        s=rng.choice(len(ud),len(ud)); ii=np.concatenate([idx[ud[k]] for k in s])
        bs.append(np.linalg.lstsq(X[ii],y[ii],rcond=None)[0][1])
    lo,hi=np.percentile(bs,[2.5,97.5])
    sh=(D[v]-D.A0)[u&D.A0.notna()]
    out[v]=dict(n=int(u.sum()),days=int(len(ud)),slope=round(b,3),ci=[round(lo,2),round(hi,2)],shift_n=int(sh.notna().sum()),shift_median=round(float(sh.median()),2))
    print(v,out[v])
json.dump(out,open('analyses/M578_audit/m505_r3_s0.json','w',encoding='utf-8'),indent=1)
