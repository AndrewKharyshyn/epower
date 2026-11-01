// M556 (analyses/M556_spec.md Rev 2): the Distribution-tab panel "Declared Validity Rules of Logged Channels" reads S.signalValidity; unavailable wording for the all-zero BMS 12 V channel, no 12 V chart, raw values preserved.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port2.onmessage&&this.port2.onmessage({data:d}))};this.port2={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};}};}
const HTML=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));const B=A.signalValidity;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fails=0;const ok=(label,c,extra)=>{console.log((c?'PASS ':'FAIL ')+label+((!c&&extra)?' - '+extra:''));if(!c)fails++;};
const errs=[];
const dom=new JSDOM(HTML,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=(...a)=>errs.push(a.join(' '));}});
const d=dom.window.document;const click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const btns=()=>[...d.querySelectorAll('button')];
(async()=>{
  await sleep(900);
  const bms=B.entries.find(e=>e.id==='bms_12v_supply');
  ok('payload: partition identity, no non-zero BMS 12 V value, no unexplained raw file, master intake inside the bound',bms.filesRuleHolds+bms.filesRuleNotHolding===bms.filesWithSamples&&bms.nonZeroValuesInDeclaredChannel===0&&B.reconciliation.rawNotInMasterByRole.unexplained===0&&B.masterIntakeCheck.rowsOutsideBound===0);
  const tab=btns().find(b=>b.textContent.trim().toLowerCase()==='distribution');
  ok('Distribution tab button',!!tab);if(tab){click(tab);await sleep(500);}
  const note=d.querySelector('[data-validity-note]');
  ok('panel rendered',!!note);
  if(note){
    ok('note: declared rule with justification, holds in the corpus files counted, raw preserved, no physical statement',/declared validity rule/.test(note.textContent)&&/holds in the corpus files counted/.test(note.textContent)&&/stay in the raw files/.test(note.textContent)&&/no physical statement/.test(note.textContent)&&!/always/.test(note.textContent));
    for(const e of B.entries){
      const r=d.querySelector(`[data-validity-row="${e.id}"]`);ok(e.id+': row present with the column header',!!r&&r.textContent.includes(e.column),r&&r.textContent.slice(0,120));
    }
    const rb=d.querySelector('[data-validity-row="bms_12v_supply"]');
    ok('BMS 12 V row: files and days where the rule holds, active period',!!rb&&rb.textContent.includes(`${bms.filesRuleHolds} of ${bms.filesWithSamples} files, ${bms.daysRuleHolds} days`)&&rb.textContent.includes(bms.activePeriod[0]),rb&&rb.textContent.slice(0,200));
    const t=d.querySelector('[data-validity-bms]').textContent;
    ok('BMS 12 V sentence: unavailable, cause unknown, no chart, no fault wording',/unavailable \(all logged values equal 0 in \d+ files\)/.test(t)&&/cause of the 0 response is unknown/.test(t)&&/No 12 V chart/.test(t)&&!/fault|dead|failed/i.test(t));
    const a=d.querySelector('[data-validity-air]').textContent;
    ok('intake-air sentence: sentinel upstream, out-of-bound samples not interpreted, master rows outside the bound',/removed upstream/.test(a)&&/not interpreted/.test(a)&&new RegExp(B.masterIntakeCheck.rowsOutsideBound+' master rows outside the bound').test(a)&&!/fault|error|overheat/i.test(a));
    ok('inventory line: not a validity declaration',/not a validity declaration/.test(d.querySelector('[data-validity-inventory]').textContent));
  }
  ok('no console errors',errs.length===0,errs.slice(0,2).join(' | '));
  console.log(fails?`test_signal_validity_view: ${fails} FAIL`:'test_signal_validity_view: OK');process.exit(fails?1:0);
})();
