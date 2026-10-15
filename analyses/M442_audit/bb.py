from lib import *
fast=[f for f in sup if res[f]['fast']]
print('fast in support',len(fast), 'fast all', sum(res[f]['fast'] for f in files))
def eff(fs,var,c):
    a=np.array([res[f][var][CI[c]] for f in fs]).sum(0); return 100*a[0]/a[1], a[2]
def b(fs,c):
    n,_=eff(fs,'nat',c); return max(abs(n-eff(fs,v,c)[0]) for v in ('d2','d3')), [round(n-eff(fs,v,c)[0],4) for v in ('d2','d3')]
for c,lab in [('T4','temp 20-30'),('S5','soc 66-69'),('T5','temp 30-40'),('T3','temp 10-20'),('S4','soc 63-66'),('total','total')]:
    print(lab,b(fast,c),eff(fast,'nat',c))
# support in fast drives
for c in ['T3','T4','T5','S4','S5','T6']:
    a=np.array([res[f]['nat'][CI[c]] for f in fast]); print(c,a[:,2].sum(),(a[:,2]>0).sum(),len({res[f]['date'] for f,x in zip(fast,a) if x[2]>0}))
