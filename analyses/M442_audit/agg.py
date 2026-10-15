import sys,pickle
sys.path.insert(0,'analyses/M442_audit')
import ext, numpy as np, pandas as pd
res=pickle.load(open('analyses/M442_audit/res.pkl','rb'))
CI={c:i for i,c in enumerate(ext.CELLS)}
def insup(v):
    q=v['q90']; return all(np.isfinite(q[k]) and q[k]<=3.0 for k in q)
files=[f for f,v in res.items() if v['known']]
sup=[f for f in files if insup(res[f])]
oos=[f for f in files if not insup(res[f])]
print('known',len(files),'sup',len(sup),'oos',len(oos))
ke_all=sum(res[f]['nat'][0][1] for f in files); ke_oos=sum(res[f]['nat'][0][1] for f in oos)
print('oos KE share',ke_oos/ke_all)
def pool(fs,var,cell):
    a=np.array([res[f][var][CI[cell]] for f in fs]); return a
def summ(fs,var,cell):
    a=pool(fs,var,cell); s=a.sum(0)
    nd=(a[:,2]+a[:,3]>0).sum(); days=len({res[f]['date'] for f,x in zip(fs,a) if x[2]+x[3]>0})
    return dict(n=s[2],npl=s[3],ke=s[1],chg=s[0],eff=100*s[0]/s[1],drives=nd,days=days)
print('total',summ(sup,'nat','total'))
for i,(lo,hi,l) in enumerate(ext.TEMP_BINS): print(l,summ(sup,'nat','T%d'%i))
# also all-known (no support exclusion)
print('total all known',summ(files,'nat','total'))
