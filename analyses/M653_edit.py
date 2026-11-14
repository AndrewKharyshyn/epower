"""M653: builder stops nulling the mileage pace; jsx card label; M632 test list. Byte-level, ASCII only."""
def edit(p, pairs):
    b = open(p, 'rb').read()
    for o, n in pairs:
        ob = o.encode(); assert b.count(ob) == 1, (o[:60], b.count(ob)); b = b.replace(ob, n.encode())
    open(p, 'wb').write(b)
edit('compute_summary_arrays.py', [
 ("'yrPer1kGtc', 'afWeightedYearsTotal', 'yearsToOfficialLifeKm',\n", "'yrPer1kGtc', 'afWeightedYearsTotal',\n"),
 ("'life ceiling, seasonal/hot-tail/plating year sensitivities, years-to-'\n        'official-life). Exposure rates, accumulations, intensities, thresholds-'",
  "'life ceiling, seasonal/hot-tail/plating year sensitivities). The mileage '\n        'pace (usageRate.yearsToOfficialLifeKm: disclosed mileage divided by the logged km per year, arithmetic only) is retained. Exposure rates, accumulations, intensities, thresholds-'"),
])
edit('xtrail_summary.jsx', [('`to ${od.expectedLifeKm.toLocaleString("en-US")} km @ current pace`,', '`to ${od.expectedLifeKm.toLocaleString("en-US")} km @ current pace (arithmetic, not a battery-life estimate)`,')])
edit('tests/synthetic/test_m632_official_fields.py', [('"yearsToOfficialLifeKm", "expectedLifeYr"', '"expectedLifeYr"')])
print('ok')
