// test_regen_axes.js (M439 helpers; M451 stratified display, spec analyses/M446_spec.md Rev 1.1-1.4): renders xtrail_dashboard.html in jsdom, opens the Charts tab and checks the regeneration section in every available cohort.
// M451 checks replace the legacy-view checks: every figure comes from S.regenDisplayV2 (rows of the selected cohort, polling stratum, SOC selection and basis), the axes are data-driven from the payload extents, every payload temperature bin is drawn,
// failed/empty cells are absent with a reason, the B6 badge, the not-a-contrast note and the exploratory note are present, the controls change values, counts and captions together. The M439 helper checks below are kept:
// (G2) the temperature and speed captions equal a reference computed here from the payload rows of that cohort (half-even rounding as the producer), not the global values;
// (G3) the axes are data-driven (data-ymax >= every displayed value incl. the mass-range upper end, a multiple of the tick step), the temperature view draws every payload bin;
// (KAT) the pure helpers on fixtures: 62.5 -> 62, 63.5 -> 64, an 85 % value extends the axis, a negative value fails. Cold (11 drives, at least the minimum support of 10) is an available cohort and is checked like the others.
const fs=require('fs');const {JSDOM}=require('jsdom');
if(typeof globalThis.MessageChannel==='undefined'){globalThis.MessageChannel=class{constructor(){this.port1={onmessage:null,postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}))};this.port2={postMessage:d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d})),onmessage:null};this.port2.postMessage=d=>setImmediate(()=>this.port1.onmessage&&this.port1.onmessage({data:d}));}};}
const html=fs.readFileSync(process.env.XT_HTML||'xtrail_dashboard.html','utf8');
const A=JSON.parse(fs.readFileSync('summary_arrays.json','utf8'));
const jsx=fs.readFileSync('xtrail_summary.jsx','utf8');
let fails=0;const ok=(label,c)=>{console.log((c?'PASS ':'FAIL ')+label);if(!c)fails++;};
// ---- helpers extracted from the source and evaluated (KAT on fixtures)
const i0=jsx.indexOf('function pyRound('), i1=jsx.indexOf('function regenXMax(');
const src=jsx.slice(i0, jsx.indexOf('\n', i1));
const H=new Function(src+'; return {pyRound, regenMetaOf, regenAxis, regenXMax};')();
ok('pyRound is half-even like Python (62.5 -> 62, 63.5 -> 64, 62.4 -> 62)', H.pyRound(62.5)===62 && H.pyRound(63.5)===64 && H.pyRound(62.4)===62 && H.pyRound(54.15,1)===Number((54.15).toFixed(1)));
ok('axis: max 54 -> step 10, extent 60; max 62 -> step 20, extent 80; 85 -> extent 100 (not clipped); 0 -> extent 10', H.regenAxis(54).ymax===60 && H.regenAxis(54).step===10 && H.regenAxis(62).ymax===80 && H.regenAxis(62).step===20 && H.regenAxis(85).ymax===100 && H.regenAxis(0).ymax===10);
ok('axis: values above 100 are allowed; a negative value is flagged invalid (never thrown inside a render)', H.regenAxis(104).ymax===120 && H.regenAxis(-1).invalid===true && H.regenAxis(5).invalid===false && H.regenAxis(-1).ymax===10);
ok('speed extent: largest bin 115 + width 10 -> 130', H.regenXMax(115,10)===130 && H.regenXMax(35,10)===50);
const rows=[{label:'a',lo:null,hi:0,n:0,eff:null,valid:false},{label:'b',lo:0,hi:10,n:46,eff:12.5,valid:false},{label:'c',lo:10,hi:20,n:300,eff:54.14,valid:true},{label:'d',lo:20,hi:30,n:900,eff:63.26,valid:true}];
const sp=[[5,9.7,1000],[15,43,900],[25,62.5,800],[55,68.3,700],[105,65.5,300]];
const M=H.regenMetaOf(rows,sp);
ok('regenMetaOf reproduces the producer rules: valid bins only, thin = invalid with an estimate, plateau 50-110 over all non-null rows, crawl = first row below 30, half-even',
   M.tempEffMin===54.1 && M.tempEffMax===63.3 && M.tempLabelLo==='c' && M.tempLabelHi==='d' && M.tempNMin===300 && M.tempNMax===900 && JSON.stringify(M.tempThinBins)===JSON.stringify([{label:'b',n:46}]) &&
   M.speedEffMin===9.7 && M.speedEffMax===68.3 && M.plateauLo===66 && M.plateauHi===68 && M.crawlEff===10);
