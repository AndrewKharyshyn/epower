import sys,pickle
sys.path.insert(0,'analyses/M442_audit')
import ext, numpy as np, pandas as pd
res=pickle.load(open('analyses/M442_audit/res.pkl','rb')); q2=pickle.load(open('analyses/M442_audit/q2.pkl','rb'))
CI={c:i for i,c in enumerate(ext.CELLS)}
def insup(f):
    return all((q2[f][k][1]<=3.0) for k in q2[f] if q2[f][k][0]>=2)
files=[f for f,v in res.items() if v['known']]   # C7
sup=[f for f in files if insup(f)]
oos=[f for f in res if not insup(f)]
oos_known=[f for f in files if not insup(f)]
print('all',len(res),'known',len(files),'sup',len(sup),'oos(all)',len(oos),'oos(known)',len(oos_known))
for f in oos: print(f,res[f]['known'],{k:(q2[f][k][0],None if np.isnan(q2[f][k][1]) else round(q2[f][k][1],2)) for k in q2[f]},'nat n',res[f]['nat'][0][2]+res[f]['nat'][0][3])
# old rule
oldoos=[f for f in files if not all(np.isfinite(res[f]['q90'][k]) and res[f]['q90'][k]<=3 for k in res[f]['q90'])]
print('old known oos',len(oldoos),'diff',set(oldoos)^set(oos_known))
for f in set(oldoos)^set(oos_known): print(f,res[f]['q90'],q2[f],res[f]['nat'][0])
def perday(fs,cells,days,var='nat'):
    di={d:i for i,d in enumerate(days)}
    out={c:np.zeros((len(days),5)) for c in cells}
    for f in fs:
        v=res[f]
        if v['date'] not in di: continue
        for c in cells: out[c][di[v['date']]]+=v[var][CI[c]]
    return out
pct=lambda x:np.percentile(x,[2.5,97.5])
def contrast(A,B,days,fs):
    p=perday(fs,[A,B],days); D=len(days); a,b=p[A],p[B]
    pt=100*b[:,0].sum()/b[:,1].sum()-100*a[:,0].sum()/a[:,1].sum()
    idx=np.random.default_rng(42).integers(0,D,(4000,D))
    d=100*b[idx,0].sum(1)/b[idx,1].sum(1)-100*a[idx,0].sum(1)/a[idx,1].sum(1)
    return round(pt,3),pct(d).round(3),D
for nm,fs in [('sup',sup)]:
    days=sorted({res[f]['date'] for f in fs if res[f]['nat'][0][2]+res[f]['nat'][0][3]>0})
    even=[d for d in days if int(d[-2:])%2==0]
    print(nm,'days',len(days),'even',len(even))
    print('T3-T4',contrast('T3','T4',even,fs)); print('S4-S5',contrast('S4','S5',even,fs))
    # also days defined by any-data (any drive in sup at all)
    days2=sorted({res[f]['date'] for f in fs}); ev2=[d for d in days2 if int(d[-2:])%2==0]
    print('alt any-drive days even',len(ev2),contrast('T3','T4',ev2,fs),contrast('S4','S5',ev2,fs))
# levels sanity
for c in ['total','T3','T4','T5']:
    a=sum(res[f]['nat'][CI[c]] for f in sup); print(c,a[2],a[3],100*a[0]/a[1])
# G2
ev=[f for f in sup if int(res[f]['date'][-2:])%2==0]
fd={res[f]['date'] for f in ev if res[f]['fast']}; sd={res[f]['date'] for f in ev if not res[f]['fast']}
both=sorted(fd&sd); print('even days with both',len(both),both)
def st(fs,c):
    a=np.array([res[f]['nat'][CI[c]] for f in fs]).reshape(-1,5); n=a[:,2].sum(); dr=(a[:,2]>0).sum(); dy=len({res[f]['date'] for f,x in zip(fs,a) if x[2]>0})
    return n,dr,dy,bool(n>=200 and dr>=10 and dy>=5)
for scope,filt in [('all even',lambda f:True),('paired days',lambda f:res[f]['date'] in both)]:
    k=[]
    for c in ext.CELLS:
        F=[f for f in ev if res[f]['fast'] and filt(f)]; S=[f for f in ev if not res[f]['fast'] and filt(f)]
        a,b=st(F,c),st(S,c)
        if a[3] and b[3]: k.append(c)
    print(scope,'both-supported cells',len(k),k)
# also with n counting n strict as per-phase mean (col 2)
print('---extra')
d_any=set(res[f]['date'] for f in sup); d_data=set(res[f]['date'] for f in sup if res[f]['nat'][0][2]+res[f]['nat'][0][3]>0)
print(len(d_any),len(d_data),sorted(d_any-d_data))
for d in sorted(d_any-d_data): print(d,[(f,res[f]['nat'][0][:4].tolist(),q2[f]) for f in sup if res[f]['date']==d])
allk=set(res[f]['date'] for f in files); print('known days',len(allk),'even',len([d for d in allk if int(d[-2:])%2==0]))
old17=[f for f in files if not all((np.isfinite(res[f]['q90'][k]) and res[f]['q90'][k]<=3) or (np.isnan(res[f]['q90'][k]) and False) for k in res[f]['q90'])]
# earlier 17 rule: finite >3 only plus nan with data? compute finite>3
o=[f for f in files if any(np.isfinite(res[f]['q90'][k]) and res[f]['q90'][k]>3 for k in res[f]['q90'])]
print('finite>3 old',len(o),set(o)-set(oos_known),set(oos_known)-set(o))
print('---g2data')
evd=[f for f in ev if res[f]['nat'][0][2]+res[f]['nat'][0][3]>0]
fd={res[f]['date'] for f in evd if res[f]['fast']}; sd={res[f]['date'] for f in evd if not res[f]['fast']}
print('even days both with data',sorted(fd&sd))
print('fast drives in-sup even',sum(res[f]['fast'] for f in ev),'slow',sum(not res[f]['fast'] for f in ev))
