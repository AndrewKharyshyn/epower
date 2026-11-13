"""M633 (W1-12 label points a, c, e; f verified, b/d/g are analysis items for their own specs).
(a) the regen exploratory notes declare which floor governs the totals (days), (c) the GTR basis text '435 clean / 435 fuel-instrumented' -> '435 clean of 437 fuel-instrumented', (e) a meaning leaf for mdeMohmPerMo (a CI half-width, not an 80 % power MDE)."""
import json


def edit(p, pairs):
    s = open(p, encoding='utf-8', newline='').read()
    for o, n in pairs:
        ok = False
        for oo, nn in ((o, n), (o.replace('\n', '\r\n'), n.replace('\n', '\r\n'))):
            if s.count(oo) == 1:
                s = s.replace(oo, nn)
                ok = True
                break
        assert ok, (p, o[:90], s.count(o))
    open(p, 'w', encoding='utf-8', newline='').write(s)


# (a) the declaration of the governing floor, in both exploratory notes (the days floor decides exploratory vs interval; the ISO-week floor applies only to the week-block sensitivity and the SOC-standardised view)
FLOOR = ' The 5-calendar-day floor governs these totals; the 5-ISO-week floor applies only to the week-block sensitivity and the SOC-standardised view.'
edit('xtrail_summary.jsx', [
    ('in this polling group; no interval is drawn below the support floor.</div>):null)}',
     'in this polling group; no interval is drawn below the support floor.' + FLOOR + '</div>):null)}'),
    ('in this selection; no interval is computed.</div>):null)}',
     'in this selection; no interval is computed.' + FLOOR + '</div>):null)}'),
])

# (c) basis text: clean of all fuel-instrumented rows (the canonical-excluded drives are in the second number, no longer hidden by the first)
edit('wire_gtr_seasonal.py', [
    ('''    nProduction = len(subset)
    clean = subset[subset['f_gen'].notna()].copy()''',
     '''    nFuelRows = len(subset)                          # M633 (W1-12 c): all fuel-instrumented rows of the set, before the canonical exclusion
    if canonical:
        subset = subset[~subset['ens_excluded']]
    nProduction = len(subset)
    clean = subset[subset['f_gen'].notna()].copy()'''),
    ('''    if canonical:
        assert 'ens_excluded' in subset.columns, "aggregate() needs the canonical flag: build the frame with load_merged()"
        subset = subset[~subset['ens_excluded']]
''', '''    if canonical:
        assert 'ens_excluded' in subset.columns, "aggregate() needs the canonical flag: build the frame with load_merged()"
'''),
    ('''f"generator \\u2192 DC-bus balance), {nDrives} clean / {nProduction} "
             f"fuel-instrumented drives, {km} km \\u2014 {cohort_label} cohort "''',
     '''f"generator \\u2192 DC-bus balance), {nDrives} clean of {nFuelRows} "
             f"fuel-instrumented drives, {km} km \\u2014 {cohort_label} cohort "'''),
])
edit('refresh_gtr_headline.py', [
    ('''f"generator \\u2192 DC-bus balance), {data_all['nDrives']} clean / "
                  f"{data_all['nProduction']} fuel-instrumented drives, "''',
     '''f"generator \\u2192 DC-bus balance), {data_all['nDrives']} clean of "
                  f"{len(merged)} fuel-instrumented drives, "'''),
])

# (e) meaning leaf for mdeMohmPerMo (key kept: a rename needs a planned schema change)
edit('compute_summary_arrays.py', [
    ("        'mdeMohmPerMo': round(mde, 3),\n",
     "        'mdeMohmPerMo': round(mde, 3),\n"
     "        'mdeMohmPerMoMeaning': ('CI half-width of the slope (1.96 x SE), not a power calculation; slopes smaller than it are not distinguished '\n"
     "                                'from zero in this window; the key name is kept until a planned schema change (M633, self-audit W1-12 e)'),\n"),
])
print('ok')
