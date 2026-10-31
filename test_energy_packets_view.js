// M551 (analyses/M551_spec.md Rev 2): the Records tab section "Energy Exchange Runs" reads S.energyPackets per cadence stratum; no pooled value, censoring and the length-bias bracket stated.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port2.onmessage&&this.port2.onmessage({data:d}))};this.port2={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};}};}
const HTML=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));const B=A.energyPackets;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fails=0;const ok=(label,c,extra)=>{console.log((c?'PASS ':'FAIL ')+label+((!c&&extra)?' - '+extra:''));if(!c)fails++;};
const errs=[];
const dom=new JSDOM(HTML,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=(...a)=>errs.push(a.join(' '));}});
const d=dom.window.document;const click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const btns=()=>[...d.querySelectorAll('button')];
const f=(x,n=1)=>x==null?'\u2014':Number(x).toFixed(n);
(async()=>{
  await sleep(900);
  ok('payload: reconciliation closed, strata only, no pooled key',B.reconciliation.nMisses===0&&!('pooled' in B)&&Object.keys(B.strata).every(k=>['fast','slow','unknown'].includes(k)));
  click(btns().find(b=>b.textContent.trim().toLowerCase()==='records'));await sleep(400);
  const note=d.querySelector('[data-packets-note]');
  ok('section rendered on the Records tab',!!note);
  if(note){
    ok('note: observed exchange, not an ageing cycle, strata not comparable, no pooled value',/not an ageing cycle/.test(note.textContent)&&/not comparable/.test(note.textContent)&&/no pooled value/.test(note.textContent));
    for(const k of ['fast','slow']){
      const b=d.querySelector(`[data-packets-stratum="${k}"]`);ok(k+': stratum button present',!!b);if(!b)continue;
      click(b);await sleep(250);
      const D=B.strata[k],sup=d.querySelector('[data-packets-support]').textContent;
      ok(k+': support line states drives, days and runs',sup.includes(D.nDrives+' drives on '+D.nDays+' days')&&sup.includes(D.nRunsAll.toLocaleString()),sup.slice(0,160));
      ok(k+': censored shares and reconciliation stated',sup.includes(f(D.censoredRunSharePct,2)+' %')&&sup.includes(B.reconciliation.nCompared+' drives compared, '+B.reconciliation.nMisses+' misses'));
      const row=[...d.querySelectorAll('tbody tr')].find(r=>r.textContent.startsWith('All runs'));
      const med=D.overall.energyWh.completeOnly.median;
      ok(k+': all-runs median energy with its interval',!!row&&row.textContent.includes(f(med.value)+(med.ci95?` (${f(med.ci95[0])}\u2013${f(med.ci95[1])})`:'')),row&&row.textContent.slice(0,160));
      ok(k+': below-1-Wh shares of runs and energy',!!row&&row.textContent.includes(f(D.overall.below1Wh.countSharePct.pct,2)+' %')&&row.textContent.includes(f(D.overall.below1Wh.energySharePct.pct,2)+' %'));
      ok(k+': length-bias bracket and deadband sentence',/length-biased/.test(d.querySelector('[data-packets-bracket]').textContent)&&/Current deadband/.test(d.querySelector('[data-packets-bracket]').textContent));
    }
    ok('no pooled/comparable wording in the section',!/pooled (energy )?runs?|runs are comparable/i.test(note.parentElement.textContent));
  }
  ok('no console errors',errs.length===0,errs.slice(0,2).join(' | '));
  console.log(fails?`test_energy_packets_view: ${fails} FAIL`:'test_energy_packets_view: OK');process.exit(fails?1:0);
})();
