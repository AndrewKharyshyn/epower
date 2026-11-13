"""M631 (W1-11): formatting and note hygiene. One fixed locale for every toLocaleString call of xtrail_summary.jsx, the kWh interval rounded, 'constant constant' fixed, the unverified '93.2C peak' note removed."""
import re

# 1. fixed locale (a Ukrainian-locale browser printed '10 738,8 km' beside '10738.8 km'; the jsdom dumps are en-US so no gate saw it)
p = 'xtrail_summary.jsx'
s = open(p, encoding='utf-8', newline='').read()
n0 = len(re.findall(r'toLocaleString\(\)|toLocaleString\?\.\(\)|toLocaleString\(undefined,', s))
s = s.replace('toLocaleString()', 'toLocaleString("en-US")').replace('toLocaleString?.()', 'toLocaleString?.("en-US")').replace('toLocaleString(undefined,', 'toLocaleString("en-US",')
assert not re.search(r'toLocaleString\(\)|toLocaleString\?\.\(\)|toLocaleString\(undefined', s)

# 2. kWh interval: one decimal (the interval is +- 4 kWh wide; four decimals were false precision)
o = 'metric={`95% CI [${S.energyUncertaintyMC?.grossThroughputMC?.throughputKwh?.p2_5}, ${S.energyUncertaintyMC?.grossThroughputMC?.throughputKwh?.p97_5}] kWh around ${S.energyUncertaintyMC?.grossThroughputMC?.nominalReleasedThroughputKwh} kWh`}'
n = 'metric={`95% CI [${S.energyUncertaintyMC?.grossThroughputMC?.throughputKwh?.p2_5?.toFixed(1)}, ${S.energyUncertaintyMC?.grossThroughputMC?.throughputKwh?.p97_5?.toFixed(1)}] kWh around ${S.energyUncertaintyMC?.grossThroughputMC?.nominalReleasedThroughputKwh?.toFixed(1)} kWh`}'
assert s.count(o) == 1
s = s.replace(o, n)
open(p, 'w', encoding='utf-8', newline='').write(s)
print('toLocaleString calls fixed:', n0)

# 3. 'A constant constant current offset' -> 'A constant current offset' (producer, shipped payload leaf, tracked sidecar)
for p in ('energy_uncertainty_mc.py', 'energy_uncertainty_mc.json', 'summary_arrays.json'):
    s = open(p, encoding='utf-8', newline='').read()
    assert s.count('A constant constant current offset') == 1, (p, s.count('A constant constant current offset'))
    s = s.replace('A constant constant current offset', 'A constant current offset')
    open(p, 'w', encoding='utf-8', newline='').write(s)

# 4. the unverified '93.2C peak' parenthetical of the Jun 25 session note (self-audit: no quantity of that drive peaks at 93.2 C that the note names; removed, not replaced)
p = 'summary_config.json'
s = open(p, encoding='utf-8', newline='').read()
nl = '\r\n' if '\r\n' in s[:3000] else '\n'
o = '19s regen deceleration (93.2C peak, engine OFF)'
assert s.count(o) == 1, s.count(o)
s = s.replace(o, '19s regen deceleration (engine OFF)')
open(p, 'w', encoding='utf-8', newline='').write(s)
print('ok')
