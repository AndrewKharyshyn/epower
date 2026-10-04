import json,re
A=json.load(open('published_arrays.json',encoding='utf-8')); B=json.load(open('summary_arrays.json',encoding='utf-8'))
EK=['est','median','bootMedian','value','slope']
isn=lambda x:isinstance(x,(int,float)) and not isinstance(x,bool)
chk=0;out=[];strs=[]
def walk(a,b,p):
    global chk
    if isinstance(a,dict) and isinstance(b,dict):
        ci=a.get('ci95')
        if isinstance(ci,list) and len(ci)==2 and all(isn(x) for x in ci):
            for k in EK:
                if k in a and k in b and isn(a[k]) and isn(b[k]) and a[k]!=b[k]:
                    chk+=1
                    if not(ci[0]<=b[k]<=ci[1]): out.append((p+'/'+k,a[k],b[k],ci))
        for k in a:
            if k in b: walk(a[k],b[k],p+'/'+k)
    elif isinstance(a,list) and isinstance(b,list):
        for i,(x,y) in enumerate(zip(a,b)): walk(x,y,f'{p}/{i}')
    elif isinstance(a,(str,bool)) and isinstance(b,(str,bool)) and a!=b: strs.append((p,a,b))
walk(A,B,'')
print(chk,len(out)); [print(o) for o in out]
print(len(strs))
for p,a,b in strs:
    if 'generatedAt' in p or '_artifactStamps' in p: continue
    if isinstance(a,str) and re.fullmatch(r'[0-9a-f]{32}',a): continue
    print(p,'|',repr(a)[:90],'->',repr(b)[:90])
