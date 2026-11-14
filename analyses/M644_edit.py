"""M644 (self-audit UI-01, measured in a real browser): Compare frames, second part. CmpBox, CmpKpi and CmpLines get texts of at least 9 px (fixed-width svg inside a horizontally scrolling wrapper
instead of a shrinking svg), CmpKpi puts its values in a right-hand column (no labels on the markers), CmpLines spaces its x labels by their length and widens an ordinal axis instead of overprinting.
(CmpBars was rewritten before this script: analyses/M644_cmpbars.jsx.) All new text is ASCII except the existing characters kept verbatim."""
import re


def apply(txt, pairs):
    crlf = '\r\n' in txt[:5000]
    S = txt.replace('\r\n', '\n')
    for o, n in pairs:
        assert S.count(o) == 1, (o[:90], S.count(o))
        S = S.replace(o, n)
    return S.replace('\n', '\r\n') if crlf else S


p = 'xtrail_summary.jsx'
s = open(p, encoding='utf-8', newline='').read()

pairs = [
    # ---------------- CmpBox ----------------
    ('  const W=520,labelW=118,plotX=labelW,plotW=W-labelW-46;\n'
     '  const X=v=>plotX+Math.max(0,Math.min(1,(tf(v)-a)/(b-a)))*plotW;\n'
     '  const nS=per.length, boxH=6, gap=2, catPad=9, rowH=nS*(boxH+gap)+catPad, H=ref.length*rowH+22;\n',
     '  const labelW=176,plotX=labelW,plotW=340,W=labelW+plotW+110;      // M644: fixed width, 9 px floor, value text to the right of each box\n'
     '  const X=v=>plotX+Math.max(0,Math.min(1,(tf(v)-a)/(b-a)))*plotW;\n'
     '  const nS=per.length, boxH=9, gap=3, catPad=10, rowH=nS*(boxH+gap)+catPad, H=ref.length*rowH+36;\n'),
    ('  return <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{maxWidth:W}}>\n'
     '    {ticks.map((t,i)=><g key={"t"+i}><line x1={X(t)} x2={X(t)} y1={16} y2={H-4} stroke="#f4f6f9"/><text x={X(t)} y={12} textAnchor="middle" fontSize={7} fill="#cbd5e1">{fmt(t,0)}</text></g>)}\n'
     '    {ref.map((lb,ci)=>{ const y0=22+ci*rowH;\n',
     '  return <div style={{overflowX:"auto"}} data-cmp-box="1"><svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{display:"block"}}>\n'
     '    {ticks.map((t,i)=><g key={"t"+i}><line x1={X(t)} x2={X(t)} y1={18} y2={H-18} stroke="#f4f6f9"/><text x={X(t)} y={13} textAnchor="middle" fontSize={9} fill="#64748b">{fmt(t,0)}</text></g>)}\n'
     '    {ref.map((lb,ci)=>{ const y0=22+ci*rowH;\n'),
    ('<text x={labelW-6} y={y0+(nS*(boxH+gap))/2} textAnchor="end" fontSize={8} fill="#475569" dominantBaseline="middle">{lb.length>19?lb.slice(0,18)+"\\u2026":lb}</text>',
     '<text x={labelW-8} y={y0+(nS*(boxH+gap))/2} textAnchor="end" fontSize={10} fill="#475569" dominantBaseline="middle">{lb.length>29?lb.slice(0,28)+"\\u2026":lb}<title>{lb}</title></text>'),
    ('<text x={whi+3} y={yy+boxH-0.5} fontSize={6.5} fill="#94a3b8">{fmt(c.med)}{c.n!=null?` (n=${c.n})`:""}</text>',
     '<text x={whi+4} y={yy+boxH-1} fontSize={9} fill="#64748b">{fmt(c.med)}{c.n!=null?` (n=${c.n})`:""}</text>'),
    ('    {spec.unit&&<text x={plotX} y={H-1} fontSize={7} fill="#94a3b8">{spec.unit}{log?" (log axis)":""} \u00b7 box = q1\u2013q3, line = median, whiskers = min/max</text>}\n  </svg>;\n}\nfunction CmpKpi',
     '    {spec.unit&&<text x={plotX} y={H-4} fontSize={9} fill="#64748b">{spec.unit}{log?" (log axis)":""} \u2014 box = q1 to q3, line = median, whiskers = min/max</text>}\n  </svg></div>;\n}\nfunction CmpKpi'),
    # ---------------- CmpKpi ----------------
    ('  const W=520,labelW=152,plotX=labelW,plotW=W-labelW-72;\n  const mk=(marker,cx,cy,col)=>{\n    if(marker==="square") return <rect x={cx-3} y={cy-3} width={6} height={6} fill={col}/>;\n    if(marker==="diamond") return <rect x={cx-3} y={cy-3} width={6} height={6} fill={col} transform={`rotate(45 ${cx} ${cy})`}/>;\n    return <circle cx={cx} cy={cy} r={3.4} fill={col}/>; };\n  return <div>\n',
     '  const vcolW=84, valW=series.length*vcolW, labelW=196, plotX=labelW, plotW=250, W=labelW+plotW+valW+12;      // M644: values in a right-hand column per cohort, no labels on the markers\n'
     '  const mk=(marker,cx,cy,col)=>{\n    if(marker==="square") return <rect x={cx-3.5} y={cy-3.5} width={7} height={7} fill={col}/>;\n    if(marker==="diamond") return <rect x={cx-3.5} y={cy-3.5} width={7} height={7} fill={col} transform={`rotate(45 ${cx} ${cy})`}/>;\n    return <circle cx={cx} cy={cy} r={4} fill={col}/>; };\n  return <div style={{overflowX:"auto"}} data-cmp-kpi="1">\n'),
    ('      const allV=hasAll?m.get(data["all"],"all"):null; const H=23;\n      return <svg key={mi} width="100%" viewBox={`0 0 ${W} ${H+6}`} style={{maxWidth:W,display:"block"}}>\n        <text x={labelW-6} y={H/2} textAnchor="end" fontSize={8.5} fill="#334155" dominantBaseline="middle">{m.label}{m.unit?` (${m.unit})`:""}</text>\n',
     '      const allV=hasAll?m.get(data["all"],"all"):null; const H=24;\n      const vxs=i=>plotX+plotW+14+i*vcolW;\n      return <svg key={mi} width={W} height={H+4} viewBox={`0 0 ${W} ${H+4}`} style={{display:"block"}}>\n        <text x={labelW-8} y={H/2} textAnchor="end" fontSize={10} fill="#334155" dominantBaseline="middle">{(m.label+(m.unit?` (${m.unit})`:"")).length>34?(m.label+(m.unit?` (${m.unit})`:"")).slice(0,33)+"\\u2026":m.label+(m.unit?` (${m.unit})`:"")}<title>{m.label}{m.unit?` (${m.unit})`:""}</title></text>\n'),
    ('            <text x={cx} y={(drawn.indexOf(o)%2===0)?H/2-5:H/2+10} textAnchor="middle" fontSize={7} fill={o.s.col}>{fmt(o.v,dg)}{(dl!=null&&Math.abs(dl)>=Math.pow(10,-dg))?<tspan fill="#94a3b8">{` (${dl>=0?"+":""}${fmt(dl,dg)})`}</tspan>:null}</text>\n',
     '            <text x={vxs(series.indexOf(o.s))} y={H/2} fontSize={9.5} fill={o.s.col} fontWeight={600} dominantBaseline="middle" data-cmp-value="1">{fmt(o.v,dg)}{(dl!=null&&Math.abs(dl)>=Math.pow(10,-dg))?<tspan fill="#64748b" fontWeight={400}>{` (${dl>=0?"+":""}${fmt(dl,dg)})`}</tspan>:null}</text>\n'),
    ('        {noObs.map(o=><g key={o.s.key}><line x1={plotX} x2={plotX} y1={H/2-4} y2={H/2+4} stroke="#cbd5e1"/><title>{o.s.label}: no observations</title></g>)}\n      </svg>;',
     '        {noObs.map(o=><g key={o.s.key}><line x1={plotX} x2={plotX} y1={H/2-4} y2={H/2+4} stroke="#cbd5e1"/><text x={vxs(series.indexOf(o.s))} y={H/2} fontSize={9.5} fill="#94a3b8" dominantBaseline="middle">{"\\u2014"}</text><title>{o.s.label}: no observations</title></g>)}\n      </svg>;'),
    # ---------------- CmpLines ----------------
    ('  const W=520,H=210,L=46,R=12,T=14,B=28,pw=W-L-R,ph=H-T-B;\n',
     '  const lblTxt=xs.map(v=>String(v)), maxCh=Math.max(1,...lblTxt.map(q=>q.length)), cell=maxCh*5.6+8;      // M644: x labels spaced by their length; an ordinal axis is widened instead of overprinting\n'
     '  const L=46,R=12,T=16,B=32,H=222, W=Math.min(860,Math.max(520,L+R+(num?0:n*cell))), pw=W-L-R, ph=H-T-B;\n'),
    ('xs.forEach((_,i)=>{ if(X(i)-lastPx>=24||i===n-1&&X(i)-lastPx>=24){ lblIdx.push(i); lastPx=X(i); } });',
     'xs.forEach((_,i)=>{ if(X(i)-lastPx>=cell){ lblIdx.push(i); lastPx=X(i); } });'),
    ('  return <><svg width="100%" viewBox={"0 0 "+W+" "+H} style={{maxWidth:W}} data-cmp-lines-x={num?"numeric":"ordinal"}>\n',
     '  return <><div style={{overflowX:"auto"}}><svg width={W} height={H} viewBox={"0 0 "+W+" "+H} style={{display:"block"}} data-cmp-lines-x={num?"numeric":"ordinal"}>\n'),
    ('textAnchor="end" fontSize={8} fill="#94a3b8">{Number(t).toLocaleString("en-US",{maximumFractionDigits:digits})}</text></g>)}\n',
     'textAnchor="end" fontSize={9} fill="#64748b">{Number(t).toLocaleString("en-US",{maximumFractionDigits:digits})}</text></g>)}\n'),
    ('y={H-B+13} textAnchor="middle" fontSize={7.5} fill="#94a3b8">{String(xs[i])}</text>)}', 'y={H-B+14} textAnchor="middle" fontSize={9} fill="#64748b">{String(xs[i])}</text>)}'),
    ('{spec.xtitle&&<text x={W-R} y={H-3} textAnchor="end" fontSize={7.5} fill="#94a3b8">{spec.xtitle}</text>}', '{spec.xtitle&&<text x={W-R} y={H-3} textAnchor="end" fontSize={9} fill="#64748b">{spec.xtitle}</text>}'),
    ('<text x={W-R-2} y={ry-3} textAnchor="end" fontSize={7.5} fill="#64748b">', '<text x={W-R-2} y={ry-3} textAnchor="end" fontSize={9} fill="#64748b">'),
    ('    {spec.unit&&<text x={L} y={10} fontSize={8} fill="#94a3b8">{spec.unit}</text>}\n  </svg>\n  {noObs.length>0',
     '    {spec.unit&&<text x={L} y={11} fontSize={9} fill="#64748b">{spec.unit}</text>}\n  </svg></div>\n  {noObs.length>0'),
]
out = apply(s, pairs)
open(p, 'w', encoding='utf-8', newline='').write(out)
print('ok')
