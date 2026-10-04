import sys; sys.path.insert(0,'C:/Users/AndriiKharyshyn/Downloads/X-Trail Investigation/Repo/xtrail-repo/audit/m366b')
from lib import *
a=json.load(open('summary_arrays.json',encoding='utf-8'))['fuelAnalytics']['trips']
print('reset',sum(T['reset'] for T in a),'gap',sum(T['gap'] for T in a),'hashFalse',sum(not T['hashPass'] for T in a))
ni=index(NEW); ai=index(ARC); print(len(ai))
man=json.load(open(ARC+'archived_reexports_sha256.json'))['files']
mk={m['canonical'][:8]+m['canonical'][9:15] for m in man}
print(len(mk), mk==set(ai), sum(1 for T in a if key(T['id']) in ai))
rc="Витрати палива (L/h)"
def res(idx,**kw):
    out={}
    for T in a:
        k=key(T['id']); out[k]=trip(idx[k],rc,**kw)
    return out
oldidx={k:ai.get(k,v) for k,v in ni.items()}
variants={'base':{}, 'cap10s':{'cap':10},'cap2s':{'cap':2},'trap':{'trap':True}}
R={}
for b,idx in (('NEW',ni),('OLD',oldidx)):
    for vn,kw in variants.items(): R[(b,vn)]=res(idx,**kw)
def stat(b,vn,sel):
    ts=[T for T in a if sel(T)]
    r=R[(b,vn)]
    num=[r[key(T['id'])][1]-r[key(T['id'])][0] for T in ts]; den=[r[key(T['id'])][0] for T in ts]
    e,lo,hi,k=boot([T['day'] for T in ts],num,den)
    return f"{e:.5f} [{lo:.5f},{hi:.5f}] n={len(ts)} d={k}"
sels={'all':lambda T:True,'pass':lambda T:T['hashPass'],'fail':lambda T:not T['hashPass'],'gapfree':lambda T:not T['gap'],'gapped':lambda T:T['gap'],'noreset':lambda T:not T['reset']}
for b in ('NEW','OLD'):
    for vn in variants:
        for s in sels:
            if vn!='base' and s in('pass','fail','noreset'): continue
            print(b,vn,s,stat(b,vn,sels[s]))
# decomposition
fk=[key(T['id']) for T in a if key(T['id']) in ai]
allk=[k for k in ai if k in ni]
for nm,ks in (('payload-trips re-exported',fk),('all archived files w/ fuel',allk)):
    ok=[];vi=[];vc=[];vi2=[];vc2=[]
    for k in ks:
        n=trip(ni[k],rc); o=trip(ai[k],rc)
        if n is None or o is None: continue
        vc.append(n[0]);vi.append(n[1]);vc2.append(o[0]);vi2.append(o[1])
    print(nm,len(vc),'Vint rel',sum(vi)/sum(vi2)-1,'Vcnt rel',sum(vc)/sum(vc2)-1)
