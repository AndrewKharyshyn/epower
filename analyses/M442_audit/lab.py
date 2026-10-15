from lib import *
def tot(fs,c,m):
    a=np.array([res[f]['nat'][CI[c]] for f in fs]).sum(0); return 100*a[0]/(a[4]*m/1890.+a[1]-a[4])
par=lambda fs,p:[f for f in fs if int(res[f]['date'][-2:])%2==p]
for A,B,bs in [('T3','T4',1.6766170268772242+0.7011723490320989),('S4','S5',0.5545589466649474+0.3140269833029521)]:
    for nm,fs in [('even',par(files,0)),('odd',par(files,1)),('all',files)]:
        print(A,B,nm,[round(tot(fs,B,m)-tot(fs,A,m),3) for m in (1860.,1890.,1920.)])
    print('bracketSum',round(bs,3))
# G2 vacuity: even days with both fast and slow supported (per cell) among in-support drives
even=[f for f in sup if int(res[f]['date'][-2:])%2==0]
days=sorted({res[f]['date'] for f in even})
print('even days',len(days))
both=[d for d in days if any(res[f]['fast'] and res[f]['date']==d for f in even) and any((not res[f]['fast']) and res[f]['date']==d for f in even)]
print('even days with both fast and slow',len(both),both)
