// M559 (analyses/M559_spec.md Rev 2): the Distribution-tab panel "Engine Rotation, Pack Flow, Coolant and Combustion Proxy as Separate Fields" reads S.engineContextFields; fields shown separately per cadence group, unresolved with and without the thermal label, scope note.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port2.onmessage&&this.port2.onmessage({data:d}))};this.port2={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};}};}
const HTML=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));const B=A.engineContextFields;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fails=0;const ok=(label,c,extra)=>{console.log((c?'PASS ':'FAIL ')+label+((!c&&extra)?' - '+extra:''));if(!c)fails++;};
const errs=[];
const dom=new JSDOM(HTML,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=(...a)=>errs.push(a.join(' '));}});
const d=dom.window.document;const click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const btns=()=>[...d.querySelectorAll('button')];
(async()=>{
  await sleep(900);
  ok('payload: strata, params, known answer residual 0',!!B&&Object.keys(B.strata).length>=2&&B.knownAnswer.residualSeconds===0&&B.params.rpm_on===400);
  const tab=btns().find(b=>b.textContent.trim().toLowerCase()==='distribution');
  ok('Distribution tab button',!!tab);if(tab){click(tab);await sleep(500);}
  const note=d.querySelector('[data-ecf-note]');
  ok('panel rendered',!!note);
  if(note){
    const t=note.textContent;
    ok('note: rotation logged, combustion and purpose not; labels not exclusive; unresolved shown with and without thermal; legacy panels unchanged',/Rotation is logged; combustion and purpose are not/.test(t)&&/not exclusive/.test(t)&&/with and without it/.test(t)&&/unchanged/.test(t)&&/not pooled/.test(t));
    for(const k of Object.keys(B.strata)){const s=d.querySelector(`[data-ecf-stratum="${k}"]`);ok(k+': stratum block present with 14 rows',!!s&&s.querySelectorAll('[data-ecf-row]').length===14,s&&s.textContent.slice(0,80));}
    const first=d.querySelector('[data-ecf-stratum]').textContent;
    ok('rows show both unresolved shares, the reasons, the band table and the exploratory probe',/no candidate at all/.test(first)&&/other than thermal context/.test(first)&&/unresolved by reason/.test(first)&&/warm cut at 75 \/ 80 \/ 85 C/.test(first)&&/exploratory: rotating at state of charge 80 %/.test(first));
    ok('the fuel-valid slow sub-stratum is labelled and present',!!B.strata.slow_fuelValid&&/not representative/.test(d.querySelector('[data-ecf-stratum="slow_fuelValid"]').textContent));
    const foot=d.querySelector('[data-ecf-foot]').textContent;
    ok('footer states the cool-cut sensitivity from the payload and the exact reconciliation',/percentage points between 75 and 85 C/.test(foot)&&/residual 0 s/.test(foot)&&/band-dependent/.test(foot)&&/between 55 and 65 C/.test(foot),foot.slice(0,200));
    ok('no forbidden wording',!/the engine runs to warm up|fuel cut is confirmed|confirmed dissipation/i.test(d.querySelector('[data-ecf-note]').parentElement.textContent));
  }
  ok('no console errors',errs.length===0,errs.slice(0,2).join(' | '));
  console.log(fails?`test_engine_context_fields_view: ${fails} FAIL`:'test_engine_context_fields_view: OK');process.exit(fails?1:0);
})();
