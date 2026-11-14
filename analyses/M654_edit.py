"""M654 (UI-05, thermal group, forests): ShareForest + ChartWithTable around the fill-sensitivity, longer-fill and start-temperature-tercile tables. ASCII only; JS non-ASCII via escapes."""
def rep(t, o, n):
    assert t.count(o) == 1, (o[:90], t.count(o))
    return t.replace(o, n)

p = 'xtrail_summary.jsx'
s = open(p, encoding='utf-8', newline='').read(); crlf = '\r\n' in s[:5000]; S = s.replace('\r\n', '\n')

comp = '''/* M654 (UI-05, spec analyses/M654_spec.md): forest of the observed share (E1) and the Kaplan-Meier (product-limit) estimate (E2) per setting, built from the SAME ledger values the table beside it prints.
   items: [{label, r:{supported, E1:{point,ci95}, E2:{point,ci95}}, sub}]; an unsupported row is text ("not supported"), never a zero; no interval is invented (IntervalForest rules). */
function ShareForest({ items, h, ariaLabel }) {
  const rows = [];
  (items || []).forEach(it => {
    const r = it.r;
    [["observed share", "E1", "#2563eb"], ["Kaplan-Meier (product-limit) estimate", "E2", "#ea580c"]].forEach(([nm, key, col]) => {
      const e = r && r.supported && r[key];
      rows.push(e && typeof e.point === "number"
        ? { label: it.label + ", " + nm, est: e.point, lo: e.ci95 && e.ci95[0], hi: e.ci95 && e.ci95[1], color: col, sub: it.sub }
        : { label: it.label + ", " + nm, color: col, note: "not supported", sub: it.sub });
    });
  });
  return <IntervalForest rows={rows} zero={false} xLabel={"share of cold starts reaching the threshold within " + h + " s (95% day-clustered interval)"} ariaLabel={ariaLabel} fmt={v => Number(v).toFixed(3)} lblW={210}/>;
}

'''
S = rep(S, 'function TimeToThresholdPanel() {', comp + 'function TimeToThresholdPanel() {')

def wrap(S, start_marker, forest_jsx):
    i = S.index(start_marker)
    j = S.index('</table>', i) + len('</table>')
    tbl = S[i:j]
    return S[:i] + '<ChartWithTable chart={' + forest_jsx + '}>' + tbl + '</ChartWithTable>' + S[j:]

# 1. fill sensitivity (M437): record fills 0 / 3 / 6
S = wrap(S, '<table style={{borderCollapse:"collapse",margin:"4px 0"}}><thead><tr><th style={th}>Cell</th><th style={th}>Fill (s)</th><th style={th}>Cold starts / days</th><th style={th}>Reached</th><th style={th}>Right-censored',
         '<ShareForest h={FS.h} ariaLabel="Observed share and Kaplan-Meier (product-limit) estimate by forward-fill limit" items={cells.flatMap(k=>FS.fills.map(F=>{ const r=FS.settings[String(F)][k]; return r?{label:(NM[k]||k)+", fill "+F+" s"+(F===FS.record.fill?" (record)":""), r:{supported:r.supported600,E1:r.E1,E2:r.E2}, sub:r.n+" cold starts / "+r.days+" days, "+r.reached+" reached"}:null; }).filter(Boolean))}/>')
# 2. longer fills (M648)
S = wrap(S, '<table style={{borderCollapse:"collapse",margin:"4px 0"}}><thead><tr><th style={th}>Cell</th><th style={th}>Fill (s)</th><th style={th}>Cold starts / days</th><th style={th}>Reached</th><th style={th}>Observed share within {EF.h} s',
         '<ShareForest h={EF.h} ariaLabel="Observed share and Kaplan-Meier (product-limit) estimate by longer forward-fill limit" items={EF.headlineCells.flatMap(k=>EF.fills.map(F=>{ const r=EF.settings[String(F)][k]; return r?{label:(NM[k]||k)+", fill "+F+" s"+(F===EF.record.fill?" (record)":""), r:{supported:r.supported600,E1:r.E1,E2:r.E2}, sub:r.n+" cold starts / "+r.days+" days, "+r.reached+" reached"}:null; }).filter(Boolean))}/>')
# 3. start-temperature terciles (M438)
S = wrap(S, '<table style={{borderCollapse:"collapse",margin:"4px 0"}}><thead><tr><th style={th}>Start temperature</th>',
         '<ShareForest h={SS.headlineH} ariaLabel={(NM[k]||k)+": observed share and Kaplan-Meier (product-limit) estimate by start-temperature tercile"} items={cc.strata.map(s=>{ const r=s.horizons.find(x=>x.h===SS.headlineH); return {label:(NM[k]||k)+", start "+s.range, r:r?{supported:r.supported,E1:r.E1,E2:r.E2}:null, sub:s.n+" cold starts / "+s.days+" days, "+s.reached+" reached"}; })}/>')
open(p, 'w', encoding='utf-8', newline='').write(S.replace('\n', '\r\n') if crlf else S)
print('ok')
