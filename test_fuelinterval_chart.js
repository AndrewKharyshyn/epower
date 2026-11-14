// test_fuelinterval_chart.js (M660, UI-05, spec analyses/M660_spec.md): the Fuel tab warm-up panel shows the moving-sample L/100 km per 0.5 km interval as a BandSeries
// (one series per initial-coolant band, every plotted value and interval equals the payload at 1 dp, an interval without a CI is an open point), table behind ChartWithTable.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};this.port2={postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))}}}}
const html=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));
let fails=0;const ok=(label,c)=>{console.log((c?'PASS ':'FAIL ')+label);if(!c)fails++;};
const dom=new JSDOM(html,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=()=>{};w.console.warn=()=>{}}});
const d=dom.window.document,sleep=ms=>new Promise(r=>setTimeout(r,ms)),click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const Z=A.fuelWarmup, bands=Object.keys(Z.bands).filter(b=>b!=='oil-fallback'), f1=v=>Number(v).toFixed(1);
(async()=>{
  await sleep(1000);
  click([...d.querySelectorAll('button')].find(b=>b.textContent.trim().toLowerCase()==='fuel'));await sleep(500);
  const host=d.querySelector('[data-fuel-interval-chart]'); ok('interval chart present',!!host); if(!host){process.exit(1);}
  const cw=host.closest('[data-chart-with-table]'); ok('inside ChartWithTable with the table behind the toggle',!!cw&&!!cw.querySelector('details table'));
  const titles=[...host.querySelectorAll('[data-band-point] title')].map(t=>t.textContent);
  let exp=0;
  bands.forEach(b=>Z.groups['all|'+b].intervalConsumption.forEach(e=>{ if(e.est==null) return; exp++;
    const key=Z.bands[b]+', '+e.fromKm+': '+f1(e.est); const t=titles.find(x=>x.startsWith(key));
    ok(b+' '+e.fromKm+' km: value'+(e.ci95?' and interval':' (points only)')+' equal the payload',!!t&&(e.ci95?t.includes('('+f1(e.ci95[0])+', '+f1(e.ci95[1])+')'):!t.includes('(')));
  }));
  ok('point count equals payload ('+exp+')',titles.length===exp);
  console.log(fails?'FAILED '+fails:'ALL PASS'); process.exit(fails?1:0);
})();
