// test_warmup_chart.js (M624, spec analyses/M624_spec.md Rev 1): renders xtrail_dashboard.html in jsdom, opens the Distribution tab (host of the coolant / oil warm-up section) and checks
// (1) the x positions of the curve markers are proportional to the bin mid-time in seconds (within 0.5 px), (2) bins below the support floor are hollow and carry no whisker,
// (3) the caption and row labels, (4) the Kaplan-Meier panel prints the ledger values (all cohort) and the 'not computed' text (cold cohort),
// (5) the end labels exist, (6) the old wording is absent. Pure SVG geometry is read from the DOM; the payload supplies the expected values.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};this.port2={postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))}}}}
const html=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));
let fails=0;const ok=(label,c)=>{console.log((c?'PASS ':'FAIL ')+label);if(!c)fails++;};
const dom=new JSDOM(html,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=()=>{};w.console.warn=()=>{}}});
const d=dom.window.document,sleep=ms=>new Promise(r=>setTimeout(r,ms)),click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
let click2;const W=A.thermalWarmupLag.warmupCurves;
(async()=>{
  await sleep(1000);
  click([...d.querySelectorAll('button')].find(b=>b.textContent.trim().toLowerCase()==='distribution'));await sleep(400);
  for(const b of [...d.querySelectorAll('button')].filter(b=>/▸|▶|show|expand|more|details/i.test(b.textContent)&&b.getAttribute('aria-expanded')==='false')){click(b);}
  await sleep(300);
  const cap=[...d.querySelectorAll('div')].find(x=>x.children.length===0&&x.textContent.startsWith('WARM-UP CURVES'));
  ok('warm-up chart present with the new caption (elapsed time, cold-start definition, whiskers, hollow markers)', !!cap&&/elapsed time from start/.test(cap.textContent)&&/below 60/.test(cap.textContent)&&/p25.p75/.test(cap.textContent)&&/hollow marker/.test(cap.textContent));
  const svg=cap&&cap.nextElementSibling; const circles=svg?[...svg.querySelectorAll('circle')]:[];
  const nb=W.coolantMedianC.length, PL=44, PR=60, pw=480-PL-PR, tmax=W.timeBinsS[W.timeBinsS.length-1];
  const cc=circles.filter(c=>c.getAttribute('stroke')==='#2563eb');
  ok('one coolant marker per non-null bin', cc.length===W.coolantMedianC.filter(v=>v!=null).length);
  let prop=true;
  W.coolantMedianC.forEach((v,i)=>{ if(v==null) return; const mid=(W.timeBinsS[i]+W.timeBinsS[i+1])/2; const want=PL+mid/tmax*pw; const got=parseFloat(cc[i].getAttribute('cx')); if(Math.abs(got-want)>0.5) prop=false; });
  ok('x position proportional to the bin mid-time in seconds (within 0.5 px)', prop);
  ok('markers: filled iff the bin meets the support floor (payload coolantSupported)', cc.every((c,i)=>(c.getAttribute('fill')==='#2563eb')===W.coolantSupported[i]));
  const whiskers=svg?[...svg.querySelectorAll('line')].filter(l=>l.getAttribute('stroke')==='#2563eb'&&l.getAttribute('opacity')==='0.55'):[];
  ok('a whisker only for supported bins', whiskers.length===W.coolantSupported.filter(Boolean).length);
  const txt=svg?[...svg.querySelectorAll('text')].map(t=>t.textContent):[];
  ok('end labels for coolant and oil', txt.includes('coolant')&&txt.includes('oil'));
  const all=d.getElementById('root').textContent;
  ok('caption states coolant minus oil temperature difference and the composition note', /coolant minus oil, a temperature difference/.test(all)&&/bin composition/.test(all));
  ok('old wording absent (thermal lag attribution of the curve gap, mild-ambient sentence, mechanism claims)', !/the coolant.oil thermal lag \(time bins/.test(all)&&!/mild-ambient cold-starts/.test(all)&&!/gates truly-warm/.test(all)&&!/what makes short trips thermally costly/.test(all));
  ok('KM panel for the all cohort prints the ledger median of coolant 80 C', (()=>{const m=A.thermalSupportLedger.timeToThreshold.cohorts.all.coolant['80'].median; return all.includes('Kaplan-Meier (product-limit) estimate of the MEDIAN TIME TO THRESHOLD')&&(m.shown?all.includes(String(m.point)):true);})());
  const cb=d.querySelector('button[data-cohort-btn="cold"]');
  if(cb&&!cb.disabled){click(cb);await sleep(400);{ const rt=d.getElementById('root').textContent; ok('cold cohort (M648: it has a ledger entry, exploratory cells): Kaplan-Meier medians print the fixed short not-shown text, no reachers-only fallback', rt.includes('not shown (reason in the time-to-threshold panel)')&&!/MEDIAN OF REACHERS ONLY/.test(rt)&&!/estimate of the median is not computed for this cohort/.test(rt)); } }
  else console.log('skip cold cohort');
  // ---- Director condition (M624): the headline Kaplan-Meier panel never repeats the R5 reason sentence; a not-shown cell prints the fixed short text, once per cell
  const FIXED='not shown (reason in the time-to-threshold panel)', R5='cohort median not identifiable without an assumption on censoring';
  const kmPanel=()=>[...d.querySelectorAll('div')].filter(x=>x.textContent.startsWith('Kaplan-Meier (product-limit) estimate of the MEDIAN TIME TO THRESHOLD')).sort((a,b)=>a.textContent.length-b.textContent.length)[0]?.parentElement;
  for(const coh of ['all','warm','shoulder']){
    const b=d.querySelector(`button[data-cohort-btn="${coh}"]`); if(!b||b.disabled) continue; click(b); await sleep(400);
    const pn=kmPanel(); const cells=A.thermalSupportLedger.timeToThreshold.cohorts[coh]; let unshown=0;
    for(const fl of ['coolant','oil']) for(const t of ['60','70','80']){const m=cells?.[fl]?.[t]?.median; if(!m||!m.shown) unshown++;}
    const txt=pn?pn.textContent:'';
    ok(`${coh}: the headline panel has no R5 sentence and prints the fixed text once per not-shown cell (${unshown})`, !!pn && !txt.includes(R5) && txt.split(FIXED).length-1===unshown);
  }
  // ---- null bin: a second render with bin 3 of every coolantMedianC array set to null must split the blue polyline in two (no join across the gap)
  let h2=html,nrep=0;
  h2=h2.replace(/"coolantMedianC":\s*\[([^\]]*)\]/g,(m,inner)=>{const a=inner.split(',');if(a.length<5)return m;a[3]='null';nrep++;return '"coolantMedianC":['+a.join(',')+']';});
  ok('null-bin fixture: payload arrays found in the html', nrep>0);
  const dom2=new JSDOM(h2,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=()=>{};w.console.warn=()=>{}}});
  const d2=dom2.window.document;await sleep(1000);
  click2=el=>el.dispatchEvent(new dom2.window.MouseEvent('click',{bubbles:true}));
  click2([...d2.querySelectorAll('button')].find(b=>b.textContent.trim().toLowerCase()==='distribution'));await sleep(400);
  for(const b of [...d2.querySelectorAll('button')].filter(b=>/▸|▶|show|expand|more|details/i.test(b.textContent)&&b.getAttribute('aria-expanded')==='false')){click2(b);}
  await sleep(300);
  const cap2=[...d2.querySelectorAll('div')].find(x=>x.children.length===0&&x.textContent.startsWith('WARM-UP CURVES'));
  const blue=cap2&&cap2.nextElementSibling?[...cap2.nextElementSibling.querySelectorAll('polyline')].filter(l=>l.getAttribute('stroke')==='#2563eb'):[];
  ok('a null bin splits the coolant polyline into two segments', blue.length===2);
  console.log(fails?`FAILED ${fails}`:'ALL PASS');process.exit(fails?1:0);
})();
