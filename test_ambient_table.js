// test_ambient_table.js (M314) — renders xtrail_dashboard.html in jsdom, opens the Thermal tab and exercises the "Ambient Temperature per Drive" section:
// month -> date grouping, default state, expand/collapse all, search by date / "Sep 27" / time, and that every drive appears when fully expanded.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};this.port2={onmessage:null,postMessage:d=>setImmediate(()=>this.port2.onmessage&&this.port2.onmessage({data:d}))};const a=this.port1,b=this.port2;a.postMessage=d=>setImmediate(()=>b.onmessage&&b.onmessage({data:d}));b.postMessage=d=>setImmediate(()=>a.onmessage&&a.onmessage({data:d}));}};}
const html=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const arrays=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));
const T=arrays.ambientTable;const errs=[];
const dom=new JSDOM(html,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=(...a)=>errs.push(a.join(' '));}});
const d=dom.window.document,sleep=ms=>new Promise(r=>setTimeout(r,ms)),click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
let fails=0;const ok=(label,c)=>{console.log((c?'PASS ':'FAIL ')+label);if(!c)fails++;};
(async()=>{
  await sleep(800);
  click([...d.querySelectorAll('button')].find(b=>b.textContent.trim().toLowerCase()==='thermal'));await sleep(400);
  const root=d.querySelector('[data-amb-table]');
  ok('section present at the end of the Thermal tab', !!root);
  if(!root){process.exit(1);}
  const heads=[...d.querySelectorAll('h2')].map(h=>h.textContent.trim());
  ok('Ambient section is the LAST section of the Thermal tab', heads[heads.length-1]==='Ambient Temperature per Drive — Start / Interim / End');
  const months=[...new Set(T.rows.map(r=>r.d.slice(0,7)))], days=[...new Set(T.rows.map(r=>r.d))];
  ok(`one collapsible per month (${months.length})`, root.querySelectorAll('[data-amb-month]').length===months.length);
  const last=months[months.length-1];
  ok('latest month open, earlier months collapsed by default', [...root.querySelectorAll('[data-amb-month]')].every(m=>(m.querySelector('button').getAttribute('aria-expanded')==='true')===(m.getAttribute('data-amb-month')===last)));
  const lastDays=days.filter(x=>x.startsWith(last));
  ok(`latest month lists its ${lastDays.length} days, all collapsed (no data rows yet)`, root.querySelectorAll(`[data-amb-month="${last}"] [data-amb-date]`).length===lastDays.length && root.querySelectorAll('tbody tr').length===0);
  const btn=t=>[...root.querySelectorAll('button')].find(b=>b.textContent.trim()===t);
  click(btn('Expand all'));await sleep(200);
  ok(`Expand all shows every drive (${T.rows.length} rows)`, root.querySelectorAll('tbody tr').length===T.rows.length);
  const r0=T.rows.find(r=>r.a.length>2);
  const tr=[...root.querySelectorAll('tbody tr')].find(x=>x.textContent.includes(r0.t)&&x.closest('[data-amb-date]').getAttribute('data-amb-date')===r0.d);
  ok('a drive with interim readings shows start, every interim value and end', !!tr && r0.a.slice(1,-1).every(v=>tr.textContent.includes(String(v))) && tr.textContent.includes(String(r0.a[0])) && tr.textContent.includes(String(r0.a[r0.a.length-1])));
  click(btn('Collapse all'));await sleep(200);
  ok('Collapse all hides every data row', root.querySelectorAll('tbody tr').length===0);
  const inp=root.querySelector('input[type=search]');
  const type=v=>{Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype,'value').set.call(inp,v);inp.dispatchEvent(new dom.window.Event('input',{bubbles:true}));};
  const sample=days[days.length-2], [yy,mm,dd]=sample.split('-'), n=T.rows.filter(r=>r.d===sample).length;
  type(sample);await sleep(200);
  ok(`search "${sample}" opens that day with its ${n} drives`, root.querySelectorAll('[data-amb-date]').length===1 && root.querySelectorAll('tbody tr').length===n);
  const mon=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][+mm-1];
  type(`${mon} ${+dd}`);await sleep(200);
  ok(`search "${mon} ${+dd}" finds the same day`, root.querySelectorAll(`[data-amb-date="${sample}"]`).length===1 && root.querySelectorAll('tbody tr').length>=n);
  type('zzzz-no-match');await sleep(200);
  ok('no-match search shows an explicit empty message', root.textContent.includes('no drive matches this search') && root.querySelectorAll('[data-amb-date]').length===0);
  type('');await sleep(200);
  ok('clearing the search restores the collapsed view', root.querySelectorAll('tbody tr').length===0 && root.querySelectorAll('[data-amb-month]').length===months.length);
  ok('no console errors while interacting', errs.length===0);
  if(errs.length)console.log(errs.slice(0,3).join('\n'));
  console.log(fails?`FAILED ${fails}`:'AMBIENT TABLE TEST PASSED');process.exit(fails?1:0);
})();
