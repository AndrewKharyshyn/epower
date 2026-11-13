"""M636 (W1-07): date-stamp the two undated M85 historical figures in the provenance strings (summary_config.json and the copied leaves of summary_arrays.json)."""
import json
O1 = "(time-weighted mean pack ~34.2C, 54.3% of drive-time >=35C, highway thermal rise +17C above ambient)"
N1 = "(at M85, 2026-08-05 corpus, historical: time-weighted mean pack ~34.2C, 54.3% of drive-time >=35C, highway thermal rise +17C above ambient; the live values are in hotTail.packThermalMeasured)"
O2 = "(67.6% highway)"
N2 = "(67.6% highway at M85, 2026-08-05 corpus, historical; the live distance mix is in observedMix)"
for p in ('summary_config.json', 'summary_arrays.json'):
    s = open(p, encoding='utf-8', newline='').read()
    for o, n in ((O1, N1), (O2, N2)):
        assert s.count(o) == (1 if p == 'summary_config.json' else s.count(o)) and s.count(o) >= 1, (p, o, s.count(o))
        print(p, s.count(o))
        s = s.replace(o, n)
    json.loads(s)
    open(p, 'w', encoding='utf-8', newline='').write(s)
