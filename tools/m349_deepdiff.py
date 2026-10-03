"""M349: leaf-level deep diff of summary_arrays.json / fuel_contract.json before vs after the control build; writes analyses/M349_deepdiff.json."""
import json, sys
pre, post = sys.argv[1], sys.argv[2]
a = json.load(open(pre, encoding='utf-8')); b = json.load(open(post, encoding='utf-8'))
out = []
def walk(x, y, p):
    if isinstance(x, dict) and isinstance(y, dict):
        for k in sorted(set(x) | set(y)):
            if k not in x: out.append((p + '/' + k, 'ADDED', None, y[k] if not isinstance(y[k], (dict, list)) else '<struct>'))
            elif k not in y: out.append((p + '/' + k, 'REMOVED', None, None))
            else: walk(x[k], y[k], p + '/' + k)
    elif isinstance(x, list) and isinstance(y, list):
        if len(x) != len(y): out.append((p, 'LEN', len(x), len(y)))
        for i, (u, v) in enumerate(zip(x, y)): walk(u, v, p + '[%d]' % i)
    elif x != y:
        out.append((p, 'CHG', x, y))
walk(a, b, '')
json.dump([list(o) for o in out], open('analyses/M349_deepdiff.json', 'w', encoding='utf-8', newline='\n'), indent=0, default=str)
print(len(out), 'leaf differences')
roots = {}
for p, *_ in out: roots[p.split('/')[1] if p.count('/') else p] = roots.get(p.split('/')[1] if p.count('/') else p, 0) + 1
print(roots)
for o in out[:60]: print(o[0][:120], o[1], str(o[2])[:30], str(o[3])[:30])
