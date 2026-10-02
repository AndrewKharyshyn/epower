// test_fuel_tab.js (M334, spec analyses/M334_spec.md rev 2): the Fuel tab (owner decision O1) in jsdom.
// T1 tab exists and hosts the banner + the three fuel views; they are gone from Charts/Distribution; EnergyArchitecture stays in Charts and links to Fuel.
// T2 cohort selection persists into the Fuel tab (Shoulder, Compare); Cold stays disabled. T3 each Fuel section in a cohort/Compare mode shows its cohort-native
// content or the All-data badge (SocBalancedFuel is not seasonAware -> badge). T5 banner numbers equal the payload (fuelContract).
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port2.onmessage&&this.port2.onmessage({data:d}))};this.port2={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};}}}
const HTML=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));const FC=A.fuelContract;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fails=0;const ok=(label,c,extra)=>{console.log((c?'PASS ':'FAIL ')+label+((!c&&extra)?' - '+extra:''));if(!c)fails++;};
const errs=[];
const dom=new JSDOM(HTML,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=(...a)=>errs.push(a.join(' ').slice(0,200));}});
const d=dom.window.document;const click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const tab=async t=>{const b=[...d.querySelectorAll('button')].find(x=>x.textContent.trim().toLowerCase()===t);if(!b)return false;click(b);await sleep(500);return true;};
const root=()=>d.getElementById('root').textContent;
const heads=()=>[...d.querySelectorAll('h2')].map(h=>h.textContent.trim());
const T_GTR='Generator→Traction Electrical Energy', T_SB='SoC-Balanced Fuel Consumption', T_TF='Cold-start fuel-rate association';
const has=(re)=>heads().some(h=>h.includes(re));
const sec=(re)=>{const h=[...d.querySelectorAll('h2')].find(x=>x.textContent.includes(re));return h?h.parentElement:null;};
(async()=>{
  await sleep(900);
  ok('fuelContract present in the payload (REQUIRED block)', !!FC&&!!FC.coverage&&FC.coverage.nCanonical===A.meta.totalDrives, FC?JSON.stringify(FC.coverage.nCanonical):'missing');
  // ---------- T1 ----------
  const navTabs=[...d.querySelectorAll('button')].map(b=>b.textContent.trim().toLowerCase());
  ok('T1 "fuel" tab button exists', navTabs.includes('fuel'));
  ok('T1 Fuel tab: banner, GTR section, SoC-balanced fuel, cold-start association', await tab('fuel')&&!!d.querySelector('[data-fuel-banner]')&&has(T_GTR)&&has(T_SB)&&has(T_TF), JSON.stringify(heads()));
  ok('T1 Fuel tab: GTR accounting table visible, no Sankey before reveal', !!d.querySelector('[data-gtr-accounting]')&&d.querySelectorAll('svg[data-gtr-sankey]').length===0);
  ok('T1 Fuel tab: no 4b prefix in the GTR title', !heads().some(h=>/^4b/.test(h)));
  await tab('charts');
  ok('T1 Charts tab: the three fuel views are gone, EnergyArchitecture stays and links to Fuel', !has(T_GTR)&&!has(T_SB)&&!has(T_TF)&&has('e-POWER Architecture')&&!!d.querySelector('[data-fuel-link-charts]'), JSON.stringify(heads()));
  await tab('distribution');
  ok('T1 Distribution tab: SoC-balanced fuel and cold-start association are gone; RpmSpeedSync / EngineStateMachine stay', !has(T_SB)&&!has(T_TF)&&has('Engine RPM')&&has('Engine Operating-Point State Machine'));
  // ---------- T2 / T3 ----------
  await tab('charts');
  for(const mode of ['shoulder','warm','compare']){
    const mb=d.querySelector(`button[data-cohort-btn="${mode}"]`);
    if(!mb||mb.disabled){ok(`${mode}: cohort button enabled`,false);continue;}
    click(mb);await sleep(500);
    await tab('fuel');
    const pressed=d.querySelector(`button[data-cohort-btn="${mode}"]`)?.getAttribute('aria-pressed')==='true';
    ok(`T2 ${mode}: selection persists after switching charts -> fuel`, pressed);
    const cold=d.querySelector('button[data-cohort-btn="cold"]');
    ok(`T2 ${mode}: Cold stays disabled in the Fuel tab`, !!cold&&cold.disabled);
    const sb=sec(T_SB);
    ok(`T3 ${mode}: SoC-balanced fuel (not cohort-native) carries the All-data badge`, !!sb&&!!sb.querySelector('[data-allref-badge]'));
    ok(`T3 ${mode}: GTR accounting table is cohort-aware (one column per series in Compare)`, (()=>{const a=d.querySelector('[data-gtr-accounting]');if(!a)return false;const cols=[...a.querySelectorAll('thead th')].length-2;return mode==='compare'?cols===[...d.querySelectorAll('button[data-cmp-btn][aria-pressed="true"]')].length:cols===1;})());
    const tf=sec(T_TF);
    ok(`T3 ${mode}: cold-start association is cohort-native (no All-data badge)`, !!tf&&!tf.querySelector('[data-allref-badge]'));
    await tab('charts');
  }
  // ---------- T5: banner numbers equal the payload ----------
  await tab('fuel');
  const bt=d.querySelector('[data-fuel-banner]').textContent.replace(/\s+/g,' ');
  const need=[`present in ${FC.coverage.rate.columnPresent} of ${FC.coverage.nCanonical} canonical files`,`${FC.coverage.bothUsable} with a usable rate and counter`,`only ${FC.coverage.nativeObdFuelRatePid_gPerS.filesWithColumn} files`,
    `Reconstruction rows: ${FC.recon.nRows} drives (${FC.recon.nChargeSustaining} charge-sustaining)`,`${FC.recon.kmProduction} km`,`(${FC.lhvRatioDefinition} = ${FC.lhvRatio})`,
    ...FC.lhvBases.filter(b=>b.kWhPerL!=null).map(b=>`${b.name} ${b.kWhPerL} kWh/L`), ...Object.keys(FC.coverage.byMonth)];
  const miss=need.filter(x=>!bt.includes(x));
  ok('T5 banner numbers and month rows equal the payload', miss.length===0, JSON.stringify(miss));
  ok('T5 banner states logged/app-calculated, model-derived, scenario, association, no fuel cost', ['logged/app-calculated','model-derived','scenario','association','No fuel cost is shown'].every(x=>bt.includes(x)));
  ok('no fuel cost column text anywhere in the dashboard', !/Вартість палива|fuel cost/i.test(root().replace('No fuel cost is shown','')));
  ok('no console errors', errs.length===0, errs.slice(0,2).join(' | '));
  console.log(fails?`\nFUEL TAB: ${fails} FAILED`:'\nFUEL TAB: all passed');process.exit(fails?1:0);
})();
