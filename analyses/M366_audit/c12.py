import json,hashlib,os,re,glob
import pandas as pd, numpy as np
R='C:/Users/AndriiKharyshyn/Downloads/X-Trail Investigation/'
m=json.load(open('raw_manifest.json'))['files']
can=[x for x in m if x['role']=='canonical']
raw={re.sub(r'\D','',os.path.basename(p))[:14]:p for p in glob.glob('raw/*.csv')}
sh=lambda p:hashlib.sha256(open(p,'rb').read()).hexdigest()
orig_ok=0;rawfail=[];rawpass=0;missing=0
for x in can:
    k=re.sub(r'\D','',x['canonical'])[:14]; p=raw.get(k)
    if p is None: missing+=1;continue
    if sh(p)==x['sha256']: rawpass+=1
    else: rawfail.append(x)
for x in rawfail:
    o=R+'originals_recovered/'+x['canonical']
    if os.path.exists(o) and sh(o)==x['sha256']: orig_ok+=1
print('can',len(can),'missing',missing,'rawpass',rawpass,'rawfail',len(rawfail),'orig_ok',orig_ok)
allo=sum(1 for x in can if os.path.exists(R+'originals_recovered/'+x['canonical']) and sh(R+'originals_recovered/'+x['canonical'])==x['sha256'])
print('orig matching any canonical',allo)
rc=0;res={};nonnum=set();tot=0;diffrows={};mx={};cnt={}
cols=['[BMS] HV Battery Current (A)','[BMS] HV Battery Voltage (V)']
for x in rawfail:
    k=re.sub(r'\D','',x['canonical'])[:14]
    a=pd.read_csv(raw[k],dtype=str,keep_default_na=False);b=pd.read_csv(R+'originals_recovered/'+x['canonical'],dtype=str,keep_default_na=False)
    if len(a)!=len(b) or list(a.columns)!=list(b.columns): rc+=1;continue
    for c in a.columns:
        if (a[c]!=b[c]).any():
            na=pd.to_numeric(a[c],errors='coerce');nb=pd.to_numeric(b[c],errors='coerce')
            d=a[c]!=b[c]
            bad=d&(na.isna()|nb.isna())&~((a[c]=='')&(b[c]==''))
            if bad.any(): nonnum.add(c)
        if c in cols:
            na=pd.to_numeric(a[c],errors='coerce');nb=pd.to_numeric(b[c],errors='coerce')
            d=(na-nb).abs()
            diffrows[c]=diffrows.get(c,0)+int((d>0).sum());cnt[c]=cnt.get(c,0)+len(a);mx[c]=max(mx.get(c,0),np.nanmax(d))
print('rowcount/col mismatch pairs',rc)
print({c:(diffrows[c],cnt[c],diffrows[c]/cnt[c],mx[c]) for c in diffrows})
print('cols with non-numeric-type diffs',sorted(nonnum))
