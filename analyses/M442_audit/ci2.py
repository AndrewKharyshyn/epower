from lib import *
cells=['total','T3','T4','T5']
days0=sorted({res[f]['date'] for f in sup})
pd0=perday(sup,'nat',cells,days0)
days=[d for d,x in zip(days0,pd0['total']) if x[2]+x[3]>0]
print(len(days))
pdd=perday(sup,'nat',cells,days); D=len(days)
for c in cells:
    r,=boot([pdd[c]],D); print(c,pct(r).round(3))
# variant: statistic with draws where zero-den dropped etc. nothing. Variant: float percentile method
