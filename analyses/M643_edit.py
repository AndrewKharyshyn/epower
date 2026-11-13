"""M643 (UI-07, owner decision D-06): the Compare regen dot plots no longer draw the grey connector between the lowest and the highest cohort value in a row (it read as a Cold-to-Warm contrast, against the
2026-10-19 and 2026-11-10 no-contrast decisions). Done with a spec flag noConnector on the three legacy regen bar charts; other Compare charts keep their connector."""
def edit(p, pairs):
    s = open(p, encoding='utf-8', newline='').read()
    for o, n in pairs:
        ok = False
        for oo, nn in ((o, n), (o.replace('\n', '\r\n'), n.replace('\n', '\r\n'))):
            if s.count(oo) == 1:
                s = s.replace(oo, nn); ok = True; break
        assert ok, (o[:90], s.count(o))
    open(p, 'w', encoding='utf-8', newline='').write(s)

edit('xtrail_summary.jsx', [
 ('  RegenByTempMeasured:{kind:"bars",title:', '  RegenByTempMeasured:{kind:"bars",noConnector:true,title:'),
 ('  RegenByType:{kind:"bars",title:', '  RegenByType:{kind:"bars",noConnector:true,title:'),
 ('  RegenByZone:{kind:"bars",title:', '  RegenByZone:{kind:"bars",noConnector:true,title:'),
 ('        {x0!=null&&x1!=null&&x1>x0&&<line x1={x0} x2={x1} y1={cy} y2={cy} stroke="#cbd5e1" strokeWidth={2}/>}',
  '        {!spec.noConnector&&x0!=null&&x1!=null&&x1>x0&&<line data-cmp-connector="1" x1={x0} x2={x1} y1={cy} y2={cy} stroke="#cbd5e1" strokeWidth={2}/>}'),
])
print('ok')
