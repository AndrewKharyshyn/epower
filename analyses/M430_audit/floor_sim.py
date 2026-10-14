import numpy as np
from audit_m430 import *
# Illustrative: if the TRUE law were a pure exponential at the fitted coolant slope, what would outcome-selected survivors look like by gap bin?
# ie unknown for coolant -> bracket 4..25 (pack design) and 10..40; noise sd 0.35; integer-degree rounding; filter re>0.5
f=P['fits'][1]; x=np.array(f['gapH']); b=binidx(x); s=-0.2938
rng=np.random.default_rng(1)
for lo,hi in [(4,25),(10,40)]:
    med={k:[] for k in range(6)}; surv={k:[] for k in range(6)}
    for r in range(300):
        ie=rng.integers(lo,hi+1,len(x)); re=np.round(ie*np.exp(s*x+0.35*rng.standard_normal(len(x))))
        keep=re>0.5
        for k in range(6):
            m=(b==k)
            surv[k].append(keep[m].mean()); 
            if (keep&m).sum(): med[k].append(np.median(re[keep&m]/ie[keep&m]))
    print('ie',lo,hi,'survivor share / median retained among survivors by bin (obs coolant: .852 .443 .242 .137 .066 .056):')
    print('  ',[ (round(float(np.mean(surv[k])),2), round(float(np.mean(med[k])),3)) for k in range(6)])
