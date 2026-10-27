// M519 (R02, audit 2026-10-26): the nested Charts > "Power fade - estimated proxy" view is not reached by the default tab/mode dump. This test opens it in every cohort mode and checks that the
// joint-matrix sentence states BOTH populations from S.resistanceJointSensitivity.pairedSet and pairedSet.g2Subset (G0/G1 paired set; G2 smaller subset), keeps the dependence warning, and that
// the former single-population wording is gone.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port2.onmessage&&this.port2.onmessage({data:d}))};this.port2={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};}};}
const HTML=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));const ps=A.resistanceJointSensitivity.pairedSet;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fails=0;const ok=(label,c,extra)=>{console.log((c?'PASS ':'FAIL ')+label+((!c&&extra)?' - '+extra:''));if(!c)fails++;};
const errs=[];
const dom=new JSDOM(HTML,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=(...a)=>errs.push(a.join(' ').slice(0,200));}});
const d=dom.window.document;const click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const btnText=(re)=>[...d.querySelectorAll('button')].find(b=>re.test(b.textContent.trim()));
(async()=>{
  await sleep(900);
  click(btnText(/^charts$/i));await sleep(500);
  const modes=[...d.querySelectorAll('button[data-cohort-btn]')].filter(b=>!b.disabled).map(b=>b.getAttribute('data-cohort-btn'));
  ok('at least the five documented cohort modes are selectable',modes.length>=5,JSON.stringify(modes));
  for(const m of modes){
    const mb=d.querySelector(`button[data-cohort-btn="${m}"]`);click(mb);await sleep(400);
    const pv=btnText(/^Power fade\s*[\u2014-]\s*estimated proxy/);
    if(!pv){ok(`${m}: Power fade selector present`,false);continue;}
    click(pv);await sleep(500);
    const t=d.getElementById('root').textContent;
    const i=t.indexOf('Joint instrumentation sensitivity (M514');
    ok(`${m}: joint-matrix sentence rendered`,i>=0);
    if(i<0)continue;
    const s=t.slice(i,i+1400);
    ok(`${m}: G0/G1 population stated (${ps.nDrives} drives on ${ps.nDays} days)`,s.includes(`G0 and G1 cells: the paired set of ${ps.nDrives} drives on ${ps.nDays} days`),s.slice(0,300));
    ok(`${m}: G2 population stated as the smaller subset (${ps.g2Subset.nDrives} drives on ${ps.g2Subset.nDays} days)`,s.includes(`G2 grid-exclusion cells: the smaller subset of ${ps.g2Subset.nDrives} drives on ${ps.g2Subset.nDays} days`));
    ok(`${m}: the former single-population claim is gone`,!/the cells share the same drives/.test(s));
    ok(`${m}: dependence warning kept`,/dependent, not independent tests/.test(s));
  }
  ok('no console errors',errs.length===0,errs.slice(0,2).join(' | '));
  console.log(fails?`test_power_fade_matrix: ${fails} FAIL`:'test_power_fade_matrix: OK');process.exit(fails?1:0);
})();
