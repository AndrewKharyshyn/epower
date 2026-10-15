from lib import *
def eff(fs,A,var='nat'):
    a=np.array([res[f][var][CI[A]] for f in fs]).sum(0); return 100*a[0]/a[1]
par=lambda fs,p:[f for f in fs if int(res[f]['date'][-2:])%2==p]
pops={'sup':sup,'known':files,'allfiles':list(res),'fast':[f for f in sup if res[f]['fast']],'slow':[f for f in sup if not res[f]['fast']]}
for nm,fs in pops.items():
    print(nm,[ (round(eff(par(fs,p) if p<2 else fs,'T4')-eff(par(fs,p) if p<2 else fs,'T3'),3)) for p in (0,1,2)],
      [ (round(eff(par(fs,p) if p<2 else fs,'S5')-eff(par(fs,p) if p<2 else fs,'S4'),3)) for p in (0,1,2)])
