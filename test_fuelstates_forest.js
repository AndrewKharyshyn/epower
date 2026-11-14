// test_fuelstates_forest.js (M661, UI-05, spec analyses/M661_spec.md): the Fuel tab "Fuel by speed state" panel shows a forest of the stationary share per group
// (value and interval equal S.fuelStates.groups at 2 dp), inside ChartWithTable with the unchanged table behind the toggle.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};this.port2={postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))}}}}
const html=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));
let fails=0;const ok=(label,c)=>{console.log((c?'PASS ':'FAIL ')+label);if(!c)fails++;};
const dom=new JSDOM(html,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=()=>{};w.console.warn=()=>{}}});
const d=dom.window.document,sleep=ms=>new Promise(r=>setTimeout(r,ms)),click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const G=A.fuelStates.groups, f2=v=>Number(v*100).toFixed(2);
const keys=['all','band 0.5-2','band 2-5','band 5-10','band 10-20','band 20+'].concat(Object.keys(G).filter(k=>k.startsWith('driveType')||k.startsWith('cohort'))).filter(k=>G[k]);
(async()=>{
  await sleep(1000);
  click([...d.querySelectorAll('button')].find(b=>b.textContent.trim().toLowerCase()==='fuel'));await sleep(500);
  const host=d.querySelector('[data-fuel-states-forest]'); ok('forest present',!!host); if(!host){process.exit(1);}
  const cw=host.closest('[data-chart-with-table]'); ok('inside ChartWithTable with the table behind the toggle',!!cw&&!!cw.querySelector('details table'));
  const rows=[...host.querySelectorAll('[data-forest-row]')]; ok('one row per group ('+keys.length+')',rows.length===keys.length);
  keys.forEach((k,i)=>{ const s=G[k].stationaryShare, r=rows[i]; if(!r) return;
    ok(k+': value'+(s.ci95?' and interval':'')+' equal the payload',r.textContent.includes(f2(s.est))&&(!s.ci95||(r.textContent.includes(f2(s.ci95[0]))&&r.textContent.includes(f2(s.ci95[1]))))&&r.textContent.includes(G[k].nTrips+' trips')); });
  console.log(fails?'FAILED '+fails:'ALL PASS'); process.exit(fails?1:0);
})();
