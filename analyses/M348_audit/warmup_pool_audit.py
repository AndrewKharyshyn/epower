import json
d=json.load(open('summary_arrays.json',encoding='utf-8'))['seasonalCharts']['charts']['WarmupCurve']['data']
canon=['urban','mixed','mixed_highway','highway']
out={'aliasIdentical':{},'pooledCanonical':{},'pooledWithAlias':{},'maxAbsDiff':{},'fallbackWeightPoints':0,'notes':[]}
print(list(d.keys()) if isinstance(d,dict) else type(d))
for c in ['all','warm','shoulder']:
    co=d[c]; g=co['grid']; cl=co.get('classes') or {}
    print(c,list(cl.keys()), len(g))
    def pts(name):
        v=cl.get(name)
        if not v: return None
        p=v['points'] if isinstance(v,dict) else v
        return {round(x['km'],6):x for x in p}
    P={n:pts(n) for n in list(cl.keys())}
    cy,ur=P.get('city'),P.get('urban')
    out['aliasIdentical'][c]=(cy==ur) if (cy is not None or ur is not None) else None
    if cy is None or ur is None: out['notes'].append(f'{c}: city={cy is not None} urban={ur is not None}')
    def pool(names):
        r=[]
        for km in g:
            k=round(km,6); s=w=0
            for n in names:
                p=(P.get(n) or {}).get(k)
                if not p: continue
                nn=p.get('n'); m=p.get('med')
                if nn is None or m is None or nn<=0 or m!=m:
                    out['fallbackWeightPoints']+=1; out['notes'].append(f'{c} km{km} {n} n={nn} med={m}'); continue
                s+=nn*m; w+=nn
            r.append(round(s/w,4) if w else None)
        return r
    a=pool(canon); b=pool(canon+['city'])
    out['pooledCanonical'][c]=a; out['pooledWithAlias'][c]=b
    out['maxAbsDiff'][c]=max([abs(x-y) for x,y in zip(a,b) if x is not None and y is not None] or [0])
print(json.dumps(out))
