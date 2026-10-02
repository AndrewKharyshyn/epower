import os,re,json,hashlib,pandas as pd,numpy as np
R='raw';O='../../originals_recovered'
man={r['record_id']:r for r in json.load(open('raw_manifest.json'))['files'] if r['role']=='canonical'}
def test(path):
    df=pd.read_csv(path,low_memory=False)
    cols=[c for c in df.columns if ('Max Cell Voltage' in c or 'Min Cell Voltage' in c) and not re.search(r'G\d\d',c)]
    cols=[c for c in cols if not re.match(r'\s*G\d+',c)]
    if not cols: return dict(status='unchecked')
    ser={c:pd.to_numeric(df[c],errors='coerce').dropna() for c in cols}
    if all(len(s)==0 for s in ser.values()): return dict(status='unchecked')
    allv=pd.concat(ser.values())
    r1=bool(((allv<2.5)|(allv>4.3)).any())
    r2c={};unt=[]
    for c,s in ser.items():
        u=np.unique(s.values)
        if len(u)<5: unt.append(c);continue
        st=np.diff(u);st=st[st>0]
        if len(st) and st.min()>=0.05-1e-12: r2c[c]=float(st.min())
    return dict(status='ok',cols=cols,r1=r1,r2=bool(r2c),r2cols=r2c,untested=unt)
res={}
def sha(p): return hashlib.sha256(open(p,'rb').read()).hexdigest()
for f in sorted(os.listdir(R)):
    if not re.match(r'^\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}\.csv$',f): continue
    rid=f[:10].replace('-','')+'_'+f[11:19].replace('-','')+'.csv'
    m=man.get(rid)
    if not m: g='not_canonical_in_manifest'
    else:
        h=sha(os.path.join(R,f))==m['sha256']
        g='hash_verified' if h else 'raw_reexport'
        if rid>='20260923': g_new=True
    d=test(os.path.join(R,f));d['rid']=rid;d['group']=g;d['new']=rid>='20260923';res['raw/'+f]=d
for f in sorted(os.listdir(O)):
    if f.endswith('.csv'):
        d=test(os.path.join(O,f));d['rid']=f;d['group']='originals';d['new']=False;res['orig/'+f]=d
grp={}
for k,d in res.items():
    gs=[d['group']]+(['new'] if d['new'] else [])
    for g in gs:
        s=grp.setdefault(g,dict(n=0,unchecked=0,R1=0,R2=0,untested_files=0))
        s['n']+=1
        if d['status']!='ok': s['unchecked']+=1;continue
        s['R1']+=d['r1'];s['R2']+=d['r2'];s['untested_files']+=bool(d['untested'])
r2={k:dict(rid=d['rid'],group=d['group'],new=d['new'],cols=d['r2cols']) for k,d in res.items() if d.get('r2')}
unt={k:d['untested'] for k,d in res.items() if d.get('untested')}
r1={k:d['rid'] for k,d in res.items() if d.get('r1')}
flag_clean={k:v for k,v in r2.items() if v['group'] in('hash_verified','originals') or v['new']}
out=dict(groups=grp,r2_flagged=r2,untested=unt,r1_flagged=r1,r2_in_clean_groups=flag_clean)
json.dump(out,open('analyses/M324_audit/results.json','w'),indent=1)
brief=dict(groups=grp,r2_flagged={v['rid']+'|'+v['group']:{c.strip():round(x,4) for c,x in v['cols'].items()} for v in r2.values()},n_untested_columns_files=len(unt),r2_in_hash_verified_new_orig=[v['rid'] for v in flag_clean.values()],r1_files=len(r1))
json.dump(brief,open('analyses/M324_audit/brief.json','w'))
print(json.dumps(brief)[:3000]);print(len(json.dumps(brief)))