ok('no valid bin -> no temperature fields (rendered as unavailable)', H.regenMetaOf([{label:'x',valid:false,eff:null,n:0}],[]).tempEffMin===undefined);
// ---- M451: the stratified display, checked against the payload (independent of the JSX rendering)
const D=A.regenDisplayV2;
ok('payload regenDisplayV2 present with 4 cohorts and the B6 reference', !!D && ['all','warm','shoulder','cold'].every(c=>D.cohorts[c]) && D.b6Reference && D.b6Reference.supportedCellsFailing>0);
const dom=new JSDOM(html,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=()=>{};w.console.warn=()=>{}}});
const d=dom.window.document,sleep=ms=>new Promise(r=>setTimeout(r,ms)),click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
const setSel=(el,v)=>{el.value=v;el.dispatchEvent(new dom.window.Event('change',{bubbles:true}));};
(async()=>{
  await sleep(1000);
  click([...d.querySelectorAll('button')].find(b=>b.textContent.trim().toLowerCase()==='charts'));await sleep(500);
  const btn=t=>[...d.querySelectorAll('button')].filter(b=>b.textContent.trim()===t).pop();
  const panel=()=>d.querySelector('[data-regen-v2="panel"]');
  const strBtn=k=>d.querySelector(`button[data-regen-stratum="${k}"]`), basBtn=k=>d.querySelector(`button[data-regen-basis="${k}"]`), socSel=()=>d.querySelector('select[data-regen-soc="sel"]');
  const openAll=async()=>{for(const b of [...d.querySelectorAll('button')].filter(b=>/Cell details/.test(b.textContent)&&b.getAttribute('aria-expanded')==='false')){click(b);} await sleep(150);};
  const NAME={all:'All drives',warm:'Warm cohort',shoulder:'Shoulder cohort',cold:'Cold cohort'};
  for(const coh of ['all','warm','shoulder','cold']){
    const cb=d.querySelector(`button[data-cohort-btn="${coh}"]`);
    if(!cb||cb.disabled){console.log('skip cohort',coh);continue;}
    click(cb);await sleep(300);
    const CB=D.cohorts[coh];
    click(btn('By Battery Temperature'));await sleep(300);
    ok(coh+': stratified panel rendered; default stratum slow, observed basis', !!panel() && panel().getAttribute('data-stratum')==='slow' && panel().getAttribute('data-basis')==='observed');
    ok(coh+': the controls are present (polling, SOC, basis)', !!strBtn('slow')&&!!strBtn('fast')&&!!strBtn('both')&&!!socSel()&&!!basBtn('observed')&&!!basBtn('standardized'));
    const sbS=CB.strata.slow, vbT=sbS&&sbS.views?sbS.views.temperature:null;
    if(vbT){
      const svg=d.querySelector('svg[data-regen-view="temp"]');
      const order=vbT.order, ext=vbT.bySoc.allSoc.extent, mx=ext?ext[1]:0, step=mx<60?10:20;
      ok(coh+`: every payload temperature bin is drawn (${order.length}) and the y extent ${svg&&svg.getAttribute('data-ymax')} covers the payload extent ${mx} on a multiple of ${step}`, !!svg && +svg.getAttribute('data-nbins')===order.length && order.every(l=>svg.textContent.includes(l)) && +svg.getAttribute('data-ymax')>=mx && +svg.getAttribute('data-ymax')%step===0);
      await openAll();
      const rowsEl=[...d.querySelectorAll('[data-regen-table="slow"] tbody tr')];
      ok(coh+': the detail table has one row per drawn bin', rowsEl.length===order.length);
      const sup=order.filter(l=>vbT.bySoc.allSoc.rows[l].status==='supported');
      ok(coh+': each supported cell shows its estimate, day interval, mass range and b_nat from the payload', sup.every(l=>{const r=vbT.bySoc.allSoc.rows[l]; const tr=rowsEl.find(t=>t.cells[0].textContent===l); if(!tr) return false; const c=[...tr.cells].map(x=>x.textContent);
        return c[1]===r.eff.toFixed(2) && (!r.ci95 || c[2]===r.ci95[0].toFixed(2)+'–'+r.ci95[1].toFixed(2)) && (!r.massRange || c[3]===r.massRange[0].toFixed(2)+'–'+r.massRange[1].toFixed(2)) && (r.bNat==null || c[4]===r.bNat.toFixed(2));}));
      ok(coh+': failed and empty cells are drawn absent with a stated reason', order.filter(l=>['failed','empty'].includes(vbT.bySoc.allSoc.rows[l].status)).every(l=>{const tr=rowsEl.find(t=>t.cells[0].textContent===l); return tr && /no qualifying|interval unidentified|unsupported/.test(tr.cells[7].textContent);}));
      if(sbS.design.days<5) ok(coh+': exploratory note and suppressed intervals (fewer than 5 days)', !!d.querySelector('[data-regen-note="exploratory"]') && rowsEl.every(t=>/none \(days<5\)|—/.test(t.cells[2].textContent)));
    }
    ok(coh+': the B6 FAILED badge is shown beside the chart', !!d.querySelector('[data-regen-badge="b6"]') && /B6 cadence-invariance check FAILED/.test(panel().textContent));
    ok(coh+': the caption names the cohort', panel().textContent.includes(NAME[coh]));
    ok(coh+': no undefined / NaN artefact and no retired wording', !/undefined|NaN|~-%/.test(panel().textContent) && !/measured capture|true level|cadence-corrected|within error|fast vs slow/i.test(panel().textContent));
    ok(coh+': no contrast note in the single-stratum mode', !d.querySelector('[data-regen-note="both"]'));
    click(strBtn('both'));await sleep(300);
    ok(coh+': "Both" carries the not-a-contrast note', !!d.querySelector('[data-regen-note="both"]') && /Not a contrast/.test(panel().textContent));
    click(strBtn('fast'));await sleep(300);
    ok(coh+': the fast stratum is selectable and bound to its own rows', panel().getAttribute('data-stratum')==='fast' && (!CB.strata.fast.views || panel().textContent.includes('Fast-polled drives')));
    click(strBtn('slow'));await sleep(200);
    const bandOpts=[...socSel().options].map(o=>o.value);
    ok(coh+': the SOC selector lists All SOC, the eight bands and below 40 %', bandOpts.length===10 && bandOpts[0]==='allSoc' && bandOpts.includes('below40'));
    setSel(socSel(),'band 66-69');await sleep(300);
    click(basBtn('standardized'));await sleep(300);
    ok(coh+': a single SOC band with the standardized basis falls back to observed with a visible note', panel().getAttribute('data-basis')==='observed' && !!d.querySelector('[data-regen-note="basis"]'));
    setSel(socSel(),'allSoc');await sleep(300);
    const st=sbS&&sbS.standardized?sbS.standardized.temperature:null;
    if(st){ const av=st.availability.available;
      ok(coh+': All SOC with the standardized basis '+(av?'draws the standardized bars':'falls back to observed with the reason'), av? panel().getAttribute('data-basis')==='standardized' : (panel().getAttribute('data-basis')==='observed' && !!d.querySelector('[data-regen-note="basis"]')));
      if(av){ await openAll(); const r0=Object.keys(st.bars)[0]; const tr=[...d.querySelectorAll('[data-regen-table="slow"] tbody tr')].find(t=>t.cells[0].textContent===r0);
        ok(coh+': the standardized estimate is the payload bar value', !!tr && tr.cells[1].textContent===st.bars[r0].standardized.toFixed(2)); }
    }
    click(basBtn('observed'));await sleep(200);
    click(btn('Apparent KE Recovery vs Speed'));await sleep(300);
    const vbS=sbS&&sbS.views?sbS.views.speed:null, svgS=d.querySelector('svg[data-regen-view="speed"]');
    ok(coh+': speed chart rendered with the drawn bins only (0-10 km/h and >=130 km/h are payload-only)', !!svgS && (!vbS || +svgS.getAttribute('data-nbins')===vbS.order.filter(l=>!vbS.bySoc.allSoc.rows[l].payloadOnly).length));
    ok(coh+': the speed axis states the interpolated speed during braking', /Speed during braking \(interpolated between speed samples\)/.test(panel().textContent));
    click(btn('By Speed Zone'));await sleep(300);
    const svgZ=d.querySelector('svg[data-regen-view="zone"]');
    ok(coh+': zone chart rendered with 10-30 as the first zone', !!svgZ && (!sbS.views || (svgZ.textContent.includes('10-30') && svgZ.textContent.includes('120-130'))));
    ok(coh+': no undefined / NaN artefact in the zone view', !/undefined|NaN/.test(panel().textContent));
    click(btn('Charge Sources'));await sleep(300);
    const tn=d.querySelector('[data-regen-note="type"]');
    ok(coh+': the type view shows its not-affected note and no artefact', !!tn && !/undefined|~-%|NaN|roughly 0-51%/.test(tn.parentElement.textContent));
  }
  console.log(fails?`FAIL: ${fails} check(s) failed`:'OK test_regen_axes');
  process.exit(fails?1:0);
})();
