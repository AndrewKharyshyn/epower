import pickle, json, numpy as np, pandas as pd, glob
P = r'C:\Users\ANDRII~1\AppData\Local\Temp\claude\C--Users-AndriiKharyshyn-Downloads-X-Trail-Investigation-Repo-xtrail-repo\f2ab55fa-e6d5-45d0-976d-c55d9b3eda14\scratchpad\tables578.pkl'
d = pickle.load(open(P,'rb')); S,T = d['tables'][:2]; files=d['files']; later=set(files[489:])
for nm,t in (('START',S),('STOP',T)):
    l = t[t.file.isin(later)]
    cc = l.dropna(subset=['soc','speed','tpack','demand','durationS'])
    print(nm,'later raw',len(l),int(l.y.sum()),'cc',len(cc),int(cc.y.sum()))
    for c in ['soc','speed','tpack','demand','durationS']: print('  NaN',c,int(l[c].isna().sum()))
    day=cc.groupby('day').agg(n=('y','size'),ev=('y','sum'))
    print('  top day share n',day.n.max()/day.n.sum(),'ev',day.ev.max()/day.ev.sum())
    # tpack range in later by day
    print(cc.groupby('day').tpack.agg(['min','median','max']).round(1).T.to_string())
