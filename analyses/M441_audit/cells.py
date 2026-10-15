import sys,json; sys.path.insert(0,'analyses/M441_audit')
import numpy as np, pandas as pd
import aggregate as ag
b=json.load(open('analyses/M441_audit_brief.json',encoding='utf-8'))['claims']
D=ag.load('analyses/M441_audit/cache_C')
X,B2,BC,TT,tr=ag.kept_all(D)
X['strict']=X.kind==0
def cell(mask, bins=None, label=''):
    """mask over X rows (whole-interval view) or bins index for slice view"""
    if bins is None:
        s=X[mask]; ke=s.ke.sum(); ch=s.charge.sum()
        n=len(s); npl=int((s.kind==1).sum()); nstr=int((s.kind==0).sum()); dr=s.file.nunique(); dy=s.date.nunique()
    else:
        mk=TT[:,bins]; s=X[mk]
        mass=X.mass.to_numpy()
        ke=float((B2[:,bins]*ag.K*mass).sum()); ch=float(BC[:,bins].sum())
        n=len(s); npl=int((s.kind==1).sum()); nstr=int((s.kind==0).sum()); dr=s.file.nunique(); dy=s.date.nunique()
    return dict(n=n,nStrict=nstr,nPlateau=npl,drives=dr,days=dy,ke=round(ke,5),ch=round(ch,5),eff=round(100*ch/ke,2) if ke>0 else None)
out={}
print('TEMP')
tb=[(0,10,'0–10°C'),(10,20,'10–20°C'),(20,30,'20–30°C'),(30,40,'30–40°C'),(40,50,'40–50°C')]
for lo,hi,l in tb:
    m=(X.temp>=lo)&(X.temp<hi)
    r=cell(m); out['T'+l]=r; c=b['temperatureAllSoc'][l]
    print(l,r,'| claim',c)
print('other temp bins n',[(lo,hi,int(((X.temp>=lo)&(X.temp<hi)).sum())) for lo,hi in [(-99,0),(50,99)]])
print('SPEED')
for l,j in [('0-10',0),('20-30',2),('60-70',6)]:
    r=cell(None,bins=j); out['S'+l]=r; print(l,r,'| claim',b['speedInstantaneousNoSoc'][l])
print('CLASSES')
cls={'A start<10':X.v0<10,'B start>=10 end<10':(X.v0>=10)&(X.v1<10),'C end>=10':X.v1>=10}
for l,m in cls.items():
    r=cell(m); out['C'+l]=r; print(l,r,'| claim',b['classesNoSoc'][l])
print('SOC bands (valid temp only)')
hasT=X.temp.notna()
for l,(lo,hi) in {'band 50-55':(50,55),'band 66-69':(66,69),'band 72-100':(72,100.0001)}.items():
    m=hasT&(X.soc>=lo)&(X.soc<hi)
    r=cell(m); out['B'+l]=r; print(l,r,'| claim',b['socBandsOverallTemperaturePooled'][l])
json.dump(out,open('analyses/M441_audit/cells_out.json','w'),indent=1,default=float)
