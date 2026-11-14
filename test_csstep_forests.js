// test_csstep_forests.js (M656, UI-05, spec analyses/M656_spec.md Rev 1): renders xtrail_dashboard.html in jsdom, opens the Health tab and checks that the cell-spread step-sensitivity panel shows two forests
// (months slope per model, level step per model) inside ChartWithTable in front of the unchanged model table, that each plotted value equals the payload value the table prints (2 dp), that the model without
// a months term is text and not a zero, and that the table stays behind the details toggle.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};this.port2={postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))}}}}
const html=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));
let fails=0;const ok=(label,c)=>{console.log((c?'PASS ':'FAIL ')+label);if(!c)fails++;};
const dom=new JSDOM(html,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=()=>{};w.console.warn=()=>{}}});
const d=dom.window.document,sleep=ms=>new Promise(r=>setTimeout(r,ms)),click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const B=A.cellSpreadStep, f2=v=>Number(v).toFixed(2);
const ORDER=['M0_linear_released','M1_linear_soc','M2_linear_soc_rest','M3_step','M4_step_soc','M5_step_soc_rest','M6_month_fixed_effects'].filter(k=>B.models[k]);
(async()=>{
  await sleep(1000);
  click([...d.querySelectorAll('button')].find(b=>b.textContent.trim().toLowerCase()==='health'));await sleep(500);
  const host=d.querySelector('[data-csstep-forests]'); ok('forest block present',!!host); if(!host){process.exit(1);}
  const cw=host.closest('[data-chart-with-table]'); ok('inside ChartWithTable with the table behind the toggle',!!cw&&!!cw.querySelector('details table'));
  const forests=[...host.querySelectorAll('[data-interval-forest]')]; ok('two forests',forests.length===2);
  const r1=[...forests[0].querySelectorAll('[data-forest-row]')], r2=[...forests[1].querySelectorAll('[data-forest-row]')];
  ok('months-slope forest has one row per model ('+ORDER.length+')',r1.length===ORDER.length);
  ORDER.forEach((k,i)=>{ const m=B.models[k], r=r1[i]; if(!r) return;
    if(m.est==null) ok(k+': no months term is text, not a point',r.getAttribute('data-forest-row')==='none'&&r.textContent.includes('no months term'));
    else ok(k+': months slope and interval equal the payload',r.getAttribute('data-forest-row')==='interval'&&r.textContent.includes(f2(m.est))&&r.textContent.includes(f2(m.ci95[0]))&&r.textContent.includes(f2(m.ci95[1]))); });
  const withStep=ORDER.filter(k=>B.models[k].step_term);
  ok('level-step forest has one row per step model ('+withStep.length+')',r2.length===withStep.length);
  withStep.forEach((k,i)=>{ const t=B.models[k].step_term, r=r2[i]; if(!r) return; ok(k+': level step and interval equal the payload',r.textContent.includes(f2(t.est))&&r.textContent.includes(f2(t.ci95[0]))&&r.textContent.includes(f2(t.ci95[1]))); });
  console.log(fails?'FAILED '+fails:'ALL PASS'); process.exit(fails?1:0);
})();
