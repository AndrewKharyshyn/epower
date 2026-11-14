"""M656 (UI-05, cell-spread step sensitivity): two forests (months slope per model, level step per model) in front of the unchanged model table. ASCII only."""
def rep(t, o, n):
    assert t.count(o) == 1, (o[:90], t.count(o))
    return t.replace(o, n)
p = 'xtrail_summary.jsx'
s = open(p, encoding='utf-8', newline='').read(); crlf = '\r\n' in s[:5000]; S = s.replace('\r\n', '\n')
i = S.index('      <table style={{width:"100%",fontSize:9,borderCollapse:"collapse",marginTop:6}}>\n        <thead><tr style={{color:"#64748b",textAlign:"left"}}><th>model</th>')
j = S.index('</table>', i) + len('</table>')
tbl = S[i:j]
chart = ('<div data-csstep-forests="1">\n'
 '        <IntervalForest zero={true} xLabel="months slope, mV/month (95% interval, day clusters)" ariaLabel="Cell-spread months slope by model" lblW={230}\n'
 '          caption={`Same ${af.n} drives on ${af.days} days for every model; label order as in the table; the model with calendar-month fixed effects has no months term.`}\n'
 '          rows={Object.keys(lab).filter(k=>B.models[k]).map(k=>{const m=B.models[k]; return m.est==null?{label:lab[k],note:"no months term",sub:"AIC "+f(m.aic,1)+", CV RMSE "+f(m.cv_rmse_day_blocked)}:{label:lab[k],est:m.est,lo:Array.isArray(m.ci95)?m.ci95[0]:null,hi:Array.isArray(m.ci95)?m.ci95[1]:null,sub:"AIC "+f(m.aic,1)+", CV RMSE "+f(m.cv_rmse_day_blocked)};})}/>\n'
 '        <IntervalForest zero={true} xLabel="level step, mV (95% interval, day clusters)" ariaLabel="Cell-spread level step by model" lblW={230}\n'
 '          caption={`Models that allow a level change at ${B.stepDate}; the linear models have no step term.`}\n'
 '          rows={Object.keys(lab).filter(k=>B.models[k]&&B.models[k].step_term).map(k=>{const t=B.models[k].step_term; return {label:lab[k],est:t.est,lo:Array.isArray(t.ci95)?t.ci95[0]:null,hi:Array.isArray(t.ci95)?t.ci95[1]:null};})}/>\n'
 '      </div>')
S = S[:i] + '      <ChartWithTable chart={' + chart + '}>\n' + tbl + '\n      </ChartWithTable>' + S[j:]
open(p, 'w', encoding='utf-8', newline='').write(S.replace('\n', '\r\n') if crlf else S)
print('ok')
