import sys,json; sys.path.insert(0,'analyses/M441_audit')
import numpy as np, pandas as pd, aggregate as ag
b=json.load(open('analyses/M441_audit_brief.json',encoding='utf-8'))['claims']
c=json.load(open('analyses/M441_audit/cells_out.json',encoding='utf-8'))
mx=dict(count=0,ke=0,ch=0,eff=0,keRel=0,chRel=0)
def cmp(mine,cl,soc=False):
    n_m=mine['nStrict']
    mx['count']=max(mx['count'],abs(n_m-cl['n']))
    if 'nPlateau' in cl: mx['count']=max(mx['count'],abs(mine['nPlateau']-cl['nPlateau']))
    for k in ('drives','days'):
        if k in cl: mx['count']=max(mx['count'],abs(mine[k]-cl[k]))
    mx['ke']=max(mx['ke'],abs(mine['ke']-cl['keKwh'])); mx['ch']=max(mx['ch'],abs(mine['ch']-cl['chargeKwh'])); mx['eff']=max(mx['eff'],abs(mine['eff']-cl['eff']))
    mx['keRel']=max(mx['keRel'],abs(mine['ke']-cl['keKwh'])/cl['keKwh']); mx['chRel']=max(mx['chRel'],abs(mine['ch']-cl['chargeKwh'])/cl['chargeKwh'])
for l,v in b['temperatureAllSoc'].items(): cmp(c['T'+l],v)
for l,v in b['speedInstantaneousNoSoc'].items(): cmp(c['S'+l],v)
for l,v in b['classesNoSoc'].items(): cmp(c['C'+l],v)
for l,v in b['socBandsOverallTemperaturePooled'].items(): cmp(c['B'+l],v)
print(mx)
D=ag.load('analyses/M441_audit/cache_C'); T=ag.per_drive_table(D).set_index('file')
d1=d2=0
for p in b['perDrive']:
    r=T.loc[p['file']]; d1=max(d1,abs(r.chargeKwhKept-p['chargeKwhKept'])); d2=max(d2,abs(r.dv2Kept-p['dv2Kept']))
print('perDrive max |charge diff| kWh',d1,'max |dv2| diff',d2)
X,B2,BC,TT,tr=ag.kept_all(D)
print('totals ke',X.ke.sum()-b['totals']['keKwh'],'ch',X.charge.sum()-b['totals']['chargeKwh'])
