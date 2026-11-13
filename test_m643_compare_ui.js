// M643 (UI-07 / UI-02 / UI-03): Compare mode. (1) the legacy regen dot plots draw no grey connector between cohorts while another Compare chart keeps it (owner decision D-06);
// (2) ComparisonCube and RegenCompareV2 follow the Compare filter bar (toggling Shoulder off removes its column); (3) every rpm distribution chart states its basis.
// jsdom on xtrail_dashboard.html. Usage: node test_m643_compare_ui.js
const fs=require('fs');
const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){
  globalThis.MessageChannel=class{constructor(){
    this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};
    this.port2={postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};}};
}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const fails=[]; const ok=(c,m)=>{ if(!c) fails.push(m); else console.log('  ok:',m); };
(async()=>{
  const errors=[];
  const dom=new JSDOM(fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8'),{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){
    w.MessageChannel=globalThis.MessageChannel; w.console.error=(...a)=>errors.push(a.map(String).join(' ').slice(0,240)); w.console.warn=()=>{};}});
  await sleep(900);
  const d=dom.window.document, click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
  const tab=async t=>{ click([...d.querySelectorAll('button')].find(b=>b.textContent.trim().toLowerCase()===t)); await sleep(300); };
  const compare=async()=>{ const cb=d.querySelector('button[data-cohort-btn="compare"]'); if(cb){ click(cb); await sleep(250); } };
  const toggle=async k=>{ click(d.querySelector('button[data-cmp-btn="'+k+'"]')); await sleep(250); };
  // (1) regen: no connector in the legacy regen bars; the rest of Compare keeps it
  await tab('charts'); await compare();
  const regenSection=[...d.querySelectorAll('div')].find(x=>x.getAttribute&&x.getAttribute('data-regen-note')==='compare');
  ok(!!regenSection,'regen Compare section present');
  const allConn=d.querySelectorAll('line[data-cmp-connector="1"]');
  const regenRoot=regenSection?regenSection.parentElement:null;
  ok(regenRoot&&regenRoot.querySelectorAll('line[data-cmp-connector="1"]').length===0,'regen legacy dot plots draw no connector');
  ok(regenRoot&&regenRoot.querySelectorAll('svg').length>0,'regen legacy charts still render');
  let others=allConn.length;
  for(const t of ['distribution','highway vs city','thermal','fuel']){ await tab(t); await compare(); others+=d.querySelectorAll('line[data-cmp-connector="1"]').length; }
  ok(others>0,'other Compare dot plots keep their connector ('+others+')');
  // (2) filter bar drives the typed cube and the regen v2 table
  await tab('highway vs city'); await compare();
  const cols=()=>[...d.querySelectorAll('[data-comparison-cube="1"] thead th')].map(x=>x.textContent.toLowerCase());
  ok(cols().some(c=>c.includes('shoulder')),'cube shows a Shoulder column by default');
  await toggle('shoulder');
  ok(!cols().some(c=>c.includes('shoulder')),'cube: Shoulder off removes the Shoulder column');
  await toggle('shoulder');
  ok(cols().some(c=>c.includes('shoulder')),'cube: Shoulder on restores it');
  await tab('charts'); await compare();
  const rh=()=>[...d.querySelectorAll('[data-regen-compare-table] thead th')].map(x=>x.textContent);
  ok(rh().includes('Shoulder'),'regen v2 table shows Shoulder by default');
  await toggle('shoulder');
  ok(!rh().includes('Shoulder')&&rh().includes('Warm'),'regen v2 table: Shoulder off removes the column');
  await toggle('shoulder');
  // (3) rpm basis: the single-cohort chart carries the basis line; the Compare chart carries it in its title
  await tab('highway vs city');
  const TABS=['overview','charts','fuel','distribution','highway vs city','thermal','records','health','cross-vehicle','conclusions'];
  const expand=async()=>{ for(const b of [...d.querySelectorAll('button')].filter(b=>!TABS.includes(b.textContent.trim().toLowerCase())&&!b.hasAttribute('data-cohort-btn')&&!b.hasAttribute('data-cmp-btn')&&/▸|▶|show|expand|more|details/i.test(b.textContent)).slice(0,150)){ click(b); await sleep(3); } await sleep(150); };
  click(d.querySelector('button[data-cohort-btn="all"]')); await sleep(200); await expand();
  ok(d.querySelectorAll('[data-rpm-basis="ge300"]').length>0,'single-cohort rpm chart states its basis');
  await compare(); await expand();
  ok(/rpm ≥ 300 basis/.test(d.getElementById('root').textContent),'Compare rpm chart states its basis in the title');
  ok(errors.length===0,'no console errors '+errors.slice(0,2).join(' | '));
  if(fails.length){ console.error('FAIL:\n  '+fails.join('\n  ')); process.exit(1); }
  console.log('PASS test_m643_compare_ui');
  process.exit(0);
})();
