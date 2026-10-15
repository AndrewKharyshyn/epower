from lib import *
def massrange(fs,var,cell):
    a=np.array([res[f][var][CI[cell]] for f in fs]).sum(0)
    out=[]
    for m in (1920.,1860.):
        ke=a[4]*m/1890.+(a[1]-a[4]); out.append(100*a[0]/ke)
    return [round(x,2) for x in out]
for c in ['total','T3','T4','T5']: print(c,massrange(sup,'nat',c))
