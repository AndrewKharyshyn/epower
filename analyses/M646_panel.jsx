function CmpContrastPanel(){
  // M646 (owner decision 2026-11-14, spec analyses/M646_spec.md Rev 1): Cold / Shoulder minus Warm, raw and route-mix standardised, with a day-clustered bootstrap interval.
  // Binds to S.cohortContrast (nothing computed here). Domain per metric is fixed over every contrast (it does not move with the toggles).
  const sel=React.useContext(CompareCtx);
  const C=S.cohortContrast;
  if(!C||!C.metrics) return null;
  const show=k=>sel&&sel[k]&&cohortAvailable(k);
  const keys=["shoulder","cold"].filter(show);
  if(!keys.length||!sel.warm) return <CmpFrame title="Difference from Warm"><div style={{fontSize:11,color:"#64748b"}}>Enable Warm and at least one of Cold or Shoulder in the filter bar to see the difference from Warm.</div></CmpFrame>;
  const nm={shoulder:"Shoulder",cold:"Cold"}, col={shoulder:"#7C3AED",cold:"#0072B2"};
  const fmt=(v,d)=>(v==null||v!==v)?"\u2014":(v>0?"+":"")+Number(v).toLocaleString("en-US",{minimumFractionDigits:d,maximumFractionDigits:d});
  return <CmpFrame title="Difference from Warm (cohort minus Warm)" series={[]} note={C.caption}>
    <div data-cmp-contrast="1">
    {Object.keys(C.metrics).map(mk=>{ const m=C.metrics[mk]; const dg=mk==="M1"?2:1;
      const all=[]; Object.keys(m.contrasts).forEach(c=>["raw","adjusted"].forEach(v=>{ const e=m.contrasts[c][v]; if(e&&e.estimable){ all.push(e.estimate); if(e.ci95){ all.push(e.ci95[0],e.ci95[1]); } } }));
      const lo=Math.min(0,...all), hi=Math.max(0,...all), pad=(hi-lo)*0.06||1;
      const rows=[]; keys.forEach(c=>{ const e=m.contrasts[c]; if(e) [["raw","Unadjusted"],["adjusted","Route-mix standardised (urban/non-urban only)"]].forEach(([v,lb])=>rows.push({c,v,lb,e,r:e[v]})); });
      const labelW=250, plotW=300, valW=230, W=labelW+plotW+valW, rowH=24, H=rows.length*rowH+36;
      const X=v=>labelW+((v-(lo-pad))/((hi+pad)-(lo-pad)))*plotW;
      return <div key={mk} style={{marginBottom:12,overflowX:"auto"}} data-cmp-contrast-metric={mk}>
        <div style={{fontSize:11,fontWeight:700,color:"#334155",marginBottom:2}}>{m.label} <span style={{fontWeight:400,color:"#64748b"}}>({m.unit}; difference from Warm)</span></div>
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{display:"block"}}>
          <line x1={X(0)} x2={X(0)} y1={18} y2={H-4} stroke="#94a3b8" strokeDasharray="3 3"/>
          {[lo,0,hi].filter((t,i,a)=>a.indexOf(t)===i).map((t,i)=><text key={i} x={X(t)} y={12} textAnchor="middle" fontSize={9} fill="#64748b">{fmt(t,dg)}</text>)}
          {rows.map((o,i)=>{ const cy=24+i*rowH+rowH/2-2, r=o.r, e=o.e;
            const sup=e.support[o.c]; const eff=e.effectiveDays[o.c];
            return <g key={i}>
              <text x={labelW-8} y={cy} textAnchor="end" fontSize={10} fill={col[o.c]} fontWeight={700} dominantBaseline="middle">{nm[o.c]} {"\u2212"} Warm, {o.v==="raw"?"unadjusted":"route-standardised"}</text>
              {r&&r.estimable?<g>
                {r.ci95&&<line x1={X(r.ci95[0])} x2={X(r.ci95[1])} y1={cy} y2={cy} stroke={col[o.c]} strokeOpacity={e.exploratory?0.35:0.8} strokeWidth={e.exploratory?1.5:2.4} strokeDasharray={e.exploratory?"4 3":""}/>}
                <circle cx={X(r.estimate)} cy={cy} r={4} fill={e.exploratory?"#fff":col[o.c]} stroke={col[o.c]} strokeWidth={1.5}/>
                <text x={labelW+plotW+14} y={cy} fontSize={9.5} fill="#334155" dominantBaseline="middle" data-cmp-value="1">{fmt(r.estimate,dg)} [{r.ci95?fmt(r.ci95[0],dg)+", "+fmt(r.ci95[1],dg):"no interval"}]</text>
              </g>:<text x={labelW+14} y={cy} fontSize={9.5} fill="#94a3b8" dominantBaseline="middle">not estimable</text>}
              <title>{nm[o.c]}: {sup.nDrives} drives on {sup.nDays} days; Warm: {e.support.warm.nDrives} drives on {e.support.warm.nDays} days; effective days {eff} vs {e.effectiveDays.warm}{r&&r.reading?"; "+r.reading:""}</title>
            </g>; })}
        </svg>
        {keys.map(c=>{ const e=m.contrasts[c]; if(!e) return null; const ra=e.raw, ad=e.adjusted;
          return <div key={c} style={{fontSize:9.5,color:"#64748b",lineHeight:1.5}} data-cmp-contrast-note={c}>
            <strong style={{color:col[c]}}>{nm[c]}</strong>: {e.support[c].nDrives} drives on {e.support[c].nDays} days ({e.calendarWindows[c][0]} to {e.calendarWindows[c][1]}, {e.effectiveDays[c]} effective days) against Warm {e.support.warm.nDrives} drives on {e.support.warm.nDays} days ({e.calendarWindows.warm[0]} to {e.calendarWindows.warm[1]}, {e.effectiveDays.warm} effective days).
            {e.exploratory?" Exploratory: fewer than 10 effective days in a cohort, so no verdict is stated.":(ra&&ra.reading?" Unadjusted: "+ra.reading+".":"")}{!e.exploratory&&ad&&ad.reading?" Route-mix standardised: "+ad.reading+".":""}
            {ad&&!ad.estimable?" Route-mix standardised: "+ad.reason+".":""}{e.routeMixDisagreement?" The two versions disagree in sign or in whether the interval excludes zero: the contrast depends on route mix.":""}
            {ra&&ra.lodoRange?` Leave-one-day-out range of the unadjusted difference ${fmt(ra.lodoRange[0],dg)} to ${fmt(ra.lodoRange[1],dg)}.`:""}
          </div>; })}
      </div>; })}
    <div style={{fontSize:9.5,color:"#64748b",lineHeight:1.5}}>{C.method}</div>
    </div>
  </CmpFrame>;
}
