"""M348: quantify the Compare WarmupCurve pooling as rendered before the repair (all classes incl. the legacy 'city'
alias of 'urban') against the same n-weighted mean over the canonical classes only. Read-only; writes analyses/M348_warmup_pool_check.json."""
import json, math, re, sys
a = json.load(open('summary_arrays.json', encoding='utf-8'))
data = a['seasonalCharts']['charts']['WarmupCurve']['data']
def pool(d, skip):
    out = []
    for km in d['grid']:
        num = den = 0.0
        for k, c in d['classes'].items():
            if k in skip or not isinstance(c, dict): continue
            for p in c.get('points', []):
                if abs(p['km'] - km) < 1e-9 and isinstance(p.get('med'), (int, float)) and math.isfinite(p['med']):
                    w = p['n'] if isinstance(p.get('n'), (int, float)) and p['n'] > 0 else 1
                    num += p['med'] * w; den += w
        out.append(num / den if den else None)
    return out
res = {'aliasIdentical': {}, 'cohorts': {}}
for coh, d in data.items():
    if not isinstance(d, dict) or 'classes' not in d: continue
    cl = d['classes']
    res['aliasIdentical'][coh] = ((cl.get('urban') or {}).get('points') == (cl.get('city') or {}).get('points'))
    old = pool(d, set()); new = pool(d, {'city'})
    diff = [None if (o is None or n is None) else round(o - n, 3) for o, n in zip(old, new)]
    res['cohorts'][coh] = {'grid': d['grid'], 'asRendered': old, 'canonicalOnly': new, 'diffDegC': diff,
                           'maxAbsDiffDegC': max([abs(x) for x in diff if x is not None] or [None])}
# Rev 2 evidence: fallback weights, single-view class keys, all-zero arrays without count field
fb = {}
for coh, d in data.items():
    if not isinstance(d, dict) or 'classes' not in d: continue
    fb[coh] = sum(1 for k, c in d['classes'].items() if k != 'city' and isinstance(c, dict)
                  for p in c.get('points', []) if not (isinstance(p.get('n'), (int, float)) and p['n'] > 0))
res['fallbackWeight1Points'] = fb
src = open('xtrail_summary.jsx', encoding='utf-8').read()
i = src.index('function WarmupCurve()'); blk = src[i:i + 6000]
res['singleViewClassKeys'] = sorted(set(re.findall(r'wc\.classes\.(\w+)', blk)))
res['singleViewIteratesAllClasses'] = 'Object.values(wc.classes)' in blk or 'Object.keys(wc.classes)' in blk
sd = a['seasonalCharts']['charts']['SpeedDist']['data']
zs = {}
for coh, d in sd.items():
    if not isinstance(d, dict): continue
    for key, v in d.items():
        if isinstance(v, list) and v and all(isinstance(x, (int, float)) and x == 0 for x in v):
            zs.setdefault(coh, []).append(key)
res['speedDistAllZeroArrays'] = zs
res['speedDistCountFieldsPresent'] = sorted({k for d in sd.values() if isinstance(d, dict) for k in d if re.search(r'(^n$|count|drives|nDrives)', k, re.I)})
json.dump(res, open('analyses/M348_warmup_pool_check.json', 'w', encoding='utf-8', newline='\n'), indent=1)
for c, r in res['cohorts'].items(): print(c, 'alias identical:', res['aliasIdentical'][c], 'max |diff| degC', r['maxAbsDiffDegC'])
