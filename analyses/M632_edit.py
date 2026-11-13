"""M632 (W1-09): the life-year retraction (M114) nulls MODELLED year outputs only; the manufacturer's own source facts officialDisclosureCorrelation.official.{expectedLifeYr, capacityFadeConditionYr} (14 years, from summary_config.json officialDisclosure) are exempt."""
import json

p = 'compute_summary_arrays.py'
s = open(p, encoding='utf-8', newline='').read()
nl = '\r\n' if '\r\n' in s[:5000] else '\n'


def N(t):
    return t.replace('\n', nl)


o = N("""    for _blk in ('cycleLife', 'fadeModes', 'seasonalLife',
                 'officialDisclosureCorrelation', 'observedMix',
                 'realisticBlend'):
        if isinstance(arrays.get(_blk), dict):
            _null_life_years(arrays[_blk])
""")
n = N("""    for _blk in ('cycleLife', 'fadeModes', 'seasonalLife',
                 'officialDisclosureCorrelation', 'observedMix',
                 'realisticBlend'):
        if isinstance(arrays.get(_blk), dict):
            if _blk == 'officialDisclosureCorrelation':
                # M632 (self-audit W1-09): 'official' holds the manufacturer's own SOURCE facts (expectedLifeYr 14, capacityFadeConditionYr 14,
                # copied from cfg.officialDisclosure); they are not modelled life estimates and stay. Every other leaf of the block is still retracted.
                _tmp = {_k2: _v2 for _k2, _v2 in arrays[_blk].items() if _k2 != 'official'}
                _null_life_years(_tmp)
                arrays[_blk].update(_tmp)
            else:
                _null_life_years(arrays[_blk])
""")
assert s.count(o) == 1
s = s.replace(o, n)
open(p, 'w', encoding='utf-8', newline='').write(s)

# payload: restore the two source facts from the config (the only leaves that change)
cfg = json.load(open('summary_config.json', encoding='utf-8'))['officialDisclosure']
A_raw = open('summary_arrays.json', encoding='utf-8', newline='').read()
A = json.loads(A_raw)
off = A['officialDisclosureCorrelation']['official']
assert off['expectedLifeYr'] is None and off['capacityFadeConditionYr'] is None
off['expectedLifeYr'] = cfg['expectedLifeYr']
off['capacityFadeConditionYr'] = cfg['capacityFadeConditionYr']
assert off['expectedLifeYr'] == 14 and off['capacityFadeConditionYr'] == 14
open('summary_arrays.json', 'w', encoding='utf-8', newline='').write(json.dumps(A, ensure_ascii=False, indent=1) + ('\n' if A_raw.endswith('\n') else ''))
print('ok')
