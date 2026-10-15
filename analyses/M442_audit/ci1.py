from lib import *
days=sorted({res[f]['date'] for f in sup})
print(len(days))
cells=['total','T3','T4','T5']
pd_=perday(sup,'nat',cells,days)
D=len(days)
for c in cells:
    a=pd_[c]; pt=100*a[:,0].sum()/a[:,1].sum()
    r,=boot([a],D); print(c,round(pt,3),pct(r).round(3))
    # variant: only days with cell data
    m=a[:,4]*0+ (a[:,2]+a[:,3]>0)
    dd=a[m>0]; r2,=boot([dd],len(dd)); print('  celldays',len(dd),pct(r2).round(3))
