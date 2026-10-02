import json,hashlib,io,sys,os
import numpy as np,pandas as pd
sys.path.insert(0,'.')
import compute_drive_summary_v6 as C
OR="C:/Users/AndriiKharyshyn/Downloads/X-Trail Investigation/originals_recovered/"
keys="2026-05-15 22-22-40,2026-05-23 11-33-05,2026-06-09 13-20-41,2026-06-10 09-41-00,2026-06-11 06-11-20,2026-06-18 12-46-11,2026-06-25 12-28-50,2026-06-27 08-52-19,2026-07-23 11-37-24".split(',')
man={f['record_id']:f for f in json.load(open('raw_manifest.json'))['files']}
dm=pd.read_csv('drive_master.csv')
cols=['cell_spread_loaded_p95_mv','cell_spread_loaded_max_mv','cell_spread_loaded_mean_mv','n_loaded_spread_samples']
chs=['[BMS] Max Cell Voltage (V)','[BMS] Min Cell Voltage (V)']
def grid(b):
    df=pd.read_csv(io.BytesIO(b),encoding='utf-8-sig',low_memory=False); o={}
    for c in chs:
        if c not in df: o[c]=None;continue
        v=np.unique(pd.to_numeric(df[c],errors='coerce').dropna().values)
        d=np.diff(v);d=d[d>0]
        o[c]=[int(len(v)),float(d.min()) if len(d) else None]
    return o
res=[];
for k in keys:
    dig=k.replace('-','').replace(' ','_'); dg=dig.replace('_','')
    m=dm[dm['file'].astype(str).str.replace(r'\D','',regex=True).str.contains(dg)]
    assert len(m)==1,(k,len(m)); row=m.iloc[0]; fn=row['file']
    ob=open(OR+dig+'.csv','rb').read(); rb=open('raw/'+k+'.csv','rb').read()
    rec=man[dig+'.csv']; shaok=hashlib.sha256(ob).hexdigest()==rec['sha256']
    r={'key':k,'file':fn,'orig_sha_ok':shaok,'raw_sha_ok':hashlib.sha256(rb).hexdigest()==rec['sha256']}
    for tag,b in(('orig',ob),('raw',rb)):
        a=C.analyze_bytes(b,fn)
        r[tag]={c:a.get(c) for c in cols}
        r[tag]['eq']=all(abs(float(a.get(c))-float(row[c]))<=1e-9 for c in cols)
        r[tag]['grid']=grid(b)
    r['pub']={c:float(row[c]) for c in cols}
    r['rawp95_absdiff_mv']=abs(float(r['raw']['cell_spread_loaded_p95_mv'])-float(row[cols[0]]))
    res.append(r);print(k,r['orig_sha_ok'],r['orig']['eq'],r['raw']['eq'],r['rawp95_absdiff_mv'])
d=[r['rawp95_absdiff_mv'] for r in res]
json.dump(res,open('analyses/M325_audit/results.json','w'),indent=1,default=str)
br={'n':9,'orig_sha_ok':sum(r['orig_sha_ok'] for r in res),'orig_eq_pub':sum(r['orig']['eq'] for r in res),'raw_eq_pub':sum(r['raw']['eq'] for r in res),'raw_p95_absdiff_mv_min':round(min(d),1),'raw_p95_absdiff_mv_max':round(max(d),1),
 'grid':{r['key']:{'orig':r['orig']['grid'],'raw':r['raw']['grid']} for r in res}}
json.dump(br,open('analyses/M325_audit/brief.json','w'),default=str);print(json.dumps(br,default=str))
