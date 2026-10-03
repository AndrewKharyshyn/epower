// test_gtr_gate.js (M333) - renders xtrail_dashboard.html in jsdom and checks the GTR accounting gate in every mode (spec analyses/M333_spec.md rev 2):
// M360 (owner decision 2026-10-03): the Sankey is visible by default. T1 accounting table visible by default in All / Warm / Shoulder / Compare; T2 one Sankey svg (svg[data-gtr-sankey]) per panel with no reveal button, hatched residual branches whose values equal the accounting residuals and whose size is at the shared px scale, adjacent non-closure note;
// T3 rendered residuals equal an independent recomputation from summary_arrays.json; T4 non-closure warning + "allocation index" wording;
// T5 Compare column count == selected cohorts, no column without flows; Cold: disabled, no sketch; balanced-flows guard (patched payload) shows the closure text.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port2.onmessage&&this.port2.onmessage({data:d}))};this.port2={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};}}}
const HTML=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fails=0;const ok=(label,c,extra)=>{console.log((c?'PASS ':'FAIL ')+label+((!c&&extra)?' - '+extra:''));if(!c)fails++;};
const r2=v=>Math.round(v*100)/100, sg=v=>(v>0?'+':'')+v;
const exp=F=>{const genOut=r2((F.genToTraction||0)+(F.genToBatt||0)),genExcess=r2(genOut-(F.generatorElec||0)),battIn=r2((F.genToBatt||0)+(F.regenToBatt||0)),battResid=r2(battIn-(F.battToTraction||0));
  return {excess:sg(genExcess),resid:sg(battResid),sum:`${F.genToTraction} + ${F.genToBatt} = ${genOut}`,inflow:`${battIn} vs ${F.battToTraction}`,balanced:Math.abs(genExcess)<0.05&&Math.abs(battResid)<0.05};};
const flowsOf=mode=>mode==='all'?A.generatorTractionRecon.flows:A.seasonalCharts.charts.GeneratorTractionRecon.data[mode].flows;
const LABEL2MODE={'All Data':'all','Warm':'warm','Shoulder':'shoulder','Cold':'cold'};

function boot(html){
  const errs=[];
  const dom=new JSDOM(html,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=(...a)=>errs.push(a.join(' ').slice(0,200));}});
  const d=dom.window.document;
  const click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
  return {dom,d,click,errs};
}
const rowCells=(acc,label)=>{const tr=[...acc.querySelectorAll('tbody tr')].find(t=>t.querySelector('td').textContent.trim().startsWith(label));return tr?[...tr.querySelectorAll('td')].slice(1,-1).map(td=>td.textContent.trim()):null;};

