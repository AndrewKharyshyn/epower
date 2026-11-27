import json,re,os,math,glob
import numpy as np, pandas as pd
R="raw"
cfg=json.load(open("summary_config.json",encoding="utf-8"))
amb=cfg["ambientByDrive"]
dm=pd.read_csv("drive_master.csv",encoding="utf-8",usecols=["file","date"])
print("dm dup",dm.file.duplicated().sum(),len(dm))
date=dict(zip(dm.file,dm.date))
raw={}
for f in os.listdir(R):
    if f.startswith("e4ORCE"): continue
    d=re.sub(r"\D","",f)
    if len(d)==14: raw.setdefault(d[:8]+"_"+d[8:],[]).append(f)
anom=[]
col="[BMS] HV Battery Temperature Sensor 1 (℃)"
rows=[]
for k,v in amb.items():
    if isinstance(v,(int,float)): anom.append(("plain",k)); a=float(v)
    else:
        if len(v)!=2: anom.append(("len%d"%len(v),k))
        if len(v)==0: continue
        a=(v[0]+v[-1])/2
    key=re.sub(r"\D","",k); key=key[:8]+"_"+key[8:]
    fs=raw.get(key)
    if not fs: anom.append(("noraw",k)); continue
    if len(fs)>1: anom.append(("dupraw",k))
    if k not in date: anom.append(("nomaster",k)); continue
    df=pd.read_csv(os.path.join(R,fs[0]),encoding="utf-8",usecols=lambda c:c==col)
    if col not in df: anom.append(("nocol",k)); continue
    s=pd.to_numeric(df[col],errors="coerce"); s=s[(s>=-40)&(s<=80)].dropna()
    if len(s)==0: anom.append(("novalid",k)); continue
    rows.append((a,round(s.max()),round(s.min()),date[k]))
d=pd.DataFrame(rows,columns="a pk mn dt".split())
d["b"]=np.floor(d.a/5).astype(int)*5
out=[]
for b,g in d.groupby("b"):
    p=g.pk.values
    out.append(dict(bin_lo=int(b),n=len(g),nDays=g.dt.nunique(),lo=int(math.floor(g.mn.min())),hi=int(math.floor(g.pk.max())),medPeak=int(round(float(np.median(p)))),p25=round(float(np.percentile(p,25)),1),p75=round(float(np.percentile(p,75)),1)))
print(json.dumps(dict(rows=out,total=len(d),nAmb=len(amb),anom=anom[:20],nanom=len(anom))))
json.dump(dict(rows=out,total=len(d),anom=anom),open("analyses/M780_audit/out.json","w",encoding="utf-8"))
