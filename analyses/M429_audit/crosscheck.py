import json, numpy as np, pandas as pd, sys
sys.path.insert(0,'analyses/M429_audit')
d=json.load(open('analyses/M429_pairs.json',encoding='utf-8'))
m=pd.read_csv('drive_master.csv',usecols=['file','time_start','time_end','date'])
print(len(m), m.head(3).to_string())
m['ts']=pd.to_datetime(m['date']+' '+m['time_start'],format='%Y-%m-%d %H:%M:%S.%f',errors='coerce'); m['te']=pd.to_datetime(m['date']+' '+m['time_end'],format='%Y-%m-%d %H:%M:%S.%f',errors='coerce')
m.loc[m.te<m.ts,'te']+=pd.Timedelta(days=1)
m=m.sort_values('ts').reset_index(drop=True)
m['gap']=(m['ts'].shift(-1)-m['te']).dt.total_seconds()/3600
m['arr']=m['ts'].shift(-1).dt.strftime('%Y-%m-%d'); m['dep']=m['ts'].dt.strftime('%Y-%m-%d'); m['dep_end']=m['te'].dt.strftime('%Y-%m-%d')
print(m[['ts','te','gap','arr','dep']].head())
for name,fit in zip(d['order'],d['fits']):
    g=np.array(fit['gapH']); ar=fit['arrivalDay']; dp=fit['departureDay']
    mg=m['gap'].values
    miss=0; dayok=0; depok=0; depend=0
    for gi,a,dd in zip(g,ar,dp):
        j=np.where(np.abs(mg-gi)<1e-4)[0]
        if len(j)==0: miss+=1; continue
        r=m.iloc[j[0]]
        dayok+= any(m.iloc[jj]['arr']==a for jj in j)
        depok+= any(m.iloc[jj]['dep']==dd for jj in j)
        depend+= any(m.iloc[jj]['dep_end']==dd for jj in j)
    print(name,'n',len(g),'unmatched gap',miss,'arrival ok',dayok,'dep(start-day) ok',depok,'dep(end-day) ok',depend)
