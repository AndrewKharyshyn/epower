"""M627 jsx edit #2 (Director conditions): data-quality observation (0.1 kW-grid files), the belowCeiling label, and the denominator note."""
p = 'xtrail_summary.jsx'
s = open(p, encoding='utf-8', newline='').read()


def rep(old, new):
    global s
    for o, n in ((old, new), (old.replace('\n', '\r\n'), new.replace('\n', '\r\n'))):
        if s.count(o) == 1:
            s = s.replace(o, n)
            return
    raise SystemExit('anchor not unique: ' + old[:70] + ' ' + str(s.count(old)))


rep('The statistics for events whose limit is below that value are in the data (<code>belowCeiling</code>); they are conditional on the denominator and are not a censoring correction.</p>',
    'Events whose reported limit is below that value (<code>belowCeiling</code>: {h.chargeUtilization && h.chargeUtilization.belowCeiling ? `charge ${h.chargeUtilization.belowCeiling.nEvents} events on ${h.chargeUtilization.belowCeiling.nDrives} drives and ${h.chargeUtilization.belowCeiling.nDays} days, median ${f3(h.chargeUtilization.belowCeiling.median)}` : "charge none"}; {h.dischargeUtilization && h.dischargeUtilization.belowCeiling ? `discharge ${h.dischargeUtilization.belowCeiling.nEvents} events on ${h.dischargeUtilization.belowCeiling.nDrives} drives and ${h.dischargeUtilization.belowCeiling.nDays} days, median ${f3(h.dischargeUtilization.belowCeiling.median)}` : "discharge none"}) are descriptive and conditional on the reported limit being below that value; this is not a censoring correction.</p>')
rep('The two eras are shown side by side; no contrast between them is drawn, and nothing here shows that the limit constrained driving.</p>',
    'Data-quality observation, not interpreted: {Object.keys(un.eras || {}).map(e => `${e} era ${f3(un.eras[e].shareOnQuarterKwGrid)} of samples on the usual 0.25 kW grid${un.eras[e].filesOffQuarterKwGrid ? `, ${un.eras[e].filesOffQuarterKwGrid} files off it (${un.eras[e].offQuarterDateFrom} to ${un.eras[e].offQuarterDateTo})` : ""}`).join("; ")}. The two eras differ in channel polling gap and both cover 2026-09-30; they are shown side by side, no contrast between them is drawn, and nothing here shows that the limit constrained driving. {cv.rawFilesNote}.</p>')
open(p, 'w', encoding='utf-8', newline='').write(s)
print('ok')
