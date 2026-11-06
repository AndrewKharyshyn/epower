import pandas as pd, numpy as np, sys, json
R='C:/Users/AndriiKharyshyn/Downloads/X-Trail Investigation/Repo/xtrail-repo/'
m=pd.read_csv(R+'drive_master.csv'); v=m[m.deficit_80_120_valid==True]
CUR='[BMS] HV Battery Current (A)';VOL='[BMS] HV Battery voltage (V)';RPM='Оберти двигуна (rpm)'
def tsec(s):
    p=s.str.split(':',expand=True).astype(float); t=p[0]*3600+p[1]*60+p[2]
    return t+86400*(t.diff().fillna(0)<-43200).cumsum()
def near(base,df,col,tol):
    x=df[['t',col]].dropna().sort_values('t')
    return pd.merge_asof(base[['t']],x,on='t',direction='nearest',tolerance=tol)[col].values
def drive(f,mode):
    import re; k=re.sub(r'[^0-9]','',f[:-4]); fn=R+'raw/%s-%s-%s %s-%s-%s.csv'%(k[0:4],k[4:6],k[6:8],k[8:10],k[10:12],k[12:14])
    d=pd.read_csv(fn,low_memory=False); d['t']=tsec(d['time'])
    c=d[['t',CUR]].dropna().sort_values('t').reset_index(drop=True)
    sp=near(c,d,'[VCM] Vehicle Speed (km/h)',3.0) if '[VCM] Vehicle Speed (km/h)' in d else np.full(len(c),np.nan)
    so=near(c,d,'Швидкість автомобіля (km/h)',3.0)
    sp=np.where(np.isnan(sp),so,sp)
    rp=near(c,d,RPM,3.0); vo=near(c,d,VOL,1.5)
    dt=c.t.diff() if mode=='back' else -c.t.diff(-1)
    dt=dt.fillna(0).clip(upper=5).values
    ok=(c[CUR].abs()<900)&(vo>=200)&(vo<=450)&~np.isnan(sp)&~np.isnan(rp)
    b=ok&(sp>=80)&(sp<=120); e=b&(rp>400); dd=e&(c[CUR]<0)
    return dt[b].sum(),dt[e].sum(),dt[dd].sum()
mode=sys.argv[1] if len(sys.argv)>1 else 'back'
rows=[]
for f,dte in zip(v.file,v.date):
    B,E,D=drive(f,mode); rows.append((f,dte,B,E,D))
df=pd.DataFrame(rows,columns=['file','date','B','E','D'])
df['J']=100*df.D/df.B; df['C']=100*df.D/df.E; df['R']=100*df.E/df.B; df['CJ']=df.C-df.J
df.to_csv(R+'audit/hwshare_perdrive_%s.csv'%mode,index=False)
rng=np.random.default_rng(42)
days=df.date.unique(); g={d:df[df.date==d] for d in days}
def stat(x,col,mask=None):
    y=x if mask is None else x[mask(x)]
    return y[col].mean() if len(y) else np.nan
def boot(col,mask=None):
    est=stat(df,col,mask); bs=[]
    for _ in range(4000):
        s=pd.concat([g[d] for d in rng.choice(days,len(days))]); bs.append(stat(s,col,mask))
    return est,np.nanpercentile(bs,[2.5,97.5]).tolist()
m60=lambda x:x.E>=60
out={'n_drives':len(df),'n_days':len(days),'n_E60':int((df.E>=60).sum())}
out['J']=boot('J'); out['C']=boot('C',m60); out['R']=boot('R',m60); out['CJ']=boot('CJ',m60)
out['pooledJ']=100*df.D.sum()/df.B.sum(); out['pooledC']=100*df.D.sum()/df.E.sum()
print(mode,json.dumps(out,default=float))
print(df.sample(10,random_state=1).round(1).to_string())
