// M284 (audit #7): synthetic Cold-cohort INTEGRATION fixture test.
// The release corpus has 0 cold drives, so the Cold code path (selector enablement, Compare
// series, per-chart cold payload reads, minimum-support rule, no-silent-fallback) is otherwise
// never exercised until winter data arrives. This script builds throw-away dashboards from
// mutated in-memory copies of summary_arrays.json (never written over the release artefacts)
// and drives them with jsdom:
//   A  cold n=12 (>= min support) + cold payload cloned from Shoulder  -> Cold ENABLED, renders, Compare 3 series
//   B  cold n=3  (<  min support)                                       -> Cold DISABLED
//   C  warm payload deleted for one chart                               -> explicit no-data notice, NO silent All-data fallback
// Usage: node test_cold_fixture.js   (run after build_html.js prerequisites are installed)
const fs=require('fs'),cp=require('child_process'),path=require('path');
const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){
  globalThis.MessageChannel=class{constructor(){
    this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};
    this.port2={postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};}};
}
const TMP=process.env.XT_TMP||fs.mkdtempSync(path.join(require('os').tmpdir(),'xtcold-'));
const base=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));
const MIN=(fs.readFileSync('xtrail_summary.jsx','utf8').match(/COHORT_MIN_SUPPORT_DRIVES\s*=\s*(\d+)/)||[])[1]|0;
if(!MIN){console.error('FAIL: COHORT_MIN_SUPPORT_DRIVES not declared in JSX');process.exit(1);}
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
  return {d,click,errors,txt:()=>d.getElementById('root').textContent,win:dom.window};
}
const TABS=['overview','charts','fuel','distribution','highway vs city','thermal','records','health','cross-vehicle','conclusions'];
const fails=[];const ok=(c,m)=>{if(!c)fails.push(m);else console.log('  ok:',m);};
const btn=(P,m)=>P.d.querySelector(`button[data-cohort-btn="${m}"]`);
const openAll=async(P)=>{for(const b of [...P.d.querySelectorAll('button')].filter(b=>!TABS.includes(b.textContent.trim().toLowerCase())&&!b.hasAttribute('data-cohort-btn')&&!b.hasAttribute('data-cmp-btn')).slice(0,200)){P.click(b);await sleep(4);}await sleep(150);};
const tabTo=async(P,t)=>{P.click([...P.d.querySelectorAll('button')].find(b=>b.textContent.trim().toLowerCase()===t));await sleep(220);};

(async()=>{
  // ---------- A ----------
  console.log('A: cold n=%d (>= min %d), payload cloned from Shoulder',MIN+2,MIN);
  const hpA=variant('A',a=>{
    const sc=a.seasonalCharts; sc._meta.cohortCounts.cold=MIN+2; sc._meta.cohortCounts.all=(sc._meta.cohortCounts.all||0);
    for(const id of Object.keys(sc.charts)){const dd=sc.charts[id].data; if(dd.shoulder!=null) dd.cold=clone(dd.shoulder);}
    if(a.cohortMeta&&a.cohortMeta.shoulder){ a.cohortMeta.cold=clone(a.cohortMeta.shoulder); Object.assign(a.cohortMeta.cold,{n:MIN+2,observed:MIN+2,eligibleForCohortView:MIN+2,inferenceAvailable:true,nDaysObserved:3}); }
  });
  let P=await load(hpA);
  ok(btn(P,'cold')&&!btn(P,'cold').disabled,'A: Cold selector button ENABLED at n>=min support');
  for(const t of TABS){
    await tabTo(P,t); await openAll(P);
    for(const m of ['cold','compare','warm','shoulder','all']){
      const b=btn(P,m); if(!b||b.disabled){fails.push(`A: ${t}/${m} button missing/disabled`);continue;}
      const e0=P.errors.length; P.click(b); await sleep(160);
      if(P.errors.length>e0) fails.push(`A: console error on ${t}/${m}: ${P.errors[e0]}`);
      if(m==='cold'){
        ok(!P.d.querySelector('[data-cold-nodata]'),`A: ${t}/cold renders payloads (no no-data notice)`);
        const badges=P.d.querySelectorAll('[data-allref-badge]').length;
        if(t==='conclusions') ok(badges>0,`A: conclusions/cold shows All-data-reference badges (${badges})`);
      }
    }
  }
  // Compare with Cold toggled on
  await tabTo(P,'charts'); P.click(btn(P,'compare')); await sleep(200);
  const cmpCold=P.d.querySelector('button[data-cmp-btn="cold"]');
  ok(cmpCold&&!cmpCold.disabled,'A: Compare Cold button ENABLED');
  const e1=P.errors.length; if(cmpCold){P.click(cmpCold);await sleep(250);}
  ok(cmpCold&&cmpCold.getAttribute('aria-pressed')==='true','A: Compare Cold toggles on');
  const allB=P.d.querySelector('button[data-cmp-btn="all"]'); if(allB){P.click(allB);await sleep(250);}
  ok(allB&&allB.getAttribute('aria-pressed')==='true','A: Compare All Data = aggregate of warm+shoulder+cold');
  ok(P.errors.length===e1,'A: Compare with 3 cohorts + All renders without console errors');
  P.win.close();

  // ---------- B ----------
  console.log('B: cold n=%d (< min %d)',MIN-7>0?MIN-7:1,MIN);
  const hpB=variant('B',a=>{a.seasonalCharts._meta.cohortCounts.cold=Math.max(1,MIN-7);});
  P=await load(hpB);
  ok(btn(P,'cold')&&btn(P,'cold').disabled,'B: Cold selector DISABLED below minimum support');
  P.click(btn(P,'compare')); await sleep(200);
  const cB=P.d.querySelector('button[data-cmp-btn="cold"]'); ok(cB&&cB.disabled,'B: Compare Cold DISABLED below minimum support');
  P.win.close();

  // ---------- C ----------
  console.log('C: warm payload removed for EfficiencyBands (missing cohort payload)');
  const hpC=variant('C',a=>{delete a.seasonalCharts.charts.EfficiencyBands.data.warm;});
  P=await load(hpC);
  await tabTo(P,'overview'); await openAll(P);
  P.click(btn(P,'warm')); await sleep(250);
  const nd=P.d.querySelector('[data-cold-nodata][data-nodata-cohort="warm"]');
  ok(!!nd,'C: missing Warm payload -> explicit no-data notice (no silent All-data fallback)');
  ok(nd&&/not substituted/.test(nd.textContent),'C: notice states all-data is not substituted');
  ok(P.errors.length===0,'C: no console errors');
  P.win.close();

  fails.forEach(f=>console.log('  FAIL:',f));
  if(!process.env.XT_TMP) fs.rmSync(TMP,{recursive:true,force:true});
  if(fails.length){console.error('COLD-FIXTURE TEST FAILED ('+fails.length+')');process.exit(1);}
  console.log('COLD-FIXTURE TEST PASSED');process.exit(0);
})();
