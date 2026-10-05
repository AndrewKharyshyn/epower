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
import wire_gtr_seasonal as W
from wire_gtr_seasonal import aggregate, wavg  # reuse verbatim


def refresh(d, merged):
    """Pure builder (F26, audit 2026-10-05): updates the loaded payload `d` in place from the merged fuel-recon frame and returns
    (d, old_corpus, data_all, data_warm, data_shoulder). No file access; main() below does the I/O."""
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
    # M349: glossary values that restate the headline f_gen are bound to the recomputed corpus (they were typed literals: 0.477 / 0.523
    # against a published 0.467 -- the release gate only tolerated the gap while it stayed inside its approximation tolerance).
    # M382 (audit F04): the two efficiency rows are bound the same way (they carried the stale 0.355 / 0.329 against 0.351 / 0.325).
    _fg = float(data_all['corpus']['fGen'])
    _eta = {'η_eng': data_all['corpus']['etaEng'], 'Net traction-bus/fuel index': data_all['corpus']['etaBus']}
    for _g in R.get('glossary', []):
        if _g.get('term') == 'f_gen':
            _g['value'] = f"{_fg:.3f}"
        elif _g.get('term') == 'Battery-buffer share':
            _g['value'] = f"{1 - _fg:.3f}"
        elif _g.get('term') in _eta:
            _g['value'] = f"{float(_eta[_g['term']]):.3f}"
    d['generatorTractionRecon'] = R

    # ---- Warm/Shoulder cohort splits, refreshed source ----
    data_warm = aggregate(merged[merged['thermal_regime'] == 'warm'], 'Warm', cohort_counts['warm'])
    data_shoulder = aggregate(merged[merged['thermal_regime'] == 'shoulder'], 'Shoulder', cohort_counts['shoulder'])
    entry = d['seasonalCharts']['charts']['GeneratorTractionRecon']
    entry.update(W.ENTRY_META)      # M375: the entry metadata (wording of the eligibility rule) follows the module constant
    entry['data']['all'] = data_all
    entry['data']['warm'] = data_warm
    entry['data']['shoulder'] = data_shoulder
    # cold stays None (0 cold drives)
    d['seasonalCharts']['charts']['GeneratorTractionRecon'] = entry
    return d, old_corpus, data_all, data_warm, data_shoulder


def main():
    merged = W.load_merged()      # M375: canonical-clean eligibility (eligibility.py, single flag source drive_master.csv; stop checks)
    d = json.load(open('summary_arrays.json'))
    d, old_corpus, data_all, data_warm, data_shoulder = refresh(d, merged)
    print('OLD corpus:', old_corpus)
    print('NEW corpus:', data_all['corpus'])
    print('NEW nDrives/nProduction/kmProduction:', data_all['nDrives'], data_all['nProduction'], data_all['kmProduction'])
    print()
    print('NEW warm corpus:', data_warm['corpus'])
    print('NEW shoulder corpus:', data_shoulder['corpus'])
    with open('summary_arrays.json', 'w') as f:
        json.dump(d, f, ensure_ascii=False, separators=(',', ':'))
    print('\nsummary_arrays.json updated.')


if __name__ == '__main__':
    main()
