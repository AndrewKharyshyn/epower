import json,numpy as np,pandas as pd
d=pd.read_csv('drive_master.csv'); d['dt']=d.date.astype(str).str[:10]
fin=lambda c:np.isfinite(pd.to_numeric(d[c],errors='coerce'))
sets={'R1':d.gross_discharge_kwh.notna()&d.file.notna(),
'R2':d.ens_outlier_v2.astype(str).str.strip().str.lower()=='false',
'R3':fin('cell_spread_loaded_p95_mv'),'R4':fin('vreg_R_pack_mohm')}
def ms(a,b):
    A=pd.Timestamp(a);B=pd.Timestamp(b)
    if (A.year,A.month)==(B.year,B.month): return f'{A:%B %Y}'
    return f'{A:%B} {A.year}-{B:%B} {B.year}' if A.year!=B.year else f'{A:%B}-{B:%B} {B.year}'
o={}
for k,m in sets.items():
    x=d[m].dt; o[k]={'n':int(m.sum()),'first':x.min(),'last':x.max(),'month_span':ms(x.min(),x.max())}
print(json.dumps(o)); print(d.ens_outlier_v2.astype(str).value_counts().to_dict())
