// M555 (analyses/M555_spec.md Rev 3): the panel "Observability of the Logged Cell-Voltage Channels" reads S.cellObservability per era x cadence stratum; BMS-reported wording; G01 shown with its scale ratio and no cell wording; no pooled value.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port2.onmessage&&this.port2.onmessage({data:d}))};this.port2={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};}};}
const HTML=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));const B=A.cellObservability;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fails=0;const ok=(label,c,extra)=>{console.log((c?'PASS ':'FAIL ')+label+((!c&&extra)?' - '+extra:''));if(!c)fails++;};
const errs=[];
const dom=new JSDOM(HTML,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=(...a)=>errs.push(a.join(' '));}});
const d=dom.window.document;const click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const btns=()=>[...d.querySelectorAll('button')];
const f=(x,n=2)=>x==null?'\u2014':Number(x).toFixed(n);
const pc=(x,n=2)=>x==null?'\u2014':`${(100*x).toFixed(n)} %`;
(async()=>{
  await sleep(900);
  ok('payload: known answers closed, strata only, no pooled key, no unexplained raw file',!Object.values(B.knownAnswer.misses).some(v=>v)&&!('pooled' in B)&&Object.keys(B.strata).every(k=>/^(maxMin|maxMinG01)\|/.test(k))&&B.reconciliation.rawNotInMasterByRole.unexplained===0);
  ok('payload: G01 band test not run while the scale ratio is outside 0.9-1.1',Object.values(B.strata).every(s=>Object.values(s.otherChannels).every(v=>v.bandTestRun===(v.scaleRatioToMaxMinMidMedianOfDrives>=0.9&&v.scaleRatioToMaxMinMidMedianOfDrives<=1.1))));
  const tab=btns().find(b=>b.textContent.trim().toLowerCase()==='distribution');
  ok('Distribution tab button',!!tab);if(tab){click(tab);await sleep(500);}
  const note=d.querySelector('[data-cellobs-note]');
  ok('panel rendered',!!note);
  if(note){
    ok('note: BMS-reported, not simultaneous, co-timed = equal timestamps, no spread or health statement, not comparable, no pooled value',/BMS-reported, logged/.test(note.textContent)&&/not simultaneous/.test(note.textContent)&&/exactly equal timestamps/.test(note.textContent)&&/No spread, balance, health or capacity statement/.test(note.textContent)&&/not comparable/.test(note.textContent)&&/no pooled value/.test(note.textContent));
    for(const k of Object.keys(B.strata)){
      const b=d.querySelector(`[data-cellobs-stratum="${k}"]`);ok(k+': stratum button',!!b);if(!b)continue;
      click(b);await sleep(250);
      const D=B.strata[k],sup=d.querySelector('[data-cellobs-support]').textContent;
      ok(k+': support line states drives and days',sup.includes(D.nDrives+' drives on '+D.nDays+' days'),sup.slice(0,120));
      const rowMax=d.querySelector('[data-cellobs-row="Max cell voltage"]'),cM=D.channels['[BMS] Max Cell Voltage (V)'];
      ok(k+': Max row shows coverage, age and carried-forward share',!!rowMax&&rowMax.textContent.includes(pc(cM.coverageMedianOfDrives,1))&&rowMax.textContent.includes(f(cM.ageMedianS))&&rowMax.textContent.includes(pc(cM.carriedForwardShareMedianOfDrives,1)),rowMax&&rowMax.textContent.slice(0,200));
      const cons=d.querySelector('[data-cellobs-consistency]').textContent;
      ok(k+': inversion share with its interval, no fault wording, no cell-spread change',cons.includes(pc(D.maxMinConsistency.polling.share,2))&&/of the order of the Max \/ Min sampling offset/.test(cons)&&/no cell-spread value is changed/.test(cons)&&!/fault|data error/i.test(cons),cons.slice(0,200));
      const g=d.querySelector('[data-cellobs-g01]');
      ok(k+': G01 note '+(k.startsWith('maxMinG01')?'present, scale ratio, no cell wording, labelled descriptive':'absent'),k.startsWith('maxMinG01')?(!!g&&/no band test and no cell wording/.test(g.textContent)&&/Descriptive, added after the scale pre-check/.test(g.textContent)&&!/is the sum|is cell/i.test(g.textContent)):!g);
    }
    ok('example sentence: selected-channel, counts',/Selected-channel example/.test(d.querySelector('[data-cellobs-example]').textContent));
  }
  ok('no console errors',errs.length===0,errs.slice(0,2).join(' | '));
  console.log(fails?`test_cell_observability_view: ${fails} FAIL`:'test_cell_observability_view: OK');process.exit(fails?1:0);
})();
