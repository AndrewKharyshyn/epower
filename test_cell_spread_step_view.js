// M574 (analyses/M574_spec.md Rev 1): the Health-tab panel 'Step Sensitivity of the Cell-Spread Trend' reads S.cellSpreadStep only; the statement and every number come from the payload; limits printed; no forbidden wording.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port2.onmessage&&this.port2.onmessage({data:d}))};this.port2={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};}};}
const HTML=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));const B=A.cellSpreadStep;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fails=0;const ok=(label,c,extra)=>{console.log((c?'PASS ':'FAIL ')+label+((!c&&extra)?' - '+extra:''));if(!c)fails++;};
const errs=[];
const dom=new JSDOM(HTML,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=(...a)=>errs.push(a.join(' '));}});
const d=dom.window.document;const click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const btns=()=>[...d.querySelectorAll('button')];
const f=(x,n=2)=>x==null?'\u2014':Number(x).toFixed(n);
const pc=x=>x==null?'\u2014':`${(100*x).toFixed(1)} %`;

(async()=>{
  await sleep(900);
  ok('payload: statement, models and a confirmatory status present',!!B&&typeof B.statement==='string'&&!!B.models&&!!B.confirmatory&&['awaiting data','evaluated'].includes(B.confirmatory.status));
  ok('payload: no external-file key and no Nov file name',!/item7_external|2026-11-0[12]/.test(JSON.stringify(B)));
  click(btns().find(b=>b.textContent.trim().toLowerCase()==='health'));await sleep(500);
  const note=d.querySelector('[data-csstep-note]');
  ok('step panel rendered on the Health tab',!!note);
  if(note){
    ok('statement equals the payload statement (no typed wording)',note.textContent.trim()===B.statement.trim());
    ok('statement: post hoc, model-derived, cause unidentified, neither established nor excluded',/post hoc/.test(note.textContent)&&/model-derived/.test(note.textContent)&&/unidentified/.test(note.textContent)&&/neither established nor excluded/.test(note.textContent));
    const sup=d.querySelector('[data-csstep-support]').textContent;
    ok('support line states drives, days and window',sup.includes(B.analysisFrame.n+' drives on '+B.analysisFrame.days+' days')&&sup.includes(B.analysisFrame.windowMonths+'-month'),sup.slice(0,140));
    for(const k of Object.keys(B.models)){
      const r=d.querySelector(`[data-csstep-model="${k}"]`);ok('model row '+k,!!r);if(!r)continue;
      ok(k+': AIC and CV RMSE shown',r.textContent.includes(f(B.models[k].aic,1))&&r.textContent.includes(f(B.models[k].cv_rmse_day_blocked)),r.textContent.slice(0,160));
      if(B.models[k].step_term) ok(k+': step term shown',r.textContent.includes(f(B.models[k].step_term.est)),r.textContent.slice(0,160));
      if(B.models[k].est!=null) ok(k+': months slope shown',r.textContent.includes(f(B.models[k].est)));
    }
    const cf=d.querySelector('[data-csstep-row="confirmatory"]').textContent;
    ok('confirmatory: status shown, no number below the support floor',B.confirmatory.status==='awaiting data'?(/awaiting data/.test(cf)&&!/mean residual/.test(cf)):/mean residual/.test(cf),cf.slice(0,160));
    ok('rows: dependence, matched, equal-length, cold-start, cadence present',['dependence','matched','equal-length','cold-start','cadence'].every(n=>!!d.querySelector(`[data-csstep-row="${n}"]`)));
    const ec=d.querySelector('[data-csstep-row="equal-length"]').textContent;
    ok('equal-length row shows the payload effect',ec.includes(f(B.coldStartAndSegments.first20min_loaded_p95_allDrives.lateEffect_mv)),ec.slice(0,160));
    const ft=d.querySelector('[data-csstep-foot]').textContent;
    ok('footnote: every limit printed, not ingested files excluded',B.limits.every(l=>ft.includes(l))&&/do not enter this panel/.test(ft));
    ok('no forbidden wording in the panel',!/change ?point (was |is )?(detected|confirmed)|imbalance (is )?growing|ruled out|measured degradation|degradation (is |was )?(detected|confirmed)/i.test(note.parentElement.textContent));
  }
  const xr=d.body.textContent.includes('Step sensitivity (exploratory, see the panel below)');
  ok('cross-reference generated from the block appears in the spread conclusion text',xr||!B.models.M5_step_soc_rest.ci95);
  ok('no console errors',errs.length===0,errs.slice(0,2).join(' | '));
  console.log(fails?`test_cell_spread_step_view: ${fails} FAIL`:'test_cell_spread_step_view: OK');process.exit(fails?1:0);
})();
