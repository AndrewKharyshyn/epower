import sys,pickle,time
sys.path.insert(0,'analyses/M442_audit')
import ext, numpy as np, pandas as pd
res=pickle.load(open('analyses/M442_audit/res.pkl','rb'))
L=ext.drc.make_frame_loader(raw_dir='raw_only')
out={}
t=time.time()
for f in res:
    nat,_,_=ext.load_native(L(f))
    o={}
    for k in ('speed','I','V'):
        d=np.diff(nat[k][0]); d=d[(d>0)&(d<=5)]
        o[k]=(len(d), float(np.quantile(d,0.9)) if len(d)>=2 else np.nan)
    out[f]=o
print(time.time()-t)
pickle.dump(out,open('analyses/M442_audit/q2.pkl','wb'))
