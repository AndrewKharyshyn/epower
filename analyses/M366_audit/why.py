import sys; sys.path.insert(0,'C:/Users/AndriiKharyshyn/Downloads/X-Trail Investigation/Repo/xtrail-repo/audit/m366b')
from lib import *
a=json.load(open('summary_arrays.json',encoding='utf-8'))['fuelAnalytics']['trips']
ni=index(NEW); ai=index(ARC); rc="Витрати палива (L/h)"
oi={k:ai.get(k,v) for k,v in ni.items()}
for b,idx in (('NEW',ni),('OLD',oi)):
    r={key(T['id']):trip(idx[key(T['id'])],rc) for T in a}
    D={}
    for T in a:
        c,v=r[key(T['id'])]; d=D.setdefault(T['day'],[0,0]); d[0]+=v-c; d[1]+=c
    N=np.array([x[0] for x in D.values()]);V=np.array([x[1] for x in D.values()])
    e=N.sum()/V.sum(); res=N-e*V
    print(b,'est',e,'SD of day residual (L)',res.std(ddof=1),'SE approx',np.sqrt((res**2).sum())/V.sum())
    f=[T for T in a if not T['hashPass']]; g=[T for T in a if T['gap']]
    tv=sum(x[1] for x in r.values())
    print(' Vcnt share fail',sum(r[key(T['id'])][0] for T in f)/tv,'gapped',sum(r[key(T['id'])][0] for T in g)/tv,'gapped&fail',sum(1 for T in g if not T['hashPass']))
    print(' frac of V_cnt in fail trips residual', sum(r[key(T['id'])][1]-r[key(T['id'])][0] for T in f))