async function main(){
  // ---------- real payload ----------
  const {d,click,errs}=boot(HTML);
  await sleep(900);
  click([...d.querySelectorAll('button')].find(b=>b.textContent.trim().toLowerCase()==='fuel'));await sleep(500);
  const sk=()=>d.querySelectorAll('svg[data-gtr-sankey]').length;
  for(const mode of ['all','warm','shoulder','compare']){
    const mb=d.querySelector(`button[data-cohort-btn="${mode}"]`);
    ok(`${mode}: cohort button present and enabled`, !!mb&&!mb.disabled);
    if(!mb||mb.disabled) continue;
    click(mb);await sleep(600);
    const acc=d.querySelector('[data-gtr-accounting]');
    ok(`${mode}: accounting table visible without any click (T1)`, !!acc);
    if(!acc) continue;
    ok(`${mode}: residual rows present (T1)`, !!rowCells(acc,'Allocation excess over generator output')&&!!rowCells(acc,'Unreconciled battery remainder'));
    // columns
    const heads=[...acc.querySelectorAll('thead th')].slice(1,-1).map(th=>th.textContent.trim());
    const modes=mode==='compare'?heads.map(h=>{const k=Object.keys(LABEL2MODE).find(l=>h.startsWith(l));return k?LABEL2MODE[k]:null;}):[mode];
    ok(`${mode}: columns map to known cohorts (T5)`, modes.every(m=>m)&&modes.length>=1, JSON.stringify(heads));
    if(mode==='compare'){
      const pressed=[...d.querySelectorAll('button[data-cmp-btn][aria-pressed="true"]')].length;
      ok(`compare: column count == selected cohorts (T5)`, heads.length===pressed, `${heads.length} vs ${pressed}`);
    } else ok(`${mode}: single column`, heads.length===1);
    const cells={ex:rowCells(acc,'Allocation excess over generator output'),re:rowCells(acc,'Unreconciled battery remainder'),su:rowCells(acc,'Generator → traction + generator → battery'),inf:rowCells(acc,'Battery inflow')};
    modes.forEach((m,i)=>{
      const e=exp(flowsOf(m));
      ok(`${mode}/${m}: rendered residuals == independent recomputation (T3)`, cells.ex[i]===e.excess&&cells.re[i]===e.resid&&cells.su[i]===e.sum&&cells.inf[i]===e.inflow, `${cells.ex[i]}/${e.excess} ${cells.re[i]}/${e.resid}`);
      if(!e.balanced){const t=acc.textContent; ok(`${mode}/${m}: non-closure warning with "allocation index" (T4)`, t.includes('do not close')&&t.includes('allocation index')&&!t.includes('sensitivity index'));}
    });
    // M360: default-visible sketch with explicit residual branches
    ok(`${mode}: no reveal button anywhere (owner decision 2026-10-03)`, !d.querySelector('[data-gtr-compare-reveal]')&&!d.querySelector('[data-gtr-flow-gate] button'));
    ok(`${mode}: Sankey visible by default, one per panel (T2)`, sk()===(mode==='compare'?heads.length:1), `count=${sk()}`);
    const svgs=[...d.querySelectorAll('svg[data-gtr-sankey]')];
    modes.forEach((m,i)=>{
      const F=flowsOf(m), svg=svgs[i]; if(!svg){ok(`${mode}/${m}: svg present`,false);return;}
      const rG=svg.querySelector('[data-gtr-residual="generator"]'), rB=svg.querySelector('[data-gtr-residual="battery"]');
      const resG=(F.genToTraction||0)+(F.genToBatt||0)-(F.generatorElec||0), resB=(F.genToBatt||0)+(F.regenToBatt||0)-(F.battToTraction||0);
      ok(`${mode}/${m}: residual branches present and equal the accounting residuals`, !!rG&&!!rB&&Math.abs(parseFloat(rG.getAttribute('data-gtr-residual-value'))-Math.round(resG*100)/100)<1e-9&&Math.abs(parseFloat(rB.getAttribute('data-gtr-residual-value'))-resB)<1e-9, `${rG&&rG.getAttribute('data-gtr-residual-value')}/${resG}`);
      const genNode=[...svg.querySelectorAll('rect')].find(r=>r.getAttribute('x')==='360'&&r.getAttribute('width')==='13'), hN=genNode?parseFloat(genNode.getAttribute('height')):NaN;
      const rr=rG&&rG.querySelector('rect'), hR=rr?parseFloat(rr.getAttribute('height')):NaN, pxs=hN/F.generatorElec;
      ok(`${mode}/${m}: residual branch drawn at the shared px scale (minimum 5 px)`, Math.abs(resG)*pxs>=5?Math.abs(hR-Math.abs(Math.round(resG*100)/100)*pxs)<0.05:hR===5, `h=${hR} scale=${pxs}`);
    });
    const note=d.querySelector('[data-gtr-sketch-note]');
    ok(`${mode}: adjacent non-closure note (not closed, not distributed, f_gen includes 0.5, F03)`, !!note&&['not closed','not distributed','includes 0.5','provenance-sensitive (F03)','not measured'].every(x=>note.textContent.includes(x)), note?note.textContent.slice(0,120):'no note');
    ok(`${mode}: no "repaired" / "closed by" wording in the panel`, !/repaired|closed by/i.test((d.querySelector('[data-gtr-flow-gate]')||d.querySelector('[data-gtr-accounting]')||note).textContent));
  }
  // ---------- Compare selections (R5): All+Warm has no Warm-Shoulder difference table; a single cohort still gets the table and the gate ----------
  click(d.querySelector('button[data-cohort-btn="compare"]'));await sleep(500);
  const pressed=()=>[...d.querySelectorAll('button[data-cmp-btn][aria-pressed="true"]')].map(b=>b.getAttribute('data-cmp-btn'));
  const toggle=async k=>{const b=d.querySelector(`button[data-cmp-btn="${k}"]`);if(b&&!b.disabled){click(b);await sleep(450);}};
  const cols=()=>{const a=d.querySelector('[data-gtr-accounting]');return a?[...a.querySelectorAll('thead th')].length-2:0;};
  const diffTable=()=>/Difference table \(Warm/.test(d.getElementById('root').textContent);
  // (the app's own selection rules decide the transitions; the test only asserts what is rendered for each resulting selection)
  const sel=()=>pressed().join('+');
  ok('compare default Warm+Shoulder: two columns and the difference table', pressed().length===2&&cols()===2&&diffTable()&&sk()===2, `sel=${sel()} cols=${cols()}`);
  await toggle('all');
  ok('compare + All: one column and one Sankey per selected series', cols()===pressed().length&&cols()>=3&&sk()===pressed().length, `sel=${sel()} cols=${cols()}`);
  await toggle('shoulder');
  ok('compare reduced selection: one column and one Sankey per selected series, no reveal button', cols()===pressed().length&&!d.querySelector('[data-gtr-compare-reveal]')&&sk()===pressed().length, `sel=${sel()} cols=${cols()}`);
  if(pressed().length>1){ for(const k of pressed().slice(1)) await toggle(k); }
  ok('compare single series: one column, no Warm-Shoulder difference table', pressed().length===1&&cols()===1&&!diffTable(), `sel=${sel()} cols=${cols()}`);
  // Cold: no data, no sketch, no fabricated table
  const cold=d.querySelector('button[data-cohort-btn="cold"]');
  ok('cold: selector disabled (below minimum support) - no Cold column or sketch can be reached', !!cold&&cold.disabled);
  ok('no console errors (real payload)', errs.length===0, errs.slice(0,2).join(' | '));

  // ---------- balanced-flows guard: patch the embedded flows so both branches close ----------
  // M349: the balancing values are derived from the payload flows (they were typed literals tied to the pre-M349 flows):
  // genToBatt = generatorElec - genToTraction, regenToBatt = battToTraction - genToBatt (both branches then close exactly).
  const FL=A.generatorTractionRecon.flows, r2=x=>Math.round(x*100)/100;
  const gB=r2(FL.generatorElec-FL.genToTraction), rB=r2(FL.battToTraction-gB);
  const OLD='"genToBatt":'+FL.genToBatt+',"regenToBatt":'+FL.regenToBatt, NEW='"genToBatt":'+gB+',"regenToBatt":'+rB;
  const n=HTML.split(OLD).length-1;
  ok('balanced guard: patch target found in the built HTML', n>=1, `n=${n}`);
  if(n>=1){
    const b=boot(HTML.split(OLD).join(NEW));await sleep(900);
    b.click([...b.d.querySelectorAll('button')].find(x=>x.textContent.trim().toLowerCase()==='fuel'));await sleep(500);
    const acc=b.d.querySelector('[data-gtr-accounting]');
    ok('balanced guard: closure text shown, no warning', !!acc&&acc.textContent.includes('Branches close within 0.05')&&!acc.textContent.includes('do not close'), acc?acc.textContent.slice(-160):'no table');
    ok('balanced guard: residual cells read +0/0', !!acc&&['0','+0'].some(v=>rowCells(acc,'Allocation excess over generator output')[0]===v));
  }
  console.log(fails?`\nGTR GATE: ${fails} FAILED`:'\nGTR GATE: all passed');
  process.exit(fails?1:0);
}
main();
