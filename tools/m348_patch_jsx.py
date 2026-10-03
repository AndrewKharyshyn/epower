"""M348 one-shot patch of the Compare 'lines' renderer in xtrail_summary.jsx (renderer only; no payload change).
Exact-string replacements; aborts if any anchor is missing or ambiguous. Idempotence: refuses to run twice."""
import re, sys
P = 'xtrail_summary.jsx'
s = open(P, encoding='utf-8', newline='').read()
if 'M348' in s and 'cmpPoolWarmup' in s:
    sys.exit('already patched')

def cut(start_marker, end_marker):
    i = s.index(start_marker); j = s.index(end_marker, i)
    assert s.count(start_marker) == 1, start_marker
    return i, j

# ---- 1. line specs ----
i, j = cut('  WarmupCurve:{kind:"lines"', '  // ---- KPI-delta tables')
new_specs = '''  // M348 (audit F11): line specs return pts(d)=[{x,y}] with a numeric x (xkind "num": drawn at true scale, outer-joined by
  // x) or an ordinal label (xkind "ord": canonical order = the All payload, extras appended). No payload change.
  WarmupCurve:{kind:"lines",xkind:"num",xtitle:"km",title:"Coolant warm-up curve (\\u00b0C vs distance, km; n-weighted mean of per-class medians)",unit:"\\u00b0C",digits:0,
    note:"Weighted summary of class medians, not a pooled-sample median; weights = drives per class at each km (the class mix changes along the km axis as short drives drop out); alias classes counted once.",
    pts:d=>cmpPoolWarmup(d),
    ref:d=>(d&&typeof d.operatingC==="number"&&isFinite(d.operatingC))?{y:d.operatingC,label:"reference level "+Math.round(d.operatingC)+" \\u00b0C (not observed data)"}:null},
  BatteryThermalCurve:{kind:"lines",xkind:"num",xtitle:"min",title:"Battery pack temperature vs minutes (mean of 4 sensors)",unit:"\\u00b0C",digits:1,
    pts:d=>Array.isArray(d)?d.map(r=>{ const v=[r.s1,r.s2,r.s3,r.s4].filter(x=>typeof x==="number"&&isFinite(x)); return {x:r.min,y:v.length?v.reduce((a,b)=>a+b,0)/v.length:null}; }):[]},
  TorqueBySpeed:{kind:"lines",xkind:"ord",title:"Cruise torque vs speed (Nm)",unit:"Nm",digits:0,
    pts:d=>Array.isArray(d)?d.map(r=>({x:String(r.speed),y:r.cruiseMed})):[]},
  RpmDistribution:{kind:"lines",xkind:"ord",title:"Engine-on RPM time distribution (%)",unit:"%",digits:1,
    pts:d=>(d&&Array.isArray(d.bins)&&Array.isArray(d.pooledPct))?d.bins.map((b,i)=>({x:String(b),y:d.pooledPct[i]})):[]},
'''
s = s[:i] + new_specs + s[j:]

# ---- 2. pooling helper (before COMPARE_SPECS) ----
anchor = 'const COMPARE_SPECS={'
assert s.count(anchor) == 1
helper = '''// M348: n-weighted mean (per grid km) of the per-class MEDIANS over canonical classes only. The payload carries the legacy
// alias key "city" (points identical to "urban"); an alias is counted once (clsKey maps city->urban, exact canonical key wins).
// Null/empty classes are skipped. Fallback weight 1 (n missing) is flagged on the point (fb:true).
function cmpPoolWarmup(d){
  if(!d||!Array.isArray(d.grid)||!d.classes) return [];
  const seen={}, cls=[];
  const ent=Object.keys(d.classes).filter(k=>d.classes[k]&&Array.isArray(d.classes[k].points));
  ent.filter(k=>k===clsKey({label:k})).concat(ent.filter(k=>k!==clsKey({label:k}))).forEach(k=>{ const ck=clsKey({label:k}); if(!seen[ck]){ seen[ck]=1; cls.push(d.classes[k]); } });
  return d.grid.map(km=>{
    let num=0,den=0,fb=false;
    cls.forEach(c=>{ const p=c.points.find(pt=>Math.abs(pt.km-km)<1e-9);
      if(p&&typeof p.med==="number"&&isFinite(p.med)){ const ok=(typeof p.n==="number"&&p.n>0); if(!ok) fb=true; const w=ok?p.n:1; num+=p.med*w; den+=w; }});
    return {x:km,y:den>0?num/den:null,fb:fb};
  });
}
'''
s = s.replace(anchor, helper + anchor)

