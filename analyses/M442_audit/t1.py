import sys,time
sys.path.insert(0,'analyses/M442_audit')
import ext, pandas as pd, numpy as np
dm=pd.read_csv('drive_master.csv')
L=ext.drc.make_frame_loader(raw_dir='raw_only')
tot={+1:np.zeros(2),-1:np.zeros(2)}
t=time.time()
for i in range(250,300):
    r=dm.iloc[i]
    for s in (+1,-1):
        ext.SIGN=s
        v=ext.drive_variants(r.file,r.drive_type,False,L)
        tot[s]+=v['nat'][0][:2]
print(time.time()-t, {s:(a[0]/a[1]*100,a[1]) for s,a in tot.items()})
