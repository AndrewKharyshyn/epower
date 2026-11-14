"""M645 (self-audit UI-01, remainder): chart domains independent of the Compare toggles (CmpBars, CmpBox, CmpLines), box/whisker meaning named per spec,
opaque sticky Compare header with the explanatory text collapsed. Computes the new text first, then writes. ASCII only."""


def apply(txt, pairs):
    crlf = '\r\n' in txt[:5000]
    S = txt.replace('\r\n', '\n')
    for o, n in pairs:
        assert S.count(o) == 1, (o[:90], S.count(o))
        S = S.replace(o, n)
    return S.replace('\n', '\r\n') if crlf else S


p = 'xtrail_summary.jsx'
s = open(p, encoding='utf-8', newline='').read()
BS = chr(92)

pairs = [
    # helper: series that define the domain, independent of the toggles
    ('function activeCompareSeries(sel){',
     '// M645 (UI-01): chart domains are computed over every available cohort, never over the toggled subset, so toggling a series does not move the axis\n'
     'function domainSeries(){ return CMP_SERIES.filter(s=>s.key==="all"||cohortAvailable(s.key)); }\n'
     'function activeCompareSeries(sel){'),
    # ---- CmpBars domain
    ('  const nCat=ref.length; let maxV=0,minV=Infinity;\n'
     '  per.forEach(p=>p.cats.forEach(c=>{',
     '  const nCat=ref.length; let maxV=0,minV=Infinity;\n'
     '  const perDom=domainSeries().map(s=>({cats:(spec.cats?spec.cats(seasonalData(id,s.mode)):[])||[]}));      // M645: domain over all available cohorts\n'
     '  perDom.forEach(p=>p.cats.forEach(c=>{'),
    # ---- CmpBox domain
    ('  let mn=Infinity,mx=-Infinity;\n'
     '  per.forEach(p=>p.cats.forEach(c=>{ [c.wlo,c.q1,c.med,c.q3,c.whi]',
     '  let mn=Infinity,mx=-Infinity;\n'
     '  const perDomB=domainSeries().map(s=>({cats:(spec.cats?spec.cats(seasonalData(id,s.mode)):[])||[]}));      // M645: domain over all available cohorts\n'
     '  perDomB.forEach(p=>p.cats.forEach(c=>{ [c.wlo,c.q1,c.med,c.q3,c.whi]'),
    ('box = q1 to q3, line = median, whiskers = min/max</text>',
     'box = {spec.boxDef||"q1 to q3"}, line = median, whiskers = {spec.whiskDef||"min to max"}; axis fixed over all cohorts</text>'),
    # ---- CmpLines domain
    ('  let mn=Infinity,mx=-Infinity;\n'
     '  drawn.forEach(p=>p.y.forEach(v=>{ if(fin(v)){ if(v<mn)mn=v; if(v>mx)mx=v; } }));\n',
     '  let mn=Infinity,mx=-Infinity;\n'
     '  domainSeries().forEach(s=>((spec.pts?spec.pts(seasonalData(id,s.mode)):[])||[]).forEach(q=>{ if(q&&fin(q.y)){ if(q.y<mn)mn=q.y; if(q.y>mx)mx=q.y; } }));      // M645: y domain over all available cohorts\n'),
    # ---- spec boxes: named meaning
    ('  SocBands:{kind:"box",', '  SocBands:{kind:"box",boxDef:"lo to hi as stored",whiskDef:"the same lo to hi (no separate extremes stored)",'),
    ('  DriveDurationDist:{kind:"box",', '  DriveDurationDist:{kind:"box",boxDef:"q1 to q3",whiskDef:"min to max",'),
    ('  SocBySpeed:{kind:"box",', '  SocBySpeed:{kind:"box",boxDef:"q1 to q3",whiskDef:"min to max",'),
    ('  EngineOnDuration:{kind:"box",', '  EngineOnDuration:{kind:"box",boxDef:"p10 to p90",whiskDef:"min to max",'),
    # ---- header: opaque, collapsing
    ('function CompareControls({sel,onToggle}){\n  const cc=(seasonalMeta().cohortCounts)||{};\n'
     '  return <div data-cohort-compare="1" style={{position:"sticky",top:38,zIndex:49,background:"#faf5fff2",backdropFilter:"blur(2px)",',
     'function CompareControls({sel,onToggle}){\n  const cc=(seasonalMeta().cohortCounts)||{};\n  const [help,setHelp]=React.useState(false);      // M645: the explanatory text is collapsed by default (the header stays short and opaque)\n'
     '  return <div data-cohort-compare="1" style={{position:"sticky",top:38,zIndex:49,background:"#faf5ff",'),
    ('    <div style={{fontSize:9,color:"#a78bda",marginTop:6}}>\n      Toggle series on/off',
     '    <div style={{marginTop:5}}><button data-cmp-help="1" aria-expanded={help} onClick={()=>setHelp(!help)} style={{fontSize:10,color:"#7c3aed",background:"transparent",border:"none",cursor:"pointer",padding:0}}>{help?"\\u25BE Hide notes":"\\u25B8 Notes"}</button></div>\n'
     '    {help&&<div style={{fontSize:10,color:"#6b21a8",marginTop:4}}>\n      Toggle series on/off'),
    ('drives are logged`}.'+chr(10)+'    </div>'+chr(10)+'  </div>;'+chr(10)+'}'+chr(10), 'drives are logged`}.'+chr(10)+'    </div>}'+chr(10)+'  </div>;'+chr(10)+'}'+chr(10)),
]
out = apply(s, pairs)
open(p, 'w', encoding='utf-8', newline='').write(out)
print('ok')
