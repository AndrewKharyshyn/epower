// test_stopgo_forest.js (M662, UI-05, spec analyses/M662_spec.md): the stop-go "by drive type" tiles get two forests (cycles per drive, engine starts per 10 min of stop-go):
// median with the interquartile range of drives (not a 95% interval; labelled so), values equal S.crawlStopGo.byDriveType at the printed precision, tiles behind ChartWithTable.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};this.port2={postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))}}}}
const html=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));
let fails=0;const ok=(label,c)=>{console.log((c?'PASS ':'FAIL ')+label);if(!c)fails++;};
const dom=new JSDOM(html,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=()=>{};w.console.warn=()=>{}}});
const d=dom.window.document,sleep=ms=>new Promise(r=>setTimeout(r,ms)),click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const BT=A.crawlStopGo.byDriveType, DT=['urban','mixed','mixed_highway','highway'].filter(k=>BT[k]&&BT[k].nDrives);
(async()=>{
  await sleep(1000);
  let host=null;
  const TABS=['overview','charts','fuel','distribution','highway vs city','thermal','records','health','cross-vehicle','conclusions'];
  for(const nm of TABS){ const b=[...d.querySelectorAll('button')].find(x=>x.textContent.trim().toLowerCase()===nm); if(!b) continue; click(b); await sleep(300); host=d.querySelector('[data-stopgo-dt-forest]'); if(host) break; }
  ok('forest block present',!!host); if(!host){process.exit(1);}
  const cw=host.closest('[data-chart-with-table]'); ok('inside ChartWithTable with the tiles behind the toggle',!!cw&&!!cw.querySelector('details')&&cw.querySelector('details').textContent.includes('cyc/drive'));
  // M788: the two forests became matching box plots by drive type (box = middle half of drives, median labelled, whisker to the 95th percentile)
  const fo=[...host.querySelectorAll('[data-box-rows]')]; ok('two box-plot panels',fo.length===2);
  ok('the key names the middle half of drives, the median and the 95th percentile',fo.every(f=>/middle half of drives/.test(f.textContent)&&/median/.test(f.textContent)&&/95th percentile/.test(f.textContent)));
  [['cyclesPerDrive',1],['startsPer10minStopGo',2]].forEach(([q,dp],fi)=>{ const rows=fo[fi]?[...fo[fi].querySelectorAll('[data-box-row]')]:[]; ok(q+': one row per drive type ('+DT.length+')',rows.length===DT.length);
    DT.forEach((k,i)=>{ const v=BT[k][q], r=rows[i]; if(!r) return; const fv=x=>Number(x).toFixed(x<10?1:0); ok(q+' '+k+': median label equals the payload and n is beside the group',r.querySelector('[data-box-median]').textContent===fv(v.median)&&r.textContent.includes(BT[k].nDrives+' drives')); }); });
  ok('flagged drive types are marked as short windows with the minutes shown',(A.crawlStopGo.smallDenominatorDriveTypes||[]).every(k=>fo[1].textContent.includes('(short window)')&&/min stop-go/.test(fo[1].textContent)));
  console.log(fails?'FAILED '+fails:'ALL PASS'); process.exit(fails?1:0);
})();