# ---- 3. CmpLines ----
i, j = cut('function CmpLines({id,spec,series}){', 'function CompareBlock({id}){')
new_lines = r'''function CmpLines({id,spec,series}){
  // M348 (audit F11): series are outer-joined by x. Numeric axes (xkind "num") are drawn at true scale; ordinal axes (bins)
  // keep the canonical order of the All payload (extras from other cohorts appended). A cohort with no point at an x
  // keeps a gap (no interpolation). The reference level (spec.ref) is a separate dashed line, outside the y-range logic.
  const fin=v=>typeof v==="number"&&isFinite(v);
  const num=spec.xkind==="num";
  const rawAll=(spec.pts?spec.pts(seasonalData(id,"all")):[])||[];
  const per=series.map(s=>{ const pts=((spec.pts?spec.pts(seasonalData(id,s.mode)):[])||[]).filter(p=>p&&(num?fin(p.x):p.x!=null)); const m=new Map(); pts.forEach(p=>{ const k=num?Number(p.x):String(p.x); if(!m.has(k)) m.set(k,p); });
    return {key:s.key,label:s.label,col:s.col,dash:s.dash||"",marker:s.marker||"circle",width:s.width||1.8,m:m}; });
  let xs=[]; // union axis
  if(num){ const set=new Set(); per.forEach(p=>p.m.forEach((_,k)=>set.add(k))); xs=Array.from(set).sort((a,b)=>a-b); }
  else { const seenK=new Set(); rawAll.forEach(p=>{ if(p&&p.x!=null&&!seenK.has(String(p.x))){ seenK.add(String(p.x)); xs.push(String(p.x)); } });
    per.forEach(p=>p.m.forEach((_,k)=>{ if(!seenK.has(k)){ seenK.add(k); xs.push(k); } })); }
  per.forEach(p=>{ p.y=xs.map(k=>{ const q=p.m.get(k); return (q&&fin(q.y))?q.y:null; }); p.fb=xs.map(k=>{ const q=p.m.get(k); return !!(q&&q.fb); }); });
  const finiteCount=p=>p.y.filter(fin).length;
  const noObs=per.filter(p=>finiteCount(p)===0);          // M270: cohorts with no support in this view
  const drawn=per.filter(p=>finiteCount(p)>0);
  const n=xs.length;
  if(!n||!drawn.length) return <div style={{fontSize:11,color:"#64748b"}}>No curve data available for these cohorts.</div>;
  let mn=Infinity,mx=-Infinity;
  drawn.forEach(p=>p.y.forEach(v=>{ if(fin(v)){ if(v<mn)mn=v; if(v>mx)mx=v; } }));
  if(!isFinite(mn)) return <div style={{fontSize:11,color:"#64748b"}}>No numeric curve values for these cohorts.</div>;
  if(mn===mx){ mn-=1; mx+=1; } const pd=(mx-mn)*0.08; mn-=pd; mx+=pd;
  const digits=spec.digits!=null?spec.digits:1;
  const W=520,H=210,L=46,R=12,T=14,B=28,pw=W-L-R,ph=H-T-B;
  const x0=num?xs[0]:0, x1=num?xs[n-1]:n-1;
  const X=i=>L+((n<=1||x1===x0)?pw/2:(((num?xs[i]:i)-x0)/(x1-x0))*pw), Y=v=>T+(1-(v-mn)/(mx-mn))*ph;
  const ticks=[mn,(mn+mx)/2,mx];
  const lblIdx=[]; let lastPx=-1e9; xs.forEach((_,i)=>{ if(X(i)-lastPx>=24||i===n-1&&X(i)-lastPx>=24){ lblIdx.push(i); lastPx=X(i); } });
  const ref=spec.ref?spec.ref(seasonalData(id,"all")):null;
  const mk=(p,cx,cy,k)=>{ // M270: distinct marker shape per cohort (accessibility)
    if(p.marker==="none") return null;
    if(p.marker==="square") return <rect key={k} x={cx-1.6} y={cy-1.6} width={3.2} height={3.2} fill={p.col}/>;
    if(p.marker==="diamond") return <rect key={k} x={cx-1.7} y={cy-1.7} width={3.4} height={3.4} fill={p.col} transform={`rotate(45 ${cx} ${cy})`}/>;
    return <circle key={k} cx={cx} cy={cy} r={1.6} fill={p.col}/>;
  };
  const anyFb=drawn.some(p=>p.fb.some(Boolean));
  return <><svg width="100%" viewBox={"0 0 "+W+" "+H} style={{maxWidth:W}} data-cmp-lines-x={num?"numeric":"ordinal"}>
    {ticks.map((t,i)=><g key={"t"+i}><line x1={L} x2={W-R} y1={Y(t)} y2={Y(t)} stroke="#eef2f7"/><text x={L-4} y={Y(t)+3} textAnchor="end" fontSize={8} fill="#94a3b8">{Number(t).toLocaleString(undefined,{maximumFractionDigits:digits})}</text></g>)}
    {lblIdx.map(i=><text key={"x"+i} x={X(i)} y={H-B+13} textAnchor="middle" fontSize={7.5} fill="#94a3b8">{String(xs[i])}</text>)}
    {spec.xtitle&&<text x={W-R} y={H-3} textAnchor="end" fontSize={7.5} fill="#94a3b8">{spec.xtitle}</text>}
    {ref&&(function(){ const inR=ref.y>=mn&&ref.y<=mx; const ry=Y(Math.max(mn,Math.min(mx,ref.y)));
      return <g data-cmp-ref="1"><line x1={L} x2={W-R} y1={ry} y2={ry} stroke="#94a3b8" strokeWidth={1} strokeDasharray="4 3"/>
        <text x={W-R-2} y={ry-3} textAnchor="end" fontSize={7.5} fill="#64748b">{ref.label+(inR?"":" — outside plotted range")}</text></g>; })()}
    {drawn.map((p,si)=>{ // M298 (audit 2026-09-24 §8): a null bin BREAKS the line into independent segments —
      // never join the remaining points across missing support; gaps get an open 'missing support' marker.
      const segs=[]; let cur=[];
      p.y.forEach((v,i)=>{ if(fin(v)) cur.push(X(i)+","+Y(v)); else { if(cur.length) segs.push(cur); cur=[]; } });
      if(cur.length) segs.push(cur);
      const gaps=p.y.map((v,i)=>fin(v)?null:i).filter(i=>i!=null&&i>0&&i<p.y.length-1&&p.y.slice(0,i).some(fin)&&p.y.slice(i+1).some(fin));
      return <g key={si} data-cmp-line-segments={segs.length}>{segs.map((sg,k)=>sg.length>1
          ?<polyline key={k} points={sg.join(" ")} fill="none" stroke={p.col} strokeWidth={p.width} strokeOpacity={0.95} strokeDasharray={p.dash}/>:null)}
        {p.y.map((v,i)=>fin(v)?mk(p,X(i),Y(v),i):null)}
        {p.y.map((v,i)=>(fin(v)&&p.fb[i])?<g key={"fb"+i} data-cmp-fallback-weight="1"><circle cx={X(i)} cy={Y(v)} r={3.4} fill="none" stroke={p.col}/><title>{p.label}: class weight missing at this x (fallback weight 1)</title></g>:null)}
        {gaps.map(i=><g key={"g"+i} data-missing-support="1"><circle cx={X(i)} cy={T+ph-4-si*5} r={2.2} fill="none" stroke={p.col} strokeDasharray="1 1"/><title>{p.label}: no support in this bin (gap, not interpolated)</title></g>)}</g>; })}
    {spec.unit&&<text x={L} y={10} fontSize={8} fill="#94a3b8">{spec.unit}</text>}
  </svg>
  {noObs.length>0&&<div style={{fontSize:9,color:"#94a3b8",marginTop:2}}>{noObs.map(p=>p.label).join(", ")}: no observations in this view (slot preserved, not blended into All).</div>}
  {anyFb&&<div style={{fontSize:9,color:"#94a3b8",marginTop:2}}>Open rings mark points where a class weight was missing (fallback weight 1).</div>}
  </>;
}
'''
s = s[:i] + new_lines + s[j:]

# ---- 4. CmpBars: only finite numbers count as observed ----
old = 'const present=per.map(p=>({p,c:p.cats.find(cc=>clsKey(cc)===rc.key)})).map(o=>({...o,v:(o.c&&o.c.value!=null)?o.c.value:null}));'
assert s.count(old) == 1
s = s.replace(old, 'const present=per.map(p=>({p,c:p.cats.find(cc=>clsKey(cc)===rc.key)})).map(o=>({...o,v:(o.c&&typeof o.c.value==="number"&&isFinite(o.c.value))?o.c.value:null})); // M348: null/NaN/non-numeric = not observed; an all-zero array is NOT reinterpreted')
open(P, 'w', encoding='utf-8', newline='').write(s)
print('patched')
