// M348 (audit F11): Compare 'lines' renderer parity tests (numeric x at true scale, outer join, canonical ordinal order,
// alias counted once, reference line separate, fallback-weight flag, not-observed rule for bars). jsdom on throw-away
// builds from mutated in-memory copies of summary_arrays.json (never written over the release artefacts).
// Usage: node test_compare_lines.js
const fs=require('fs'),cp=require('child_process'),path=require('path');
const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){
  globalThis.MessageChannel=class{constructor(){
    this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};
    this.port2={postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};}};
}
const TMP=process.env.XT_TMP||fs.mkdtempSync(path.join(require('os').tmpdir(),'xtcmpl-'));
const base=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));
const clone=o=>JSON.parse(JSON.stringify(o));
function variant(name,mut){
  const a=clone(base); mut(a);
  const ap=path.join(TMP,name+'.json'), hp=path.join(TMP,name+'.html');
  fs.writeFileSync(ap,JSON.stringify(a));
  const r=cp.spawnSync('node',['build_html.js'],{env:{...process.env,XT_ARRAYS:ap,XT_OUT:hp},encoding:'utf8'});
  if(r.status!==0){console.error('FAIL: fixture build '+name+' aborted\n'+r.stdout.slice(-600)+r.stderr.slice(-600));process.exit(1);}
  return hp;
}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function load(hp){
  const errors=[];
  const dom=new JSDOM(fs.readFileSync(hp,'utf8'),{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){
    w.MessageChannel=globalThis.MessageChannel;
    w.console.error=(...a)=>errors.push(a.map(String).join(' ').slice(0,240));w.console.warn=()=>{};
    w.addEventListener('error',e=>errors.push('window error: '+e.message));}});
  await sleep(800);
  const d=dom.window.document, click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
  return {d,click,errors,win:dom.window};
}
const TABS=['overview','charts','fuel','distribution','highway vs city','thermal','records','health','cross-vehicle','conclusions'];
const fails=[];const ok=(c,m)=>{if(!c)fails.push(m);else console.log('  ok:',m);};
const tabTo=async(P,t)=>{P.click([...P.d.querySelectorAll('button')].find(b=>b.textContent.trim().toLowerCase()===t));await sleep(220);};
const openAll=async(P)=>{for(const b of [...P.d.querySelectorAll('button')].filter(b=>!TABS.includes(b.textContent.trim().toLowerCase())&&!b.hasAttribute('data-cohort-btn')&&!b.hasAttribute('data-cmp-btn'))){try{P.click(b);}catch(e){} }await sleep(120);};
// Find the Compare frame whose title starts with `prefix` by scanning every tab in Compare mode.
async function frame(P,prefix){
  const find=()=>{ const f=[...P.d.querySelectorAll('div')].filter(x=>x.firstElementChild&&x.firstElementChild.firstElementChild&&x.firstElementChild.firstElementChild.textContent.startsWith(prefix)); return f.length?f[f.length-1]:null; };
  for(const t of TABS){
    await tabTo(P,t); const cb=P.d.querySelector('button[data-cohort-btn="compare"]'); if(cb){P.click(cb);await sleep(160);}
    let f=find(); if(f) return f;
    await openAll(P); f=find(); if(f) return f;
  }
  return null;
}
const polys=f=>[...f.querySelectorAll('polyline')].map(p=>p.getAttribute('points').trim().split(/\s+/).map(s=>s.split(',').map(Number)));
(async()=>{
  // ---------- A: real payload ----------
  console.log('A: real payload, Compare WarmupCurve / BatteryThermalCurve');
  const hpA=variant('A',()=>{});
  let P=await load(hpA);
  let f=await frame(P,'Coolant warm-up curve');
  ok(!!f,'A: Compare WarmupCurve frame found');
  if(f){
    ok(/n-weighted mean of per-class medians/.test(f.textContent),'A: title states n-weighted mean of per-class medians');
    ok(/weighted summary of class medians, not a pooled-sample median/i.test(f.textContent),'A: note states weighted summary, not a pooled-sample median');
    const svg=f.querySelector('svg'); ok(svg&&svg.getAttribute('data-cmp-lines-x')==='numeric','A: numeric x axis');
    const grid=base.seasonalCharts.charts.WarmupCurve.data.all.grid;
    const pl=polys(f).filter(p=>p.length===grid.length);
    ok(pl.length>=1,'A: full-length polyline present ('+pl.length+')');
    if(pl.length){ const xs=pl[0].map(p=>p[0]); const w=xs[xs.length-1]-xs[0]; let md=0; grid.forEach((km,i)=>{md=Math.max(md,Math.abs((xs[i]-xs[0])/w-(km-grid[0])/(grid[grid.length-1]-grid[0])));});
      ok(md<1e-3,'A: x positions proportional to km (max deviation '+md.toExponential(2)+')');
      // rendered y values are an affine image of the canonical-only pooled values (script-written in the check JSON)
      const chk=JSON.parse(fs.readFileSync('analyses/M348_warmup_pool_check.json','utf8')).cohorts;
      const fit=(ys,vs)=>{ const n=vs.length, mv=vs.reduce((a,b)=>a+b,0)/n, my=ys.reduce((a,b)=>a+b,0)/n; let sxy=0,sxx=0; vs.forEach((v,i)=>{sxy+=(v-mv)*(ys[i]-my);sxx+=(v-mv)**2;}); const b=sxy/sxx, a0=my-b*mv; return {b,res:Math.max(...vs.map((v,i)=>Math.abs(a0+b*v-ys[i])))}; };
      pl.forEach((q,k)=>{ const ys=q.map(p=>p[1]); const best=Object.keys(chk).map(c=>({c,f:fit(ys,chk[c].canonicalOnly)})).sort((u,v)=>u.f.res-v.f.res)[0];
        ok(best.f.b<0&&best.f.res<1e-6,'A: rendered polyline '+k+' = affine image of the canonical-only pooled values of cohort '+best.c+' (max residual '+best.f.res.toExponential(2)+' px)');
        const old=fit(ys,chk[best.c].asRendered); if(best.c!=='shoulder') ok(old.res>1e-3,'A: and not of the old alias-double-counted values (residual '+old.res.toFixed(3)+' px)'); }); }
    ok(f.querySelectorAll('[data-cmp-ref]').length===1,'A: exactly one reference line');
    ok(/reference level 80 .C \(not observed data\)/.test(f.textContent),'A: reference label reads as reference, not a cohort');
    ok(!f.querySelector('[data-cmp-fallback-weight]'),'A: no fallback-weight points on the real payload');
  }
  let g=await frame(P,'Battery pack temperature vs minutes');
  if(g){ const ps=polys(g).sort((a,b)=>b.length-a.length);
    ok(ps.length>=2&&ps[0].length===19&&ps[ps.length-1].length===6,'A: BatteryThermalCurve series of 19 and 6 points');
    if(ps.length>=2){ const lo=ps[ps.length-1], hi=ps[0]; const span=hi[hi.length-1][0]-hi[0][0];
      ok(Math.abs((lo[lo.length-1][0]-lo[0][0])/span-50/180)<1e-3,'A: shorter series ends at its own x (50/180 of the axis), not stretched'); } }
  else fails.push('A: BatteryThermalCurve frame not found');
  ok(P.errors.length===0,'A: no console errors');
  P.win.close();

  // ---------- B: alias double count ----------
  console.log('B: alias city removed -> identical pooled curve');
  const rend=async hp=>{ const Q=await load(hp); const ff=await frame(Q,'Coolant warm-up curve'); const out=ff?JSON.stringify(polys(ff)):null; Q.win.close(); return out; };
  const withAlias=await rend(hpA);
  const hpB=variant('B',a=>{ for(const c of Object.keys(a.seasonalCharts.charts.WarmupCurve.data)){ const d=a.seasonalCharts.charts.WarmupCurve.data[c]; if(d&&d.classes) delete d.classes.city; } });
  const noAlias=await rend(hpB);
  ok(withAlias&&withAlias===noAlias,'B: rendered pooled curve identical with and without the legacy city alias');

  // ---------- C: fallback weight ----------
  console.log('C: class weight missing -> fallback flag');
  const hpC=variant('C',a=>{ const d=a.seasonalCharts.charts.WarmupCurve.data.warm; d.classes.urban.points[3].n=null; d.classes.city.points[3].n=null; });
  P=await load(hpC); f=await frame(P,'Coolant warm-up curve');
  ok(f&&f.querySelectorAll('[data-cmp-fallback-weight]').length>=1,'C: fallback-weight ring flagged'); ok(f&&/fallback weight 1/.test(f.textContent),'C: legend text states fallback weight 1');
  P.win.close();

  // ---------- D: ordinal bins, different subsets ----------
  console.log('D: ordinal union keeps the All payload order; missing bin = gap');
  const hpD=variant('D',a=>{ const d=a.seasonalCharts.charts.RpmDistribution.data.shoulder; d.bins.splice(1,1); d.pooledPct.splice(1,1);
    const t=a.seasonalCharts.charts.TorqueBySpeed.data.shoulder; t.splice(3,1); });
  P=await load(hpD); f=await frame(P,'Engine-on RPM time distribution');
  if(f){ const allBins=base.seasonalCharts.charts.RpmDistribution.data.all.bins; const labs=[...f.querySelectorAll('svg text')].map(t=>t.textContent).filter(t=>allBins.includes(t));
    const exp=allBins.filter(b=>labs.includes(b)); ok(labs.length>=6&&JSON.stringify(labs)===JSON.stringify(exp),'D: bin labels follow the All order ('+labs.length+' shown)');
    ok(f.querySelector('[data-missing-support]'),'D: missing bin in Shoulder drawn as a gap marker'); } else fails.push('D: RpmDistribution frame not found');
  g=await frame(P,'Cruise torque vs speed'); ok(g&&g.querySelector('[data-missing-support]'),'D: TorqueBySpeed Shoulder missing band drawn as a gap');
  ok(P.errors.length===0,'D: no console errors'); P.win.close();

  // ---------- E: not-observed rule for bars ----------
  console.log('E: all-zero array stays a zero bar; empty/NaN array is not observed');
  const hpE=variant('E',a=>{ const sd=a.seasonalCharts.charts.SpeedDist.data; sd.shoulder.overall=sd.shoulder.overall.map(()=>0); });
  P=await load(hpE); f=await frame(P,'Time-in-speed distribution');
  ok(f&&!f.querySelector('[data-not-observed]'),'E: all-zero SpeedDist Shoulder (no count field) is NOT hatched (listed in the check JSON, unresolved)'); P.win.close();
  const hpE2=variant('E2',a=>{ const sd=a.seasonalCharts.charts.SpeedDist.data; sd.shoulder.overall=sd.shoulder.overall.map(()=>null); });
  P=await load(hpE2); f=await frame(P,'Time-in-speed distribution');
  ok(f&&f.querySelector('[data-not-observed]'),'E2: null array renders hatched not-observed'); ok(P.errors.length===0,'E2: no console errors'); P.win.close();

  fails.forEach(x=>console.log('  FAIL:',x));
  if(!process.env.XT_TMP) fs.rmSync(TMP,{recursive:true,force:true});
  if(fails.length){console.error('COMPARE-LINES TEST FAILED ('+fails.length+')');process.exit(1);}
  console.log('COMPARE-LINES TEST PASSED');process.exit(0);
})();
