// M531 (analyses/M531_spec.md Rev 2): the motored share inside the RPM Distribution chart's "Fuelled, extended" view is not reached by the default tab/mode dump. This test opens that view in every cohort mode
// where the chart renders and checks the sentence against S.motoredShare: interval for the shown cohort when the support rule holds (warm / shoulder / all), "exploratory, no interval" for the cold cohort, the
// "descriptive, no interval" label gone, and the grid-only gap-fill sensitivity clause labelled as such.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port2.onmessage&&this.port2.onmessage({data:d}))};this.port2={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};}};}
const HTML=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));const MS=A.motoredShare;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fails=0;const ok=(label,c,extra)=>{console.log((c?'PASS ':'FAIL ')+label+((!c&&extra)?' - '+extra:''));if(!c)fails++;};
const errs=[];
const dom=new JSDOM(HTML,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=(...a)=>errs.push(a.join(' '));}});
const d=dom.window.document;const click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const btns=()=>[...d.querySelectorAll('button')];
const TABS=['overview','charts','fuel','distribution','highway vs city','thermal','records','health','cross-vehicle','conclusions'];
(async()=>{
  await sleep(900);
  let found=false;
  for(const t of TABS){
    click(btns().find(b=>b.textContent.trim().toLowerCase()===t));await sleep(300);
    if(!btns().some(b=>/^Fuelled proxy, extended/.test(b.textContent.trim())))continue;
    found=true;
    const modes=btns().filter(b=>b.hasAttribute('data-cohort-btn')&&!b.disabled).map(b=>b.getAttribute('data-cohort-btn'));
    ok('tab '+t+': cohort modes selectable',modes.length>=4,JSON.stringify(modes));
    for(const m of modes){
      click(d.querySelector(`button[data-cohort-btn="${m}"]`));await sleep(400);
      const eb=btns().find(b=>/^Fuelled proxy, extended/.test(b.textContent.trim()));
      if(!eb){ok(m+': chart replaced by the compare block (no extended view)',m==='compare');continue;}
      click(eb);await sleep(300);
      const txt=d.getElementById('root').textContent;
      const i=txt.indexOf('Motored is deliberately not extended this way');
      ok(m+': motored sentence rendered',i>=0);if(i<0)continue;
      const s=txt.slice(i,i+900);
      const e=m==='all'?MS.pooled:MS.cohorts[m];
      ok(m+': "descriptive, no interval" label gone',!/descriptive, no interval/.test(s));
      if(e.intervalShown){
        ok(m+': interval '+e.ci95Pct[0].toFixed(1)+'–'+e.ci95Pct[1].toFixed(1)+' and counts shown',s.includes('95 % CI '+e.ci95Pct[0].toFixed(1)+'–'+e.ci95Pct[1].toFixed(1)+', day-clustered; '+e.nDrivesWithMotored+' of '+e.nDrivesWithClassified+' drives and '+e.nDaysWithMotored+' of '+e.nDays+' days with motored seconds; a rare, zero-inflated state'));
        ok(m+': grid-only gap-fill sensitivity labelled',s.includes('pooled share with a grid-only gap-fill convention '+MS.gridOnlyFfillSensitivity_postHoc_auditorFound.pct.toFixed(1)+' %'));
      }else{
        ok(m+': exploratory, no interval ('+e.nDaysWithMotored+' of '+e.nDays+' days)',s.includes('exploratory, no interval ('+e.nDaysWithMotored+' of '+e.nDays+' days with motored seconds)')&&!/95 % CI/.test(s));
      }
    }
    break;
  }
  ok('the RPM Distribution chart with the extended view was found',found);
  ok('no console errors',errs.length===0,errs.slice(0,2).join(' | '));
  console.log(fails?`test_motored_share_view: ${fails} FAIL`:'test_motored_share_view: OK');process.exit(fails?1:0);
})();
