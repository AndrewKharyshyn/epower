import os,sys,re,json,hashlib,random,warnings
warnings.filterwarnings('ignore')
import pandas as pd, numpy as np
R='C:/Users/AndriiKharyshyn/Downloads/X-Trail Investigation/Repo/xtrail-repo'
O='C:/Users/AndriiKharyshyn/Downloads/X-Trail Investigation/originals_recovered'
A=R+'/analyses/F03_originals/G4_audit'
os.chdir(R); sys.path.insert(0,R); os.environ['XT_RAW_DIR']=R+'/raw'
import compute_drive_summary_v6 as C
dg=lambda s:re.sub(r'\D','',s)[:14]
man={dg(f['record_id']):f for f in json.load(open('raw_manifest.json'))['files']}
sha=lambda b:hashlib.sha256(b).hexdigest()
# 1 originals hash
ok=0;bad=[];ofiles={}
for f in os.listdir(O):
    k=dg(f);b=open(O+'/'+f,'rb').read();ofiles[k]=O+'/'+f
    if k in man and man[k]['sha256']==sha(b): ok+=1
    else: bad.append(f)
print('orig sha ok',ok,'bad',bad)
rawf={dg(f):R+'/raw/'+f for f in os.listdir('raw') if f.endswith('.csv')}
M=pd.read_csv('drive_master.csv'); M['k']=M.file.map(dg); Mi=M.set_index('k')
Mo=pd.read_csv(A+'/master_old.csv'); Mo['k']=Mo.file.map(dg); Moi=Mo.set_index('k')
ML=set('drive_cluster_k3 iso_outlier iso_score lof_score f_iso f_lof f_mad f_domain ens_outlier f_domain_2p f_iso_i f_lof_i f_mad_i ens_invalid ens_extreme ens_outlier_v2'.split())
skip=lambda c: c in ML or c=='file' or re.search(r'_corr|_applied|offset_|implied_offset|_adj_',c)
# hash status of raw copies
fail=[k for k in ofiles if k in rawf and sha(open(rawf[k],'rb').read())!=man[k]['sha256']]
passk=[k for k in rawf if k in man and k in Mi.index and k not in ofiles and sha(open(rawf[k],'rb').read())==man[k]['sha256']]
print('orig keys',len(ofiles),'raw-fail among them',len(fail),'pass pool',len(passk))
def numdiff(k):
    try:
        a=pd.read_csv(ofiles[k]);b=pd.read_csv(rawf[k]);n=min(len(a),len(b))
        nc=[c for c in a.columns if c in b.columns and pd.api.types.is_numeric_dtype(a[c])]
        return float(np.nanmean([np.nanmax(np.abs(a[c].values[:n]-b[c].values[:n])) for c in nc]))
    except Exception: return np.nan
random.seed(1)
df=pd.DataFrame({'k':fail}); df['m']=df.k.str[:6]; df['d']=df.k.map(numdiff)
df['q']=pd.qcut(df.d.rank(method='first'),4,labels=False)
samp=[]
for m,g in df.groupby('m'):
    samp+=list(g.sample(min(len(g),max(1,round(40*len(g)/len(df)))),random_state=1).k)
for q,g in df.groupby('q'):
    if not set(g.k)&set(samp): samp.append(g.k.iloc[0])
print('sample',len(samp),'months',df.m.nunique(),df.groupby('q').k.apply(lambda s:len(set(s)&set(samp))).tolist())
ctrl=random.sample([k for k in passk],10)
def cmp(res,row,cols):
    mm=[]
    for c in cols:
        if c not in res: continue
        a=res[c];b=row[c]
        if (pd.isna(b) if not isinstance(b,str) else False) and (a is None or (not isinstance(a,str) and pd.isna(a))): continue
        try:
            if isinstance(b,str) or isinstance(a,str): ok=str(a)==str(b)
            else: ok=abs(float(a)-float(b))<=1e-9
        except Exception: ok=False
        if not ok: mm.append(c)
    return mm
rows=[];colstat={}
for grp,ks in (('fail',samp),('pass_ctrl',ctrl)):
  for k in ks:
    if k not in Mi.index: continue
    row=Mi.loc[k]; fn=row['file']
    cols=[c for c in M.columns if not skip(c) and c!='k']
    out={'k':k,'grp':grp}
    for ref,rd in (('new',(Mi,row)),('old',(Moi,Moi.loc[k] if k in Moi.index else None))):
        if rd[1] is None: continue
        for src,path in (('orig',ofiles.get(k)),('raw',rawf.get(k))):
            if not path: continue
            try: res=C.analyze_bytes(open(path,'rb').read(),fn)
            except Exception as e: out[f'{ref}_{src}']='ERR '+str(e)[:60]; continue
            cc=[c for c in cols if c in rd[1].index]
            mm=cmp(res,rd[1],cc)
            out[f'{ref}_{src}']=len(mm); out[f'{ref}_{src}_ncmp']=len([c for c in cc if c in res])
            out[f'{ref}_{src}_cols']=mm
            for c in mm: colstat.setdefault((ref,src,c),0); colstat[(ref,src,c)]+=1
            out['skipped_not_in_result']=[c for c in cc if c not in res][:50]
    rows.append(out); print(k,grp,{x:out.get(x) for x in out if not x.endswith('cols') and x!='skipped_not_in_result'},flush=True)
json.dump({'rows':rows,'colstat':{'|'.join(k):v for k,v in colstat.items()}},open(A+'/results.json','w'),default=str,indent=1)
