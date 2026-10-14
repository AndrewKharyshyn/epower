import numpy as np
from audit_m430 import *
for i,name in enumerate(P['order']):
    f=P['fits'][i]; x=np.array(f['gapH']); y=np.array(f['y']); arr=np.array(f['arrivalDay']); dep=np.array(f['departureDay'])
    ud=np.array(sorted(set(arr))); e=np.linspace(0,len(ud),11).astype(int)
    fold={d:j for j in range(10) for d in ud[e[j]:e[j+1]]}
    fa=np.array([fold[d] for d in arr])
    order=np.argsort(arr,kind='stable'); 
    # departure day lies in a different fold's arrival day set?
    cross=0; depin=0
    for k in range(len(x)):
        if dep[k] in fold:
            depin+=1
            if fold[dep[k]]!=fa[k]: cross+=1
    # monotone chronological ordering check & consecutive-pair fold changes
    mono=np.all(np.diff(np.array([np.datetime64(a) for a in arr]).astype('datetime64[D]').astype(int))>=0)
    ch=int(np.sum(np.diff(fa[order])!=0))
    span=np.array([(np.datetime64(a)-np.datetime64(d)).astype(int) for a,d in zip(arr,dep)])
    print(name,'chronological',mono,'fold changes along sequence',ch,'| pairs whose departure day is an arrival day of other fold:',cross,'of',depin,'| gap span days>0:',int((span>0).sum()),'max span',span.max(),'| days/fold',[int(e[j+1]-e[j]) for j in range(10)],'| pairs/fold',[int((fa==j).sum()) for j in range(10)])
    # pairs/fold min date
    print('   fold date ranges', [(str(ud[e[j]]),str(ud[e[j+1]-1])) for j in (0,4,9)])
    # calendar-time coverage: seasonal confounding—mean gap by fold
    print('   mean y by fold',[round(float(y[fa==j].mean()),2) for j in range(10)])
    print('   duplicate (x,y,arr) rows',len(x)-len(set(zip(x.round(6),y.round(6),arr))))
