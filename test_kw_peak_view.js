// M550 (analyses/M550_spec.md Rev 3): the kW view of the charge-rate risk map plots each drive at the T1 sample nearest its peak charge POWER sample (S.powerPeakTemperature.kwViewX); the A and C views keep the peak-current temperature.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port2.onmessage&&this.port2.onmessage({data:d}))};this.port2={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};}};}
const HTML=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));const B=A.powerPeakTemperature;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let fails=0;const ok=(label,c,extra)=>{console.log((c?'PASS ':'FAIL ')+label+((!c&&extra)?' - '+extra:''));if(!c)fails++;};
const errs=[];
const dom=new JSDOM(HTML,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=(...a)=>errs.push(a.join(' '));}});
const d=dom.window.document;const click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const btns=()=>[...d.querySelectorAll('button')];
const TABS=['overview','charts','fuel','distribution','highway vs city','thermal','records','health','cross-vehicle','conclusions'];
(async()=>{
  await sleep(900);
  const pts=A.cRatePointsAK;const tiers={};Object.values(B.kwViewX).forEach(v=>{tiers[v.tier]=(tiers[v.tier]||0)+1;});
  ok('payload: keyed map covers every plotted drive',pts.every(p=>p[5] in B.kwViewX)&&Object.keys(B.kwViewX).length===pts.length);
  ok('payload: known answers exact',JSON.stringify(B.knownAnswer.misses)===JSON.stringify({peakKw:0,peakI:0,t1PeakI:0}));
  let seen=false;
  for(const t of TABS){
    click(btns().find(b=>b.textContent.trim().toLowerCase()===t));await sleep(300);
    const kb=btns().find(b=>b.textContent.trim()==='Peak charge power (kW)');
    if(!kb)continue;
    seen=true;
    const ab=btns().find(b=>b.textContent.trim()==='Peak charge current (A)');click(ab);await sleep(200);
    const nA=d.querySelectorAll('svg circle').length;
    ok('A view: no kW tier markers or caption',d.querySelectorAll('[data-kw-tier]').length===0&&!d.querySelector('[data-kw-caption]'));
    click(kb);await sleep(300);
    const marks=[...d.querySelectorAll('circle[data-kw-tier]')];
    const n=(k)=>marks.filter(c=>c.getAttribute('data-kw-tier')===k).length;
    ok('kW view: every plotted drive carries a tier marker',marks.length===pts.length,String(marks.length));
    ok('kW view: tier counts equal the payload',n('cotimed')===(tiers.cotimed||0)&&n('nearby')===(tiers.nearby||0)&&n('late')===(tiers.late||0),JSON.stringify([n('cotimed'),n('nearby'),n('late'),tiers]));
    ok('kW view: late tier is hollow',marks.filter(c=>c.getAttribute('data-kw-tier')==='late').every(c=>c.getAttribute('fill')==='none'));
    ok('kW view: legend entry for the late tier',!!d.querySelector('[data-kw-late-legend]'));
    const cap=d.querySelector('[data-kw-caption]');
    ok('kW view: caption states tiers, the small-effect statement with n and the 1 degC resolution',!!cap&&cap.textContent.includes('small in this corpus')&&cap.textContent.includes(B.summary.dT1SignedKwMinusI.nDrives+' drives on '+B.summary.dT1SignedKwMinusI.nDays+' days')&&cap.textContent.includes('1 \u00B0C resolution')&&cap.textContent.includes('reconstructed I\u00D7V sample'),cap&&cap.textContent.slice(0,200));
    ok('kW view: no forbidden effect wording',!!cap&&!/no effect|negligible|identical|resolved/i.test(cap.textContent));
    ok('kW view: axis names the peak-power sample',d.getElementById('root').textContent.includes('nearest the peak charge power'));
    click(ab);await sleep(200);
    ok('back on A: the peak-current axis label returns',d.getElementById('root').textContent.includes('at the moment of peak charge current'));
    break;
  }
  ok('the risk map was found',seen);
  ok('no console errors',errs.length===0,errs.slice(0,2).join(' | '));
  console.log(fails?`test_kw_peak_view: ${fails} FAIL`:'test_kw_peak_view: OK');process.exit(fails?1:0);
})();
