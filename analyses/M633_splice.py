"""M633 one-off splice (W1-12 c, e): the five GTR basis strings from the corpus function refresh_gtr_headline.refresh() on a copy (the deep diff shows ONLY those five leaves change), plus the additive meaning leaf of mdeMohmPerMo from the text of the builder."""
import copy, json, sys

sys.path.insert(0, '.')
import refresh_gtr_headline as R
import wire_gtr_seasonal as W

raw = open('summary_arrays.json', encoding='utf-8', newline='').read()
A = json.loads(raw)
B = copy.deepcopy(A)
d = copy.deepcopy(A)
R.refresh(d, W.load_merged())


def walk(x, y, p=''):
    if isinstance(x, dict) and isinstance(y, dict):
        for k in sorted(set(x) | set(y)):
            yield from walk(x.get(k), y.get(k), p + '/' + k)
    elif isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
        for i, (u, v) in enumerate(zip(x, y)):
            yield from walk(u, v, p + '[%d]' % i)
    elif x != y:
        yield p


changed = list(walk(A, d))
assert len(changed) == 5 and all(c.endswith('/basis') for c in changed), changed
B['generatorTractionRecon']['basis'] = d['generatorTractionRecon']['basis']
for c in ('all', 'warm', 'shoulder', 'cold'):
    B['seasonalCharts']['charts']['GeneratorTractionRecon']['data'][c]['basis'] = d['seasonalCharts']['charts']['GeneratorTractionRecon']['data'][c]['basis']
# (e) additive meaning leaf next to mdeMohmPerMo
holders = [k for k, v in B.items() if isinstance(v, dict) and 'mdeMohmPerMo' in v]
assert len(holders) == 1, holders
B[holders[0]]['mdeMohmPerMoMeaning'] = ('CI half-width of the slope (1.96 x SE), not a power calculation; slopes smaller than it are not distinguished '
                                         'from zero in this window; the key name is kept until a planned schema change (M633, self-audit W1-12 e)')
final = list(walk(A, B))
print(len(final), final)
open('summary_arrays.json', 'w', encoding='utf-8', newline='').write(json.dumps(B, ensure_ascii=False, indent=1) + ('\n' if raw.endswith('\n') else ''))
print('written', holders[0])
