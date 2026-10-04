import json,numpy as np
A=json.load(open('baseline_arrays.json'));B=json.load(open('../xtrail-f03-control/control_arrays.json'))
st={'n':0,'num':[],'other':[],'struct':0}
def isnum(v):return isinstance(v,(int,float)) and not isinstance(v,bool)
def walk(a,b,p):
    if isinstance(a,dict) and isinstance(b,dict):
        for k in a:
            if k=='generatedAt' or k=='_artifactStamps': continue
            if k in b: walk(a[k],b[k],p+[k])
            else: st['struct']+=1
        st['struct']+=sum(1 for k in b if k not in a and k not in('generatedAt','_artifactStamps'))
    elif isinstance(a,list) and isinstance(b,list):
        if len(a)!=len(b): st['struct']+=1
        for i,(x,y) in enumerate(zip(a,b)): walk(x,y,p+[i])
    else:
        st['n']+=1
        if isnum(a) and isnum(b):
            if a!=b: st['num'].append(abs(b-a)/max(abs(a),1e-9))
        elif a!=b: st['other'].append(('.'.join(map(str,p)),type(a).__name__,type(b).__name__))
walk(A,B,[])
r=np.array(st['num']);print('leaves',st['n'],'struct',st['struct'],'numdiff',len(r),'median%',np.median(r)*100,'p90%',np.percentile(r,90)*100)
for o in st['other']:print(o)
# claim4
EK=['est','median','bootMedian','value','slope']
res=[]
def w4(a,b,p):
    if isinstance(a,dict) and isinstance(b,dict):
        for ek in EK:
            if ek in a and ek in b and isnum(a[ek]) and isnum(b[ek]):
                ca=a.get('ci95');cb=b.get('ci95')
                if isinstance(ca,list) and len(ca)==2 and isinstance(cb,list) and all(isnum(z) for z in ca):
                    if a[ek]!=b[ek]:
                        hw=(ca[1]-ca[0])/2
                        res.append(('.'.join(map(str,p))+'.'+ek,ca[0]<=b[ek]<=ca[1],abs(b[ek]-a[ek])/hw if hw else None))
        for k in a:
            if k in b and k not in('_artifactStamps',): w4(a[k],b[k],p+[k])
    elif isinstance(a,list) and isinstance(b,list):
        for i,(x,y) in enumerate(zip(a,b)): w4(x,y,p+[i])
w4(A,B,[])
print('claim4',len(res),'inside',sum(r[1] for r in res),'maxshift',max((r[2] or 0) for r in res))
for r in res:print(r)
