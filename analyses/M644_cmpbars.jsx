function CmpBars({id,spec,series}){
  // M270 (audit Section 9): aligned-category comparison rendered as a
  // dumbbell / grouped-dot plot (was grouped horizontal bars). Outer-join by
  // canonical category label (M267 FIX #4); cohort encoded by colour AND
  // marker shape; missing cohort/category shows an explicit 'no obs' marker
  // rather than a silent gap.
  // M644 (self-audit UI-01): values sit in a fixed right-hand column, one column per cohort (no value label on the markers, so labels cannot collide),
  // the category label column is 190 px, every text is at least 9 px (the svg has a fixed width inside a horizontally scrolling wrapper instead of shrinking), the column header shows each cohort's marker shape.
  const per=series.map(s=>({key:s.key,label:s.label,col:s.col,marker:s.marker||"circle",cats:(spec.cats?spec.cats(seasonalData(id,s.mode)):[])||[]}));
  const ref=(function(){
    const out=[],seen=new Set();
    per.forEach(p=>p.cats.forEach(c=>{ const lb=clsKey(c);
      if(!seen.has(lb)){ seen.add(lb); out.push({label:c.label,key:lb}); }}));
    return out;
  })();
  if(!ref.length) return <div style={{fontSize:11,color:"#64748b"}}>No categorical data available for these cohorts.</div>;
  const nCat=ref.length; let maxV=0,minV=Infinity;
  per.forEach(p=>p.cats.forEach(c=>{ const hi=Math.max(c&&c.value||0,c&&c.hi||0); if(hi>maxV)maxV=hi; const lo=(c&&c.lo!=null)?c.lo:(c&&c.value); if(lo!=null&&lo<minV)minV=lo; }));
  if(!isFinite(minV))minV=0; if(maxV<=0)maxV=1; if(minV>0)minV=0; // anchor at 0 for magnitude reading
  const digits=spec.digits!=null?spec.digits:1;
  const fmt=v=>(v==null||v!==v)?"—":Number(v).toLocaleString("en-US",{minimumFractionDigits:digits,maximumFractionDigits:digits});
  const colW=58, valW=per.length*colW, labelW=190, plotX=labelW, plotW=380, W=labelW+plotW+valW+16, rowH=28, H=nCat*rowH+34;
  const x=v=>plotX+Math.max(0,Math.min(1,((v||0)-minV)/(maxV-minV)))*plotW;
  const mk=(m,cx,cy,col,k,hollow)=>{ const f=hollow?"none":col, sw=hollow?1:0;
    if(m==="square") return <rect key={k} x={cx-3.5} y={cy-3.5} width={7} height={7} fill={f} stroke={col} strokeWidth={sw||0.8}/>;
    if(m==="diamond") return <rect key={k} x={cx-3.5} y={cy-3.5} width={7} height={7} fill={f} stroke={col} strokeWidth={sw||0.8} transform={`rotate(45 ${cx} ${cy})`}/>;
    return <circle key={k} cx={cx} cy={cy} r={4} fill={f} stroke={col} strokeWidth={sw||0.8}/>; };
  const axisTicks=[minV,(minV+maxV)/2,maxV];
  const vx=si=>plotX+plotW+16+si*colW;
  return <div style={{overflowX:"auto"}} data-cmp-bars="1"><svg width={W} height={H} viewBox={"0 0 "+W+" "+H} style={{display:"block"}}>
    {axisTicks.map((t,i)=><g key={"ax"+i}><line x1={x(t)} x2={x(t)} y1={20} y2={H-4} stroke="#f1f5f9"/><text x={x(t)} y={14} textAnchor="middle" fontSize={9} fill="#64748b">{fmt(t)}</text></g>)}
    {per.map((p,si)=><g key={"hd"+si}>{mk(p.marker,vx(si)+4,10,p.col,"hm"+si,false)}<text x={vx(si)+11} y={14} fontSize={9} fill={p.col} fontWeight={700}>{String(p.label).slice(0,8)}</text></g>)}
    {ref.map((rc,ci)=>{ const cy=34+ci*rowH+rowH/2-6; const lbl=String(rc.label);
      const present=per.map(p=>({p,c:p.cats.find(cc=>clsKey(cc)===rc.key)})).map(o=>({...o,v:(o.c&&typeof o.c.value==="number"&&isFinite(o.c.value))?o.c.value:null})); // M348: null/NaN/non-numeric = not observed; an all-zero array is NOT reinterpreted
      const vals=present.filter(o=>o.v!=null).map(o=>o.v);
      const x0=vals.length?x(Math.min(...vals)):null, x1=vals.length?x(Math.max(...vals)):null;
      return <g key={ci}>
        <text x={labelW-8} y={cy} textAnchor="end" fontSize={10} fill="#475569" dominantBaseline="middle">{lbl.length>31?lbl.slice(0,30)+"…":lbl}<title>{lbl}</title></text>
        {!spec.noConnector&&x0!=null&&x1!=null&&x1>x0&&<line data-cmp-connector="1" x1={x0} x2={x1} y1={cy} y2={cy} stroke="#cbd5e1" strokeWidth={2}/>}
        {present.every(o=>o.v==null)&&<NotObservedRow x={plotX} y={cy-7} w={plotW} h={14} label="not observed in any selected cohort"/>}
        {present.map((o,si)=>{ if(o.v==null){ // explicit no-observations marker at axis origin (hatched) and an em dash in the value column
            return <g key={si} data-not-observed="1"><rect x={plotX-2} y={cy-5+si*3} width={4} height={4} fill="none" stroke={o.p.col} strokeDasharray="1 1"/><title>{o.p.label}: not observed (n=0) — null, not zero</title><text x={vx(si)+11} y={cy} fontSize={9.5} fill="#94a3b8" dominantBaseline="middle">{"—"}</text></g>; }
          const cx=x(o.v);
          return <g key={si}>
            {(o.c.lo!=null&&o.c.hi!=null)&&<line x1={x(o.c.lo)} x2={x(o.c.hi)} y1={cy} y2={cy} stroke={o.p.col} strokeOpacity={0.4} strokeWidth={1.5}/>}
            {mk(o.p.marker,cx,cy,o.p.col,si,false)}
            <text x={vx(si)+11} y={cy} fontSize={9.5} fill={o.p.col} fontWeight={600} dominantBaseline="middle" data-cmp-value="1">{fmt(o.v)}</text>
          </g>; })}
      </g>; })}
  </svg></div>;
}
