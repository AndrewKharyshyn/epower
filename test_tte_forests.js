// test_tte_forests.js (M654, UI-05, spec analyses/M654_spec.md Rev 1): renders xtrail_dashboard.html in jsdom, opens the Distribution tab and checks that the fill-sensitivity, longer-fill and start-temperature-tercile
// tables are each preceded by a forest (IntervalForest) inside ChartWithTable, that the forest rows are exactly two per setting (observed share, Kaplan-Meier (product-limit) estimate), that every plotted value
// is the ledger value the table prints (3 dp), that an unsupported row is text and not a zero, and that the table stays behind the details toggle.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};this.port2={postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))}}}}
const html=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));
let fails=0;const ok=(label,c)=>{console.log((c?'PASS ':'FAIL ')+label);if(!c)fails++;};
const dom=new JSDOM(html,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=()=>{};w.console.warn=()=>{}}});
const d=dom.window.document,sleep=ms=>new Promise(r=>setTimeout(r,ms)),click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const T=A.thermalSupportLedger.timeToThreshold;
const f3=v=>Number(v).toFixed(3);
(async()=>{
  await sleep(1000);
  click([...d.querySelectorAll('button')].find(b=>b.textContent.trim().toLowerCase()==='distribution'));await sleep(500);
  const check=(sel,label,expected)=>{
    const host=d.querySelector(sel); ok(label+': block present',!!host); if(!host) return;
    const cw=host.querySelector('[data-chart-with-table]'); ok(label+': forest inside ChartWithTable',!!cw&&!!cw.querySelector('[data-interval-forest]'));
    const rows=cw?[...cw.querySelectorAll('[data-forest-row]')]:[]; ok(label+': two forest rows per setting ('+expected.length*2+')',rows.length===expected.length*2);
    ok(label+': table stays behind the details toggle',!!cw&&!!cw.querySelector('details table'));
    expected.forEach((e,i)=>{ const a=rows[2*i],b=rows[2*i+1]; if(!a||!b) return;
      if(e.supported){ ok(label+' row '+i+': values equal the ledger',a.textContent.includes(f3(e.E1.point))&&a.textContent.includes(f3(e.E1.ci95[0]))&&a.textContent.includes(f3(e.E1.ci95[1]))&&b.textContent.includes(f3(e.E2.point))&&b.textContent.includes(f3(e.E2.ci95[1]))&&a.getAttribute('data-forest-row')==='interval'); }
      else ok(label+' row '+i+': unsupported is text, not a point',a.getAttribute('data-forest-row')==='none'&&a.textContent.includes('not supported')); });
  };
  const FS=T.fillSensitivity; if(FS){ const ex=[]; FS.headlineCells.forEach(k=>FS.fills.forEach(F=>{ const r=FS.settings[String(F)][k]; if(r) ex.push({supported:r.supported600,E1:r.E1,E2:r.E2}); })); check('[data-m437="fill"]','fill sensitivity',ex); }
  const EF=FS&&FS.extendedFills; if(EF){ const ex=[]; EF.headlineCells.forEach(k=>EF.fills.forEach(F=>{ const r=EF.settings[String(F)][k]; if(r) ex.push({supported:r.supported600,E1:r.E1,E2:r.E2}); })); check('[data-m648="extended-fills"]','longer fills',ex); }
  const SS=T.startStrata; if(SS){ SS.headlineCells.forEach(k=>{ const ex=SS.cells[k].strata.map(s=>{ const r=s.horizons.find(x=>x.h===SS.headlineH); return {supported:!!(r&&r.supported&&r.E1),E1:r&&r.E1,E2:r&&r.E2}; }); check('[data-m438-cell="'+k+'"]','terciles '+k,ex); }); }
  console.log(fails?'FAILED '+fails:'ALL PASS'); process.exit(fails?1:0);
})();
