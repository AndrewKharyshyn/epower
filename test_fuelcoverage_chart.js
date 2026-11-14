// test_fuelcoverage_chart.js (M664, UI-05, spec analyses/M664_spec.md): the Fuel-tab banner draws the share of files with fuel columns and with a usable rate and counter per month
// (two series, every plotted share equals the payload count ratio at 2 dp, open points only), month table behind ChartWithTable.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};this.port2={postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))}}}}
const html=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));
let fails=0;const ok=(label,c)=>{console.log((c?'PASS ':'FAIL ')+label);if(!c)fails++;};
const dom=new JSDOM(html,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=()=>{};w.console.warn=()=>{}}});
const d=dom.window.document,sleep=ms=>new Promise(r=>setTimeout(r,ms)),click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const mo=A.fuelContract.coverage.byMonth, months=Object.keys(mo).sort().filter(m=>mo[m].files>0), f2=v=>Number(v).toFixed(2);
(async()=>{
  await sleep(1000);
  click([...d.querySelectorAll('button')].find(b=>b.textContent.trim().toLowerCase()==='fuel'));await sleep(500);
  const host=d.querySelector('[data-fuel-coverage-chart]'); ok('coverage chart present',!!host); if(!host){process.exit(1);}
  const cw=host.closest('[data-chart-with-table]'); ok('month table behind the toggle',!!cw&&!!cw.querySelector('details table'));
  const titles=[...host.querySelectorAll('[data-band-point] title')].map(t=>t.textContent);
  ok('two series x '+months.length+' months of points',titles.length===2*months.length);
  ok('no interval is drawn (open points only)',host.querySelectorAll('[data-band-point="interval"]').length===0);
  months.forEach(m=>{ ok(m+': shares equal the payload ('+mo[m].withFuelColumns+'/'+mo[m].files+', '+mo[m].usableBoth+'/'+mo[m].files+')',
    titles.some(t=>t.startsWith('with fuel columns, '+m+': '+f2(mo[m].withFuelColumns/mo[m].files)))&&titles.some(t=>t.startsWith('usable rate and counter, '+m+': '+f2(mo[m].usableBoth/mo[m].files)))); });
  console.log(fails?'FAILED '+fails:'ALL PASS'); process.exit(fails?1:0);
})();
