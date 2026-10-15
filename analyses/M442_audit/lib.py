import sys,pickle
sys.path.insert(0,'analyses/M442_audit')
import ext, numpy as np, pandas as pd
res=pickle.load(open(__import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)),'res.pkl'),'rb'))
CI={c:i for i,c in enumerate(ext.CELLS)}
def insup(v):
    q=v['q90']; return all(np.isfinite(q[k]) and q[k]<=3.0 for k in q)
files=[f for f,v in res.items() if v['known']]
sup=[f for f in files if insup(res[f])]
def dom(d): return int(d[-2:])
def perday(fs,var,cells,days):
    """-> dict cell -> array (D,2) [chg,ke] ; also n"""
    di={d:i for i,d in enumerate(days)}
    out={c:np.zeros((len(days),5)) for c in cells}
    for f in fs:
        v=res[f]
        if v['date'] not in di or var not in v: continue
        for c in cells: out[c][di[v['date']]]+=v[var][CI[c]]
    return out
def boot(numden_list,D,seed=42,B=4000):
    """numden_list: list of (arr(D,2)) ; returns ratio matrix (B,len)"""
    rng=np.random.default_rng(seed); idx=rng.integers(0,D,(B,D))
    out=[]
    for a in numden_list:
        c=a[idx,0].sum(1); k=a[idx,1].sum(1)
        out.append(100*c/k)
    return out
def pct(x): return np.percentile(x,[2.5,97.5])
