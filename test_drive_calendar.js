// test_drive_calendar.js (M663, UI-05, spec analyses/M663_spec.md): known-answer test of driveCalendarModel and a render check of the Sessions calendar heatmap
// (one square per day, n equals the number of S.ambientTable.rows with that date, total equals the drive count, day table behind ChartWithTable).
const fs=require('fs');const {JSDOM}=require('jsdom');
const src=fs.readFileSync('xtrail_summary.jsx','utf8');
const m=src.match(/\/\*M663-MODEL-BEGIN\*\/([\s\S]*?)\/\*M663-MODEL-END\*\//); if(!m){console.error('FAIL: model not found');process.exit(1);}
const driveCalendarModel=new Function(m[1]+';return driveCalendarModel;')();
let fails=0;const ok=(label,c)=>{console.log((c?'PASS ':'FAIL ')+label);if(!c)fails++;};
// known answer: 2026-11-01 is a Sunday, 2026-11-02 a Monday
const k=driveCalendarModel(['2026-11-01','2026-11-01','2026-11-02','bad',null,'2026-11-09']);
ok('total counts valid dates only',k.total===4&&k.days.length===3&&k.max===2);
ok('weeks start on Monday: first column is 2026-10-26..2026-11-01',k.weeks[0][0].date==='2026-10-26'&&k.weeks[0][6].date==='2026-11-01'&&k.weeks[0][6].n===2);
ok('days before the first logged day are out of range, Sunday 2026-11-01 is in range',k.weeks[0][5].inRange===false&&k.weeks[0][6].inRange===true);
ok('three weeks, 2026-11-02 sits in the second column Monday with n=1',k.weeks.length===3&&k.weeks[1][0].date==='2026-11-02'&&k.weeks[1][0].n===1&&k.weeks[2][0].n===1&&k.weeks[1][1].n===0);
ok('empty input gives an empty model',driveCalendarModel([]).weeks.length===0);
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};this.port2={postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))}}}}
const html=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));
const dom=new JSDOM(html,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=()=>{};w.console.warn=()=>{}}});
const d=dom.window.document,sleep=ms=>new Promise(r=>setTimeout(r,ms)),click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const cnt={}; A.ambientTable.rows.forEach(r=>{cnt[r.d]=(cnt[r.d]||0)+1;});
(async()=>{
  await sleep(1000);
  let host=null;
  for(const nm of ['overview','charts','fuel','distribution','highway vs city','thermal','records','health','cross-vehicle','conclusions']){ const b=[...d.querySelectorAll('button')].find(x=>x.textContent.trim().toLowerCase()===nm); if(!b) continue; click(b); await sleep(300); host=d.querySelector('[data-drive-calendar]'); if(host) break; }
  ok('calendar present',!!host); if(!host){process.exit(1);}
  const cells=[...host.querySelectorAll('[data-cal-day]')]; const days=Object.keys(cnt);
  ok('one square per calendar day from first to last logged day (>= '+days.length+' logged days)',cells.length>=days.length);
  ok('every logged day carries its drive count',days.every(dd=>{const c=cells.find(x=>x.getAttribute('data-cal-day')===dd);return c&&+c.getAttribute('data-cal-n')===cnt[dd];}));
  ok('squares sum to the drive count ('+A.ambientTable.rows.length+')',cells.reduce((a,c)=>a+ +c.getAttribute('data-cal-n'),0)===A.ambientTable.rows.length);
  const cw=host.closest('[data-chart-with-table]'); ok('day table behind the toggle',!!cw&&!!cw.querySelector('details table')&&cw.querySelectorAll('details tbody tr').length===days.length);
  console.log(fails?'FAILED '+fails:'ALL PASS'); process.exit(fails?1:0);
})();
