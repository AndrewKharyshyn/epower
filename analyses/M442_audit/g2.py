from lib import *
for nm,pool in [('sup',sup),('known',files)]:
    even=[f for f in pool if int(res[f]['date'][-2:])%2==0]
    days=sorted({res[f]['date'] for f in even})
    fd={res[f]['date'] for f in even if res[f]['fast']}; sd={res[f]['date'] for f in even if not res[f]['fast']}
    both=sorted(fd&sd); print(nm,'even days',len(days),'both',both)
    def sup_status(fs,c):
        a=np.array([res[f]['nat'][CI[c]] for f in fs]); n=a[:,2].sum(); dr=(a[:,2]>0).sum(); dy=len({res[f]['date'] for f,x in zip(fs,a) if x[2]>0})
        return n,dr,dy,(n>=200 and dr>=10 and dy>=5)
    for scope,filt in [('all even days',lambda f:True),('paired days only',lambda f:res[f]['date'] in both)]:
        k=0
        for c in ext.CELLS:
            F=[f for f in even if res[f]['fast'] and filt(f)]; S=[f for f in even if (not res[f]['fast']) and filt(f)]
            a=sup_status(F,c); b=sup_status(S,c)
            if a[3] and b[3]: k+=1; print('  ENTERS',scope,c,a,b)
            elif a[3] or b[3]:
                if scope=='all even days': print('  one-sided',c,a[:3],b[:3])
        print(scope,'cells supported in both groups:',k)
