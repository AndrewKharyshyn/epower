// M560 (analyses/M560_spec.md Rev 2): the panel "Sensitivity of the Cell-Spread Relaxation to Pairing, Fill and Gaps" reads S.cellSpreadRelaxationSensitivity; per cadence group the reference row, the re-measured rows, the window-set rows with added / dropped counts, the placebo and the scope note.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port2.onmessage&&this.port2.onmessage({data:d}))};this.port2={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};}};}
const HTML=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));const B=A.cellSpreadRelaxationSensitivity;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fails=0;const ok=(label,c,extra)=>{console.log((c?'PASS ':'FAIL ')+label+((!c&&extra)?' - '+extra:''));if(!c)fails++;};
const errs=[];
const dom=new JSDOM(HTML,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=(...a)=>errs.push(a.join(' '));}});
const d=dom.window.document;const click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const btns=()=>[...d.querySelectorAll('button')];
(async()=>{
  await sleep(900);
  ok('payload: V0 reproduces the stored block (830 windows) and strata present',!!B&&B.knownAnswer.reproducesStored&&B.knownAnswer.pooledIntervalMatchesStored&&B.pooledV0.n===830&&Object.keys(B.strata).length>=2);
  const tab=btns().find(b=>b.textContent.trim().toLowerCase()==='distribution');
  ok('Distribution tab button',!!tab);if(tab){click(tab);await sleep(500);}
  const note=d.querySelector('[data-csr-note]');
  ok('panel rendered',!!note);
  if(note){
    const t=note.textContent;
    ok('note: published block unchanged, one step per row, lattice and resolution floor, not pooled, no diagnosis',/published block and its text are unchanged/.test(t)&&/Each row changes one step/.test(t)&&/0\.5 mV lattice/.test(t)&&/resolution floor, not a measured widening/.test(t)&&/not pooled/.test(t)&&/no cell diagnosis/.test(t));
    for(const k of Object.keys(B.strata)){const s=d.querySelector(`[data-csr-stratum="${k}"]`);ok(k+': 11 rows (reference, 3 re-measured, 6 window-set, placebo)',!!s&&s.querySelectorAll('[data-csr-row]').length===11,s&&String(s.querySelectorAll('[data-csr-row]').length));}
    const first=d.querySelector('[data-csr-stratum]').textContent;
    ok('rows name the separate estimand, the window-set rows and the placebo',/separate estimand: native pair level/.test(first)&&/window set: real samples of both channels only/.test(first)&&/placebo: pseudo load-offs/.test(first)&&/added/.test(first));
    const foot=d.querySelector('[data-csr-foot]').textContent;
    ok('footer: exact reproduction, lattice-bound intervals, half-time not reported, flags',/reproduce the published block exactly/.test(foot)&&/lattice-bound/.test(foot)&&/Half-time has no median/.test(foot)&&/Flags raised/.test(foot)&&/filled past a channel's last real sample/.test(foot)&&/cannot be told apart from rest noise/.test(foot),foot.slice(0,160));
    ok('no forbidden wording',!/well-balanced|never deeply stresses|healthy|balanced pack/i.test(d.querySelector('[data-csr-note]').parentElement.textContent));
  }
  ok('no console errors',errs.length===0,errs.slice(0,2).join(' | '));
  console.log(fails?`test_csr_sensitivity_view: ${fails} FAIL`:'test_csr_sensitivity_view: OK');process.exit(fails?1:0);
})();
