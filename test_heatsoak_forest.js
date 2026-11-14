// test_heatsoak_forest.js (M659, UI-05, spec analyses/M659_spec.md): the heat-soak carryover panel shows a forest of the median retained share per gap bin
// (value equals 100 x medRetainedFrac, n in the label), inside ChartWithTable with the unchanged listing behind the toggle; a bin without a ratio is text, not zero.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};this.port2={postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))}}}}
const html=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));
let fails=0;const ok=(label,c)=>{console.log((c?'PASS ':'FAIL ')+label);if(!c)fails++;};
const dom=new JSDOM(html,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=()=>{};w.console.warn=()=>{}}});
const d=dom.window.document,sleep=ms=>new Promise(r=>setTimeout(r,ms)),click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const bins=A.heatSoakCarryover.gapBins;
(async()=>{
  await sleep(1000);
  click([...d.querySelectorAll('button')].find(b=>b.textContent.trim().toLowerCase()==='thermal'));await sleep(500);
  const host=d.querySelector('[data-heatsoak-forest]'); ok('forest block present',!!host); if(!host){process.exit(1);}
  const cw=host.closest('[data-chart-with-table]'); ok('inside ChartWithTable with the listing behind the toggle',!!cw&&!!cw.querySelector('details')&&cw.querySelector('details').textContent.includes('sheds'));
  const rows=[...host.querySelectorAll('[data-forest-row]')]; ok('one row per gap bin ('+bins.length+')',rows.length===bins.length);
  bins.forEach((b,i)=>{ const r=rows[i]; if(!r) return;
    if(typeof b.medRetainedFrac==='number') ok('bin '+i+': value and n equal the payload',r.getAttribute('data-forest-row')!=='none'&&r.textContent.includes(String(Math.round(b.medRetainedFrac*100)))&&r.textContent.includes(b.n+' pairs'));
    else ok('bin '+i+': no ratio is text',r.getAttribute('data-forest-row')==='none'); });
  console.log(fails?'FAILED '+fails:'ALL PASS'); process.exit(fails?1:0);
})();
