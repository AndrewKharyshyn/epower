// M557 (analyses/M557_spec.md Rev 2): the Distribution-tab panel "Dependency of Checks and Controls on Their Targets" reads S.channelDependency; computed relation per ledger check, conflict marker without status change, controls with expected outcome and null mechanism.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port2.onmessage&&this.port2.onmessage({data:d}))};this.port2={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};}};}
const HTML=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));const B=A.channelDependency;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fails=0;const ok=(label,c,extra)=>{console.log((c?'PASS ':'FAIL ')+label+((!c&&extra)?' - '+extra:''));if(!c)fails++;};
const errs=[];
const dom=new JSDOM(HTML,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=(...a)=>errs.push(a.join(' '));}});
const d=dom.window.document;const click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const btns=()=>[...d.querySelectorAll('button')];
(async()=>{
  await sleep(900);
  ok('payload: 13 claims, coverage closed, every declared class equals the computed class',B.claims.length===13&&!B.coverage.ledgerChecksWithoutClaim.length&&!B.coverage.scanHitsWithoutClaim.length&&!B.coverage.controlClaimsWithoutHit.length&&B.claims.every(c=>c.declaredClass===c.computedClass));
  ok('payload: pre-registered classes (E1 coding, E2 shared, E3 circular, E4/E5 model adequacy, E6 shared)',['coding_check_only','shared_raw_input','circular','model_adequacy','model_adequacy','shared_raw_input'].every((k,i)=>B.claims.find(c=>c.id==='E'+(i+1)).computedClass===k));
  const tab=btns().find(b=>b.textContent.trim().toLowerCase()==='distribution');
  ok('Distribution tab button',!!tab);if(tab){click(tab);await sleep(500);}
  const note=d.querySelector('[data-depend-note]');
  ok('panel rendered',!!note);
  if(note){
    ok('note: hand-curated, class computed, no status changed, conflict marked',/hand-curated declarations/.test(note.textContent)&&/computed from them/.test(note.textContent)&&/No validation status is changed here/.test(note.textContent)&&/conflict is marked/.test(note.textContent));
    for(const c of B.claims){const r=d.querySelector(`[data-depend-row="${c.id}"]`);ok(c.id+': row present',!!r&&r.textContent.includes(c.targetLabel),r&&r.textContent.slice(0,100));}
    const e3=d.querySelector('[data-depend-row="E3"]').textContent;
    ok('E3 shown as circular with its current status and a marked conflict',/circular/.test(e3)&&e3.includes(B.claims.find(c=>c.id==='E3').currentValidationStatus)&&/conflict marked/.test(e3),e3.slice(0,200));
    ok('controls table shows expected outcome, null mechanism, the blind-audit notes and the decision-rule label',/null mechanism/.test(d.querySelector('[data-depend-controls]').textContent)&&/bias reference/.test(d.querySelector('[data-depend-controls]').textContent)&&/notes from the blind audit/.test(d.querySelector('[data-depend-controls]').textContent)&&/pre-registered decision rule/.test(d.querySelector('[data-depend-controls]').textContent)&&/also pool drives/.test(d.querySelector('[data-depend-controls]').textContent));
    const e6=d.querySelector('[data-depend-row="E6"]').textContent; ok('E6 shows the settled class after the blind audit',/model adequacy/.test(e6)&&/settled by the Director after the blind audit/.test(e6),e6.slice(0,260));
    ok('footer states the counts and that latent inputs are declared, not observed',/6 ledger checks and 7 controls and decision rules/.test(d.querySelector('[data-depend-foot]').textContent)&&/declared, not observed/.test(d.querySelector('[data-depend-foot]').textContent));
    ok('no forbidden wording',!/independent validation by|derived sibling validates|circular check (confirms|proves)/i.test(d.querySelector('[data-depend-note]').parentElement.textContent));
  }
  ok('no console errors',errs.length===0,errs.slice(0,2).join(' | '));
  console.log(fails?`test_dependency_audit_view: ${fails} FAIL`:'test_dependency_audit_view: OK');process.exit(fails?1:0);
})();
