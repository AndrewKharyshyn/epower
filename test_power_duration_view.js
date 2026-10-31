// M552 (analyses/M552_spec.md Rev 2): the Records tab section "Observed Power Demand by Window Length" reads S.powerDuration per cadence stratum; no pooled value; exact value with the grid lower bracket; no rating wording.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port2.onmessage&&this.port2.onmessage({data:d}))};this.port2={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};}};}
const HTML=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));const B=A.powerDuration;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fails=0;const ok=(label,c,extra)=>{console.log((c?'PASS ':'FAIL ')+label+((!c&&extra)?' - '+extra:''));if(!c)fails++;};
const errs=[];
const dom=new JSDOM(HTML,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=(...a)=>errs.push(a.join(' '));}});
const d=dom.window.document;const click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const btns=()=>[...d.querySelectorAll('button')];
const f=(x,n=1)=>x==null?'\u2014':Number(x).toFixed(n);
const pv=x=>x&&x.value!=null?`${f(x.value)}${x.ci95?` (${f(x.ci95[0])}\u2013${f(x.ci95[1])})`:''}`:'\u2014';
(async()=>{
  await sleep(900);
  ok('payload: known answers closed, strata only, no pooled key',JSON.stringify(B.knownAnswer.misses)===JSON.stringify({ka4:0,ka5:0,ka6:0})&&!('pooled' in B)&&Object.keys(B.strata).every(k=>['fast','slow','unknown'].includes(k)));
  ok('payload: no escalation flag set',['fast','slow'].every(k=>Object.values(B.flags[k]).every(v=>v===false)));
  click(btns().find(b=>b.textContent.trim().toLowerCase()==='records'));await sleep(400);
  const note=d.querySelector('[data-duration-note]');
  ok('section rendered on the Records tab',!!note);
  if(note){
    ok('note: observed extrema, not ratings, strata not comparable, no pooled value, lower bracket',/not ratings, capabilities or limits/.test(note.textContent)&&/not comparable/.test(note.textContent)&&/no pooled value/.test(note.textContent)&&/lower bracket/.test(note.textContent));
    for(const k of ['fast','slow']){
      const b=d.querySelector(`[data-duration-stratum="${k}"]`);ok(k+': stratum button',!!b);if(!b)continue;
      click(b);await sleep(250);
      const D=B.strata[k],sup=d.querySelector('[data-duration-support]').textContent;
      ok(k+': support line states drives, days and the sample period',sup.includes(D.nDrives+' drives on '+D.nDays+' days')&&sup.includes(f(D.samplePeriodS.median,2)+' s'),sup.slice(0,120));
      const rows=[...d.querySelectorAll('[data-duration-row]')];
      ok(k+': one row per window length',rows.length===5);
      for(const W of ['5','120']){
        const r=rows.find(x=>x.getAttribute('data-duration-row')===W),R=D.byW[W];
        ok(k+' W='+W+': exact p95 with interval, grid lower bracket, support',!!r&&r.textContent.includes(pv(R.discharge.exact.p95))&&r.textContent.includes(pv(R.charge.exact.p95))&&r.textContent.includes(f(R.discharge.gridLowerBracket.p95))&&r.textContent.includes(R.nDrivesSupported+' ('+R.nDaysSupported+')'),r&&r.textContent.slice(0,200));
      }
    }
    ok('no rating/capability wording in the section',!/rating|capabilit|pooled (power|windows?)/i.test(d.querySelector('[data-duration-footnote]').textContent.replace(/not ratings, capabilities/g,'')));
  }
  ok('no console errors',errs.length===0,errs.slice(0,2).join(' | '));
  console.log(fails?`test_power_duration_view: ${fails} FAIL`:'test_power_duration_view: OK');process.exit(fails?1:0);
})();
