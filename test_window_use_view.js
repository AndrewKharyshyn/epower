// M553 (analyses/M553_spec.md Rev 2): the Records tab section "Use of the Assumed Battery Window" reads S.windowUse per cadence stratum; no pooled value; reference-free rows first; assumed window labelled verified:false.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port2.onmessage&&this.port2.onmessage({data:d}))};this.port2={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};}};}
const HTML=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));const B=A.windowUse;
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
  ok('payload: known answers closed, strata only, no pooled key',JSON.stringify(B.knownAnswer.misses)===JSON.stringify({closure:0,bounds:0})&&!('pooled' in B)&&Object.keys(B.strata).every(k=>['fast','slow','unknown'].includes(k)));
  click(btns().find(b=>b.textContent.trim().toLowerCase()==='records'));await sleep(400);
  const note=d.querySelector('[data-window-note]');
  ok('section rendered on the Records tab',!!note);
  if(note){
    ok('note: verified:false, not stored energy, strata not comparable, no pooled value',/verified:false/.test(note.textContent)&&/not stored energy/.test(note.textContent)&&/not comparable/.test(note.textContent)&&/no pooled value/.test(note.textContent));
    for(const k of ['fast','slow']){
      const b=d.querySelector(`[data-window-stratum="${k}"]`);ok(k+': stratum button',!!b);if(!b)continue;
      click(b);await sleep(250);
      const D=B.strata[k],sup=d.querySelector('[data-window-support]').textContent;
      ok(k+': support line states drives and days',sup.includes(D.nDrives+' drives on '+D.nDays+' days'),sup.slice(0,120));
      const ah=d.querySelector('[data-window-row="ah"]'),R=d.querySelector('[data-window-row="R"]');
      ok(k+': Ah row shows the p50',!!ah&&ah.textContent.includes(f(D.referenceFree.netChargeExcursionAhUpper.p50.value)),ah&&ah.textContent.slice(0,120));
      ok(k+': R row shows the median and the support',!!R&&R.textContent.includes(f(D.throughputOverExcursion.median,1))&&R.textContent.includes(D.throughputOverExcursion.nDrives+' drives'),R&&R.textContent.slice(0,160));
      for(const cap of ['1.5','2.1','3']){
        const key=cap==='3'?'3.0':cap;const r=d.querySelector(`[data-window-cap="${key}"]`),a=D.assumedWindow[key];
        ok(k+' cap '+key+': share of drives at or above 100 %',!!r&&r.textContent.includes(pc(a['drivesWithShareAtLeast1.0'].share)),r&&r.textContent.slice(0,160));
      }
    }
    const fn=d.querySelector('[data-window-footnote]').textContent;
    ok('footnote: rule, both verdicts, no proof, not capacity',/Rule \(fixed before the data\)/.test(fn)&&/Neither verdict is a proof/.test(fn)&&/not proof of capacity/.test(fn));
    ok('no forbidden wording in the section',!/used up|exhausted|proves the|usable capacity|pooled (window|excursion)/i.test(fn));
  }
  ok('no console errors',errs.length===0,errs.slice(0,2).join(' | '));
  console.log(fails?`test_window_use_view: ${fails} FAIL`:'test_window_use_view: OK');process.exit(fails?1:0);
})();
