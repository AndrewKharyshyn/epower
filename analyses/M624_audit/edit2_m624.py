"""One-off editor #2 for M624 (gate wording: Kaplan-Meier only as 'Kaplan-Meier (product-limit) estimate'; methodology text hypothesis wording)."""


BS = chr(92)


def edit(p, pairs):
    s = open(p, encoding='utf-8', newline='').read()
    for o, n in pairs:
        assert s.count(o) >= 1, (p, o[:70])
        s = s.replace(o, n)
    open(p, 'w', encoding='utf-8', newline='').write(s)


edit('xtrail_summary.jsx', [
    (r'KAPLAN–MEIER MEDIAN TIME TO THRESHOLD (s; independent censoring assumed; shares of cold starts reaching a threshold are in the time-to-threshold panel)',
     r'Kaplan-Meier (product-limit) estimate of the MEDIAN TIME TO THRESHOLD (s; independent censoring assumed; shares of cold starts reaching a threshold are in the time-to-threshold panel)'),
    (r'Kaplan-Meier median not computed for this cohort.', r'Kaplan-Meier (product-limit) estimate of the median is not computed for this cohort.'),
    ('Coolant '+BS+'u2192 80'+BS+'u00b0C, Kaplan'+BS+'u2013Meier median', 'Coolant '+BS+'u2192 80'+BS+'u00b0C, Kaplan-Meier (product-limit) estimate of the median'),
    ('Oil '+BS+'u2192 80'+BS+'u00b0C, Kaplan'+BS+'u2013Meier median', 'Oil '+BS+'u2192 80'+BS+'u00b0C, Kaplan-Meier (product-limit) estimate of the median'),
    ('Kaplan'+BS+'u2013Meier medians come from the support ledger', 'Kaplan-Meier (product-limit) estimates of the median come from the support ledger'),
])
edit('test_warmup_chart.js', [
    ("all.includes('KAPLAN–MEIER MEDIAN TIME TO THRESHOLD')", "all.includes('Kaplan-Meier (product-limit) estimate of the MEDIAN TIME TO THRESHOLD')"),
    ("/Kaplan-Meier median not computed for this cohort/", r"/Kaplan-Meier \(product-limit\) estimate of the median is not computed for this cohort/"),
])
edit('compute_summary_arrays.py', [
    ("'the coolant-oil lag. Oil warms slower (more thermal mass, indirect '\n            'heating), so it lags coolant. Curve bins",
     "'the coolant-oil lag. A possible reading of the lag is the larger thermal mass of the oil '\n            'and its indirect heating; this is not tested here. Curve bins"),
])
# gate expectations that follow from the M624 spec (Director review R2 and tone 'derived'); recorded as declared deviations in the CHANGELOG entry
edit('semantic_gate.py', [
    ('and "MEDIAN OF REACHERS ONLY (s; understates the time for all cold starts; not a cohort median)" in _d)',
     'and ("Kaplan-Meier (product-limit) estimate of the MEDIAN TIME TO THRESHOLD" in _d) and (_d.count("Median of reachers only") >= 1))      # M624: the headline panel is the Kaplan-Meier median (Director R2); reachers-only medians stay labelled in the time-to-threshold tables'),
    ('only the three non-thesis Measured badges (AFR, oil/coolant lag, departure speed artefact) and the register legend remain (%d: %s)" % (len(_meas), _meas), len(_meas) == 4)',
     'only the two non-thesis Measured badges (AFR, departure speed artefact; M624: the oil/coolant lag badge is Derived because coolant and oil are logged / app-calculated) and the register legend remain (%d: %s)" % (len(_meas), _meas), len(_meas) == 3)'),
])
print("ok")
