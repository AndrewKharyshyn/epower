// test_soakheldout_chart.js (M665, UI-05, spec analyses/M665_spec.md): the heat-soak held-out fit-quality block draws, for pack, coolant and oil, the median observed and model-predicted retained
// fraction per parking-gap bin (open points, no interval), every plotted value equals the payload bin at 2 dp, bin table (with held-out pairs and days) behind ChartWithTable.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};this.port2={postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))}}}}
const html=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));
let fails=0;const ok=(label,c)=>{console.log((c?'PASS ':'FAIL ')+label);if(!c)fails++;};
const dom=new JSDOM(html,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=()=>{};w.console.warn=()=>{}}});
const d=dom.window.document,sleep=ms=>new Promise(r=>setTimeout(r,ms)),click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const TD=A.interDriveCarryover.thermalDecay, fits=[['Pack',A.heatSoakCarryover.soakFitQuality],['Coolant',TD.coolant.fitQuality],['Oil',TD.oil.fitQuality]], f2=v=>Number(v).toFixed(2);
(async()=>{
  await sleep(1000);
  let host=null;
  for(const nm of ['thermal','health','overview','charts','distribution','records','conclusions']){ const b=[...d.querySelectorAll('button')].find(x=>x.textContent.trim().toLowerCase()===nm); if(!b) continue; click(b); await sleep(300); host=d.querySelector('[data-soak-heldout-chart]'); if(host) break; }
  ok('chart block present',!!host); if(!host){process.exit(1);}
  const cw=host.closest('[data-chart-with-table]'); ok('bin table behind the toggle',!!cw&&!!cw.querySelector('details table'));
  const charts=[...host.querySelectorAll('[data-band-series]')]; ok('three charts (pack, coolant, oil)',charts.length===3);
  ok('no interval drawn',host.querySelectorAll('[data-band-point="interval"]').length===0);
  fits.forEach(([name,q],fi)=>{ const bs=(q.bins||[]).filter(b=>b.nPairs>0), titles=charts[fi]?[...charts[fi].querySelectorAll('[data-band-point] title')].map(t=>t.textContent):[];
    ok(name+': '+bs.length+' bins x 2 series plotted',titles.length===2*bs.length);
    bs.forEach(b=>{ const xl=b.bin.replace(' h',''); ok(name+' '+b.bin+': observed and predicted equal the payload',titles.some(t=>t.startsWith('observed, '+xl+': '+f2(b.medianObservedRetained)))&&titles.some(t=>t.startsWith('predicted, '+xl+': '+f2(b.medianPredictedRetained)))); }); });
  const rows=cw.querySelectorAll('details tbody tr'); ok('table has one row per bin and fit ('+fits.reduce((a,[,q])=>a+q.bins.filter(b=>b.nPairs>0).length,0)+')',rows.length===fits.reduce((a,[,q])=>a+q.bins.filter(b=>b.nPairs>0).length,0));
  console.log(fails?'FAILED '+fails:'ALL PASS'); process.exit(fails?1:0);
})();
