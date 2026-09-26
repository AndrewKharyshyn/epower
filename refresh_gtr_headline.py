"""
M255 (continued): fuel_recon_master.csv was found stale (missing 10
fuel-instrumented drives -- the entire M252 7-drive 2026-09-11 batch plus 2
older files -- never run through fuel_recon.py). Refreshed via
`fuel_recon.py --all` (138->145 rows; 3 of 148 header-present drives
legitimately excluded: 2 near-zero/negative distance, 1 with <10 valid
fuel-flow samples). This script recomputes the corpus-wide §4b headline
(generatorTractionRecon.{corpus,flows,driveTypeSplit,nProduction,nDrives,
kmProduction,basis,productionCheck}) AND the Warm/Shoulder cohort splits
(seasonalCharts.charts.GeneratorTractionRecon) from the refreshed source,
using the exact same verified aggregation method as wire_gtr_seasonal.py
(reused, not reimplemented).
"""
import json
import pandas as pd
from wire_gtr_seasonal import aggregate, wavg  # reuse verbatim

fr = pd.read_csv('fuel_recon_master.csv')
sdm = pd.read_csv('seasonal_drive_master.csv')[['file', 'thermal_regime']]
merged = fr.merge(sdm, on='file', how='left')
assert merged['thermal_regime'].isna().sum() == 0, "unmatched fuel-recon drives"

d = json.load(open('summary_arrays.json'))
cohort_counts = d['seasonalCharts']['_meta']['cohortCounts']

# ---- corpus-wide ("all") headline, same method, whole merged set ----
data_all = aggregate(merged, 'All', cohort_counts['all'])
assert data_all is not None

R = d['generatorTractionRecon']
old_corpus = dict(R['corpus'])
R['nProduction'] = data_all['nProduction']
R['nDrives'] = data_all['nDrives']
R['kmProduction'] = data_all['kmProduction']
R['corpus'] = data_all['corpus']
R['flows'] = data_all['flows']
R['driveTypeSplit'] = data_all['driveTypeSplit']
R['productionCheck'] = data_all['productionCheck']
R['basis'] = (f"Path B (fuel flow \u2192 RPM/load-conditioned BSFC surface \u2192 "
              f"generator \u2192 DC-bus balance), {data_all['nDrives']} clean / "
              f"{data_all['nProduction']} fuel-instrumented drives, "
              f"{data_all['kmProduction']} km.")
d['generatorTractionRecon'] = R

print('OLD corpus:', old_corpus)
print('NEW corpus:', data_all['corpus'])
print('NEW nDrives/nProduction/kmProduction:', data_all['nDrives'], data_all['nProduction'], data_all['kmProduction'])

# ---- Warm/Shoulder cohort splits, refreshed source ----
data_warm = aggregate(merged[merged['thermal_regime'] == 'warm'], 'Warm', cohort_counts['warm'])
data_shoulder = aggregate(merged[merged['thermal_regime'] == 'shoulder'], 'Shoulder', cohort_counts['shoulder'])
print()
print('NEW warm corpus:', data_warm['corpus'])
print('NEW shoulder corpus:', data_shoulder['corpus'])

entry = d['seasonalCharts']['charts']['GeneratorTractionRecon']
entry['data']['all'] = data_all
entry['data']['warm'] = data_warm
entry['data']['shoulder'] = data_shoulder
# cold stays None (0 cold drives)
d['seasonalCharts']['charts']['GeneratorTractionRecon'] = entry

with open('summary_arrays.json', 'w') as f:
    json.dump(d, f, ensure_ascii=False, separators=(',', ':'))
print('\nsummary_arrays.json updated.')
