import csv,re,os,json,sys,collections
import pandas as pd
sys.path.insert(0,'.')
R='raw'
key=lambda s:''.join(re.findall(r'\d',s))[:14]
dm=pd.read_csv('drive_master.csv',usecols=['file','date'])
dm['k']=dm.file.map(key)
rawmap={}
for f in os.listdir(R):
    if f.startswith('e4ORCE') or not f.endswith('.csv'): continue
    rawmap[key(f)]=f
C='Використане паливо (L)';Rt='Витрати палива (L/h)'
N1='Витрата палива в автомобілі (g/sec)';N2='Витрата палива у двигуні (g/sec)'
pat=re.compile(r'(?i)паливо|палив|fuel|л/год|л/100|l/h|l/100')
res={};other=collections.Counter();missing=[]
for k in dm.k:
    f=rawmap.get(k)
    if not f: missing.append(k);continue
    d=pd.read_csv(os.path.join(R,f),low_memory=False,encoding='utf-8')
    cols=[c.strip() for c in d.columns]; d.columns=cols
    pc=C in cols;pr=Rt in cols
    uc=False;ur=False;ns=0
    if pc:
        v=pd.to_numeric(d[C],errors='coerce').dropna();uc=len(v)>=2 and v.max()>v.min()
    if pr:
        v=pd.to_numeric(d[Rt],errors='coerce').dropna();ns=len(v);ur=bool((v>0).any())
    nat=(N1 in cols) or (N2 in cols)
    for c in cols:
        if pat.search(c) and c not in (C,Rt,N1,N2) and not c.startswith('Вартість палива'): other[c]+=1
    res[k]=dict(pc=pc,pr=pr,uc=uc,ur=ur,ns=ns,nat=nat)
dm=dm[dm.k.isin(res)].copy()
for x in ['pc','pr','uc','ur','ns','nat']: dm[x]=dm.k.map(lambda k:res[k][x])
dm['both_p']=dm.pc&dm.pr;dm['both_u']=dm.uc&dm.ur
dm['month']=dm.date.astype(str).str[:7]
out=dict(n_files=len(dm),missing_raw=missing,present_counter=int(dm.pc.sum()),present_rate=int(dm.pr.sum()),
 present_both=int(dm.both_p.sum()),usable_counter=int(dm.uc.sum()),usable_rate=int(dm.ur.sum()),usable_both=int(dm.both_u.sum()),
 usable_rate_ge10=int((dm.ur&(dm.ns>=10)).sum()),
 monthly={m:dict(files=len(g),both_present=int(g.both_p.sum()),both_usable=int(g.both_u.sum())) for m,g in dm.groupby('month')},
 earliest_either=str(dm[dm.pc|dm.pr].date.min()),native_files=int(dm.nat.sum()),other_fuel_headers=dict(other))
fr=pd.read_csv('fuel_recon_master.csv');fr['k']=fr.file.map(key)
u=dict(zip(dm.k,dm.both_u));ns=dict(zip(dm.k,dm.ns))
nu=fr[~fr.k.map(lambda k:u.get(k,False))]
out['recon']=dict(rows=len(fr),cs_true=int((fr.charge_sustaining==True).sum()),date_min=str(fr.date.min()),date_max=str(fr.date.max()),
 methods=sorted(fr.method.astype(str).unique()),not_usable_both=len(nu),not_usable_ge10=int(sum(ns.get(k,0)>=10 for k in nu.k)),
 not_in_dm=int((~fr.k.isin(dm.k)).sum()))
import model_constants as mc
kwh=mc.RHO_G_PER_L[0]*mc.LHV_MJ_PER_KG[0]/1000/3.6
out['kwh_per_L']=round(kwh,4);out['ratio_to_8.9']=round(kwh/8.9,4)
json.dump(out,open('analyses/M334_audit/results.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
print(json.dumps(out,ensure_ascii=False))
