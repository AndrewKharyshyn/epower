from lib import *
fs=files
def dayset(fs,filt=None):
    return sorted({res[f]['date'] for f in fs if res[f]['nat'][0][2]+res[f]['nat'][0][3]>0})
alld=dayset(fs)
even=[d for d in alld if int(d[-2:])%2==0]
def contrast(A,B,days,fs):
    p=perday(fs,'nat',[A,B],days); D=len(days); a,b=p[A],p[B]
    pt=100*b[:,0].sum()/b[:,1].sum()-100*a[:,0].sum()/a[:,1].sum()
    rng=np.random.default_rng(42); idx=rng.integers(0,D,(4000,D))
    d=100*b[idx,0].sum(1)/b[idx,1].sum(1)-100*a[idx,0].sum(1)/a[idx,1].sum(1)
    return round(pt,3),pct(d).round(3),D
print(len(alld),len(even))
print(contrast('T3','T4',even,fs)); print(contrast('S4','S5',even,fs))
# day-set variants: all calendar even days in master
dmd=pd.read_csv('../../drive_master.csv'); ev2=sorted({d for d in dmd.date if int(d[-2:])%2==0}); print(len(ev2))
print(contrast('T3','T4',ev2,fs)); print(contrast('S4','S5',ev2,fs))
