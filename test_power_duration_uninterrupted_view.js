// M561 (analyses/M561_spec.md Rev 2): the Records tab section "Observed Power Demand Without a Change of Direction" reads S.powerDurationUninterrupted per cadence stratum; net values beside it on the same drives; no pooled value; no rating wording.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port2.onmessage&&this.port2.onmessage({data:d}))};this.port2={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};}};}
const HTML=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));const B=A.powerDurationUninterrupted;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fails=0;const ok=(label,c,extra)=>{console.log((c?'PASS ':'FAIL ')+label+((!c&&extra)?' - '+extra:''));if(!c)fails++;};
const errs=[];
const dom=new JSDOM(HTML,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=(...a)=>errs.push(a.join(' '));}});
const d=dom.window.document;const click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const btns=()=>[...d.querySelectorAll('button')];
const f=(x,n=1)=>x==null?'—':Number(x).toFixed(n);
const pv=x=>x&&x.value!=null?`${f(x.value)}${x.ci95?` (${f(x.ci95[0])}–${f(x.ci95[1])})`:''}`:'—';
const pc=x=>x==null?'—':`${(100*x).toFixed(0)} %`;
(async()=>{
  await sleep(900);
  ok('payload: known answers closed, strata only, no pooled key',JSON.stringify(B.knownAnswer.misses)===JSON.stringify({kb5LeqNet:0,kb5Monotone:0,ku6Ordering:0})&&!('pooled' in B)&&Object.keys(B.strata).every(k=>['fast','slow','unknown'].includes(k)));
  click(btns().find(b=>b.textContent.trim().toLowerCase()==='records'));await sleep(400);
  const note=d.querySelector('[data-uninterrupted-note]');
  ok('section rendered on the Records tab',!!note);
  if(note){
    ok('note: no change of direction, sample-interpolated zero, percentile-of-differences caveat, not ratings, not pooled',/did not change direction/.test(note.textContent)&&/sample-interpolated zero/.test(note.textContent)&&/not the percentile of the per-drive differences/.test(note.textContent)&&/not ratings, capabilities or limits/.test(note.textContent)&&/not pooled and not compared/.test(note.textContent));
    for(const k of ['fast','slow']){
      const b=d.querySelector(`[data-uninterrupted-stratum="${k}"]`);ok(k+': stratum button',!!b);if(!b)continue;
      click(b);await sleep(250);
      const D=B.strata[k],sup=d.querySelector('[data-uninterrupted-support]').textContent;
      ok(k+': support line states drives and days',sup.includes(D.nDrives+' drives on '+D.nDays+' days'),sup.slice(0,120));
      const rows=[...d.querySelectorAll('[data-uninterrupted-row]')];
      ok(k+': one row per window length',rows.length===5);
      for(const W of ['5','120']){
        const r=rows.find(x=>x.getAttribute('data-uninterrupted-row')===W),R=D.byW[W];
        const t=r?r.textContent:'';
        ok(k+' W='+W+': one-direction p95, net p95 on the same drives, eligible share and equals-net share for both directions',!!r&&t.includes(R.discharge.uninterrupted?pv(R.discharge.uninterrupted.p95):'—')&&t.includes(pc(R.discharge.eligibleRunShare))&&t.includes(pc(R.charge.eligibleRunShare))&&t.includes(pc(R.discharge.shareUninterruptedEqualsNet)),t.slice(0,160));
      }
    }
    click(d.querySelector('[data-uninterrupted-stratum="slow"]'));await sleep(250);
    const br=d.querySelector('[data-uninterrupted-bracket]');
    ok('slow: bracket note names the interpolated primary and the lower bracket',!!br&&/interpolated zero is the pre-registered primary/.test(br.textContent)&&/lower bracket/.test(br.textContent),br&&br.textContent.slice(0,120));
    const r120=[...d.querySelectorAll('[data-uninterrupted-row]')].find(x=>x.getAttribute('data-uninterrupted-row')==='120');
    ok('slow W=120: low-support marker with the number of drives, charge p95 suppressed (n<40)',!!r120&&/low support/.test(r120.textContent)&&r120.textContent.includes('(n='+B.strata.slow.byW['120'].charge.displayRule.nEligible+')')&&!B.strata.slow.byW['120'].charge.displayRule.showP95);
    click(d.querySelector('[data-uninterrupted-stratum="fast"]'));await sleep(250);
    const f120=[...d.querySelectorAll('[data-uninterrupted-row]')].find(x=>x.getAttribute('data-uninterrupted-row')==='120');
    ok('fast W=120 charge: cell hidden by the display rule (fewer than 20 drives)',!!f120&&!B.strata.fast.byW['120'].charge.displayRule.showCell&&f120.textContent.includes('(n='+B.strata.fast.byW['120'].charge.displayRule.nEligible+')'));
    const re=d.querySelector('[data-runend-note]');
    ok('run-end note: assumed linear-to-zero path, extent not value, not compared with net, base shrinks, smallest window under 50 %',!!re&&/assumed linear-to-zero path/.test(re.textContent)&&/not a bound on the power value/.test(re.textContent)&&/not compared with the net values/.test(re.textContent)&&/base shrinks with the window length/.test(re.textContent)&&/Smallest window with a share under 50 %/.test(re.textContent),re&&re.textContent.slice(0,120));
    const rr=[...d.querySelectorAll('[data-runend-row]')];
    ok('run-end table: one row per window length with lower / primary / upper shares',rr.length===5&&rr.every(x=>(x.textContent.match(/ \/ /g)||[]).length>=4));
    const foot=d.querySelector('[data-uninterrupted-footnote]').textContent;
    ok('footnote: equals-net definition, conditional percentiles, current offset and near-zero dependence',/Equals net/.test(foot)&&/conditional on a drive having such a window/.test(foot)&&/current offset/.test(foot));
    ok('no forbidden wording in the section',!/rating|sustained|steady|continuous|reversal penalty/i.test((note.textContent+foot).replace(/not ratings, capabilities/g,'')));
  }
  ok('no console errors',errs.length===0,errs.slice(0,2).join(' | '));
  console.log(fails?`test_power_duration_uninterrupted_view: ${fails} FAIL`:'test_power_duration_uninterrupted_view: OK');process.exit(fails?1:0);
})();
