"""M638: dashboard sentence beside the drive-average hot-tail share (binds S.hotTail.packThermalMeasured.sampleOccupancy)."""
def edit(p, pairs):
    s = open(p, encoding='utf-8', newline='').read()
    for o, n in pairs:
        ok = False
        for oo, nn in ((o, n), (o.replace('\n', '\r\n'), n.replace('\n', '\r\n'))):
            if s.count(oo) == 1:
                s = s.replace(oo, nn); ok = True; break
        assert ok, (p, o[:80], s.count(o))
    open(p, 'w', encoding='utf-8', newline='').write(s)
O = '(a drive-average estimand, not the share of logged samples above 35\u00b0C), highway thermal rise'
N = ('(a drive-average estimand, not the share of logged samples above 35\u00b0C){(() => { const o = S.hotTail?.packThermalMeasured?.sampleOccupancy; if (!o) return null; '
     'return <> and {(o.share["35"]*100).toFixed(1)}% of logged drive time with a mean pack-probe reading \u226535\u00b0C (sample-resolved; 95% CI {(o.ci95["35"][0]*100).toFixed(1)}\u2013{(o.ci95["35"][1]*100).toFixed(1)}%, day-clustered; '
     '{o.nDrives} drives, {o.nDays} days, {o.supportedHours.toFixed(1)}&nbsp;h of supported readings; for \u226540\u00b0C {(o.share["40"]*100).toFixed(1)}%, CI {(o.ci95["40"][0]*100).toFixed(1)}\u2013{(o.ci95["40"][1]*100).toFixed(1)}%; the drive-average share has no interval)</>; })()}, highway thermal rise')
edit('xtrail_summary.jsx', [(O, N)])
print('ok')
