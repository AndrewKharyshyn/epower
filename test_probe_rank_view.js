// M549 (analyses/M549_spec.md Rev 2): the Sensor 1 / Sensor 4 tiles state unique and tied time from S.temperatureProbeRanking (no first-index share); the legacy wording is gone.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port2.onmessage&&this.port2.onmessage({data:d}))};this.port2={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};}};}
const HTML=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));const B=A.temperatureProbeRanking;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fails=0;const ok=(label,c,extra)=>{console.log((c?'PASS ':'FAIL ')+label+((!c&&extra)?' - '+extra:''));if(!c)fails++;};
const errs=[];
const dom=new JSDOM(HTML,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=(...a)=>errs.push(a.join(' '));}});
const d=dom.window.document;const click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const btns=()=>[...d.querySelectorAll('button')];
const TABS=['overview','charts','fuel','distribution','highway vs city','thermal','records','health','cross-vehicle','conclusions'];
const f=x=>x.pct.toFixed(1)+' %'+(x.ci95Pct?` (95 % CI ${x.ci95Pct[0].toFixed(1)}\u2013${x.ci95Pct[1].toFixed(1)})`:'');
(async()=>{
  await sleep(900);
  ok('payload block present with the declared rule',!!B&&B.rule.primaryAggregator==='last'&&B.identities.nViolations===0);
  ok('legacy role wording removed from the payload roles',A.sensorSummary.every(s=>!/reads (highest|lowest) in/.test(s.role)));
  let seen=false;
  for(const t of TABS){
    click(btns().find(b=>b.textContent.trim().toLowerCase()===t));await sleep(300);
    const hot=d.querySelector('[data-probe-rank="Sensor 1"]'),cold=d.querySelector('[data-probe-rank="Sensor 4"]');
    if(!hot)continue;
    seen=true;const P=B.pooled;
    ok('Sensor 1 tile: unique and tied time with intervals',hot.textContent.includes('uniquely hottest '+f(P.hot.T1.unique)+' of observed time')&&hot.textContent.includes('tied for the extreme '+f(P.hot.T1.tied)),hot.textContent);
    ok('Sensor 4 tile: unique and tied time with intervals',!!cold&&cold.textContent.includes('uniquely coldest '+f(P.cold.T4.unique)+' of observed time')&&cold.textContent.includes('tied for the extreme '+f(P.cold.T4.tied)),cold&&cold.textContent);
    ok('counts stated',hot.textContent.includes(P.hot.nDrives+' drives, '+P.hot.nDays+' days'));
    const all=d.getElementById('root').textContent;
    ok('no first-index wording in the rendered tab',!/reads (highest|lowest) in|hottest probe in \d+ ?% of samples/.test(all));
    break;
  }
  ok('the sensor tiles were found',seen);
  ok('no console errors',errs.length===0,errs.slice(0,2).join(' | '));
  console.log(fails?`test_probe_rank_view: ${fails} FAIL`:'test_probe_rank_view: OK');process.exit(fails?1:0);
})();
