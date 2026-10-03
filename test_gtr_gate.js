// test_gtr_gate.js (M333) - renders xtrail_dashboard.html in jsdom and checks the GTR accounting gate in every mode (spec analyses/M333_spec.md rev 2):
// T1 accounting table visible by default in All / Warm / Shoulder / Compare; T2 no Sankey svg (svg[data-gtr-sankey]) anywhere before a reveal, >=1 after;
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
    ok(`${mode}: no Sankey svg anywhere before a reveal (T2)`, sk()===0, `count=${sk()}`);
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
    // reveal
    const btn=mode==='compare'?d.querySelector('[data-gtr-compare-reveal]'):d.querySelector('[data-gtr-flow-gate] button');
    ok(`${mode}: reveal button present`, !!btn);
    if(btn){click(btn);await sleep(300);
      ok(`${mode}: Sankey appears only after the reveal (T2)`, sk()>=1&&(mode!=='compare'||sk()===heads.length), `count=${sk()}`);
      click(btn);await sleep(200);
      ok(`${mode}: hiding the sketch removes it again`, sk()===0);}
  }
  // ---------- Compare selections (R5): All+Warm has no Warm-Shoulder difference table; a single cohort still gets the table and the gate ----------
  click(d.querySelector('button[data-cohort-btn="compare"]'));await sleep(500);
  const pressed=()=>[...d.querySelectorAll('button[data-cmp-btn][aria-pressed="true"]')].map(b=>b.getAttribute('data-cmp-btn'));
  const toggle=async k=>{const b=d.querySelector(`button[data-cmp-btn="${k}"]`);if(b&&!b.disabled){click(b);await sleep(450);}};
  const cols=()=>{const a=d.querySelector('[data-gtr-accounting]');return a?[...a.querySelectorAll('thead th')].length-2:0;};
  const diffTable=()=>/Difference table \(Warm/.test(d.getElementById('root').textContent);
  // (the app's own selection rules decide the transitions; the test only asserts what is rendered for each resulting selection)
  const sel=()=>pressed().join('+');
  ok('compare default Warm+Shoulder: two columns and the difference table', pressed().length===2&&cols()===2&&diffTable()&&sk()===0, `sel=${sel()} cols=${cols()}`);
  await toggle('all');
  ok('compare + All: one column per selected series, no Sankey before reveal', cols()===pressed().length&&cols()>=3&&sk()===0, `sel=${sel()} cols=${cols()}`);
  await toggle('shoulder');
  ok('compare reduced selection: one column per selected series, gate and reveal button still present', cols()===pressed().length&&!!d.querySelector('[data-gtr-compare-reveal]')&&sk()===0, `sel=${sel()} cols=${cols()}`);
  if(pressed().length>1){ for(const k of pressed().slice(1)) await toggle(k); }
  ok('compare single series: one column, no Warm-Shoulder difference table', pressed().length===1&&cols()===1&&!diffTable(), `sel=${sel()} cols=${cols()}`);
  // Cold: no data, no sketch, no fabricated table
  const cold=d.querySelector('button[data-cohort-btn="cold"]');
  ok('cold: selector disabled (below minimum support) - no Cold column or sketch can be reached', !!cold&&cold.disabled&&sk()===0);
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
