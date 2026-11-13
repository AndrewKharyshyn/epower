"""M631 edit #2: the second unrounded kWh interval display (the output text of the throughput claim)."""
p = 'xtrail_summary.jsx'
s = open(p, encoding='utf-8', newline='').read()
o = 'on gross throughput [${S.energyUncertaintyMC?.grossThroughputMC?.throughputKwh?.p2_5}, ${S.energyUncertaintyMC?.grossThroughputMC?.throughputKwh?.p97_5}] kWh.`}'
n = 'on gross throughput [${S.energyUncertaintyMC?.grossThroughputMC?.throughputKwh?.p2_5?.toFixed(1)}, ${S.energyUncertaintyMC?.grossThroughputMC?.throughputKwh?.p97_5?.toFixed(1)}] kWh.`}'
assert s.count(o) == 1
open(p, 'w', encoding='utf-8', newline='').write(s.replace(o, n))
print('ok')
