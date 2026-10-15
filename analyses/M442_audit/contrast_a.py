from lib import *
alld=sorted({res[f]['date'] for f in sup if res[f]['nat'][0][2]+res[f]['nat'][0][3]>0})
def contrast(A,B,days,fs=sup,label=''):
    cells=[A,B]
    p=perday(fs,'nat',cells,days); D=len(days)
    a,b=p[A],p[B]
    pt=100*b[:,0].sum()/b[:,1].sum()-100*a[:,0].sum()/a[:,1].sum()
    rng=np.random.default_rng(42); idx=rng.integers(0,D,(4000,D))
    ra=100*a[idx,0].sum(1)/a[idx,1].sum(1); rb=100*b[idx,0].sum(1)/b[idx,1].sum(1)
    d=rb-ra
    return pt,pct(d), D, np.isnan(d).sum()
even=[d for d in alld if int(d[-2:])%2==0]; odd=[d for d in alld if int(d[-2:])%2==1]
print(len(alld),len(even),len(odd))
for A,B in [('T3','T4'),('S4','S5')]:
    for nm,ds in [('even',even),('odd',odd),('all',alld)]:
        pt,ci,D,nn=contrast(A,B,ds); print(A,B,nm,D,round(pt,3),ci.round(3),nn)
# variant: even days with data in either cell
for A,B in [('T3','T4'),('S4','S5')]:
    p=perday(sup,'nat',[A,B],alld)
    ds=[d for d,x,y in zip(alld,p[A],p[B]) if int(d[-2:])%2==0 and (x[2]+x[3]+y[2]+y[3])>0]
    pt,ci,D,nn=contrast(A,B,ds); print('variant either-cell even',A,B,D,round(pt,3),ci.round(3))
