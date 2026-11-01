// M554 (analyses/M554_spec.md Rev 3): the Conclusions-tab panel "Common-support comparison of two integration methods" reads S.commonSupportBridge per cadence stratum; no pooled value; support added / lost reported apart from the difference; F17 sentence quotes the null reason and its rule.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port2.onmessage&&this.port2.onmessage({data:d}))};this.port2={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};}};}
const HTML=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));const B=A.commonSupportBridge;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fails=0;const ok=(label,c,extra)=>{console.log((c?'PASS ':'FAIL ')+label+((!c&&extra)?' - '+extra:''));if(!c)fails++;};
const errs=[];
const dom=new JSDOM(HTML,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=(...a)=>errs.push(a.join(' '));}});
const d=dom.window.document;const click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const btns=()=>[...d.querySelectorAll('button')];
const f=(x,n=4)=>x==null?'\u2014':Number(x).toFixed(n);
const dp=(x,n=3)=>(100*(x-1)).toFixed(n);
(async()=>{
  await sleep(900);
  ok('payload: known answers closed, strata only, no pooled key',!Object.values(B.knownAnswer.misses).some(v=>v)&&!('pooled' in B)&&Object.keys(B.strata).every(k=>['fast','slow','unknown'].includes(k)));
  ok('payload: F17 drives recoverable and kept out of every total',B.f17.length===2&&B.f17.every(x=>x.recoverableUnderAlternativeAlignment&&/no rate, total/.test(x.enters)));
  const m=btns().find(b=>b.textContent.trim().toLowerCase()==='conclusions');
  ok('Conclusions tab button',!!m);if(m){click(m);await sleep(500);}
  const note=d.querySelector('[data-bridge-note]');
  ok('panel rendered',!!note);
  if(note){
    ok('note: named sensitivity, estimated, validates neither energy nor offset, not comparable, no pooled value',/named sensitivity/.test(note.textContent)&&/estimated/.test(note.textContent)&&/validates neither absolute energy nor sensor offset or scale/.test(note.textContent)&&/not comparable/.test(note.textContent)&&/no pooled value/.test(note.textContent));
    for(const k of ['fast','slow']){
      const b=d.querySelector(`[data-bridge-stratum="${k}"]`);ok(k+': stratum button',!!b);if(!b)continue;
      click(b);await sleep(250);
      const g=B.strata[k].primaryCommonSupport.grossThroughput,p=d.querySelector('[data-bridge-primary]').textContent;
      ok(k+': primary shows ratio, interval, drives and days',p.includes(dp(g.ratio))&&p.includes(dp(g.ci95[0]))&&p.includes(g.nDrives+' drives on '+g.nDays+' days'),p.slice(0,160));
      ok(k+': support only one method has is stated apart',/union clock only/.test(d.querySelector('[data-bridge-support]').textContent)&&/kept out of every total/.test(d.querySelector('[data-bridge-support]').textContent));
      const rows=[...d.querySelectorAll('[data-bridge-row]')].map(x=>x.getAttribute('data-bridge-row'));
      ok(k+': ladder rows present, 1.5 s row '+(k==='slow'?'hidden':'shown'),rows.includes('U5s')&&rows.includes('Ptol3000')&&(k==='slow'?!rows.includes('Ugap1.5'):rows.includes('Ugap1.5')),rows.join(','));
    }
    const f17=d.querySelector('[data-bridge-f17]').textContent;
    ok('F17 sentence: null reason with its 1.5 s rule, alternative alignment, not about raw channels',/no_integrable_iv_pairs/.test(f17)&&/within 1\.5 s/.test(f17)&&/recoverable under an alternative alignment/.test(f17)&&/not about the raw channels/.test(f17));
    ok('no forbidden wording',!/no usable raw|validated\b(?! neither)|equivalent|no difference/i.test(d.querySelector('[data-bridge-root]').textContent.replace(/validates neither/g,'')));
  }
  ok('no console errors',errs.length===0,errs.slice(0,2).join(' | '));
  console.log(fails?`test_common_support_view: ${fails} FAIL`:'test_common_support_view: OK');process.exit(fails?1:0);
})();
