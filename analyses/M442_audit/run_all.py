import sys,time,pickle
sys.path.insert(0,'analyses/M442_audit')
import ext, pandas as pd, numpy as np
dm=pd.read_csv('drive_master.csv')
L=ext.drc.make_frame_loader(raw_dir='raw_only')
res={}
t=time.time()
for i,r in dm.iterrows():
    fast = (r.ev_rpm_dt_med_s<1.0) if pd.notna(r.ev_rpm_dt_med_s) else False
    v=ext.drive_variants(r.file,r.drive_type,fast,L)
    v['date']=r.date; v['fast']=fast; v['known']=pd.notna(r.ev_rpm_dt_med_s); v['dtype']=r.drive_type
    res[r.file]=v
print(time.time()-t)
pickle.dump(res,open('analyses/M442_audit/res.pkl','wb'))
