// test_regen_axes.js (M439, spec analyses/M439_spec.md Rev 2): renders xtrail_dashboard.html in jsdom, opens the Charts tab and checks the regeneration section in every available cohort:
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
// ---- reference (independent of the JSX): producer semantics in plain JS
const pyr=(x,d)=>{ if(d>0) return Number(x.toFixed(d)); const f=Math.floor(x); return Math.abs(x-f-0.5)<1e-12 ? (f%2===0?f:f+1) : Math.round(x); };
const T=A.seasonalCharts.charts.RegenByTempMeasured.data, SP=A.seasonalCharts.charts.RegenCaptureMeasured.data;
const dom=new JSDOM(html,{runScripts:'dangerously',pretendToBeVisual:true,beforeParse(w){w.MessageChannel=globalThis.MessageChannel;w.console.error=()=>{};w.console.warn=()=>{}}});
const d=dom.window.document,sleep=ms=>new Promise(r=>setTimeout(r,ms)),click=el=>el.dispatchEvent(new dom.window.MouseEvent('click',{bubbles:true}));
(async()=>{
  await sleep(800);
  click([...d.querySelectorAll('button')].find(b=>b.textContent.trim().toLowerCase()==='charts'));await sleep(400);
  const globalLabels=A.regenByTempMeasured.map(r=>r.label);
  for(const coh of ['all','warm','shoulder','cold']){
    const cb=d.querySelector(`button[data-cohort-btn="${coh}"]`);
    if(!cb||cb.disabled){console.log('skip cohort',coh,'(button absent or disabled)');continue;}
    click(cb);await sleep(250);
    const btn=t=>[...d.querySelectorAll('button')].filter(b=>b.textContent.trim()===t).pop();      // the regeneration view buttons come after the GTC chart's 'By Speed Zone' button
    const secEl=()=>{const h=[...d.querySelectorAll('h2')].find(x=>x.textContent.includes('Regenerative Energy Analysis'));return h?h.parentElement:d.body;};
    // temperature view
    if(!btn('By Battery Temperature')){ok(coh+': view buttons present',false);continue;}
    click(btn('By Battery Temperature'));await sleep(250);
    const svgT=d.querySelector('svg[data-regen-view="temp"]');
    ok(coh+': temperature chart rendered', !!svgT);
    if(svgT){
      const rowsT=T[coh]||[];
      const vals=rowsT.flatMap(r=>[r.eff, r.effRangeMassUncertainty?r.effRangeMassUncertainty[1]:null]).filter(v=>v!=null);
      const mx=Math.max(...vals), ymax=+svgT.getAttribute('data-ymax'), step=mx<60?10:20;
      ok(coh+`: y extent ${ymax} >= every displayed value (max ${mx}) and a multiple of ${step}`, ymax>=mx && ymax%step===0);
      ok(coh+': every global payload bin is drawn ('+globalLabels.length+')', +svgT.getAttribute('data-nbins')===globalLabels.length && globalLabels.every(l=>svgT.textContent.includes(l)));
      const valid=rowsT.filter(r=>r.valid);
      const text=d.body.textContent;
      if(valid.length){
        const mn=pyr(Math.min(...valid.map(r=>r.eff)),1), mxe=pyr(Math.max(...valid.map(r=>r.eff)),1);
        ok(coh+`: temperature caption states the cohort's value ~${mn===mxe?mn:mn+'–'+mxe}%`, text.includes(mn===mxe?`~${mn}%`:`~${mn}–${mxe}%`));
        ok(coh+': temperature caption names the cohort as a population filter when not All', coh==='all' || text.includes('a population filter, not a substitute for the battery temperature'));
      }
      if(!valid.length) ok(coh+': no valid temperature bin -> the caption says unavailable and the bars are drawn empty or dashed', text.includes('No temperature bin of this selection reaches the n≥200 validity gate: unavailable'));
      const covC=A.seasonalCharts.charts.RegenCaptureMeasured.coverage[coh];
      ok(coh+': the caption names the cohort'+(coh==='all'?'':` with its coverage (${covC.n_drives} drives, ${covC.km} km)`), text.includes(coh==='all'?'All drives':{warm:'Warm cohort',shoulder:'Shoulder cohort',cold:'Cold cohort'}[coh]+` (${covC.n_drives} drives`) && (coh==='all'||text.includes(`${covC.km} km)`)));
      ok(coh+': no undefined / empty-range artefact in the temperature view', !/undefined|~-%|NaN/.test(secEl().textContent));
      const cs=A.regenLegacySensitivity&&A.regenLegacySensitivity.cohorts[coh];
      if(cs){
        const ob=[...d.querySelectorAll('button')].find(b=>b.textContent.includes('Sensitivity of the apparent KE recovery to the extraction rule')&&b.getAttribute('aria-expanded')==='false'); if(ob){click(ob);await sleep(200);}
        const note=d.querySelector('[data-m440="note"]');
        const nTemp=Object.values(cs.variants).filter(v=>v.temp).length;
        ok(coh+': the sensitivity note is rendered in the temperature view with one row per variant that acts on it ('+nTemp+')', !!note && note.querySelectorAll('tbody tr').length===nTemp && note.textContent.includes('Material temperature bins (n≥200 under the legacy)'));
        const v6=cs.variants.V6_offset&&cs.variants.V6_offset.temp;
        if(note&&v6){ const bins=Object.entries(v6).filter(([b,r])=>r.decision!=='notEvaluable'&&typeof r.delta==='number'); const mat=Object.entries(v6).filter(([b,r])=>r.decision==='material'&&r.validLegacy).length;
          ok(coh+': the offset row states its material-bin count from the payload ('+mat+' of '+bins.length+' evaluable)', note.textContent.includes('Declared current offset applied') && note.textContent.includes(mat+' of '+bins.length+' evaluable')); }
      }
      ok(coh+': no retired wording in the temperature view', !/real data, not a model|Measured capture is a much flatter/.test(text));
    }
    // speed view
    click(btn('Apparent KE Recovery vs Speed'));await sleep(250);
    const svgS=d.querySelector('svg[data-regen-view="speed"]');
    ok(coh+': speed chart rendered', !!svgS);
    if(svgS){
      const rowsS=SP[coh]||[];
      const mx=Math.max(...rowsS.map(r=>r[1])), ymax=+svgS.getAttribute('data-ymax'), xmax=+svgS.getAttribute('data-xmax'), step=mx<60?10:20;
      ok(coh+`: speed y extent ${ymax} >= max ${mx}, multiple of ${step}; x extent ${xmax} covers the largest bin`, ymax>=mx && ymax%step===0 && xmax>=Math.max(...rowsS.map(r=>r[0])));
      const pl=rowsS.filter(r=>r[2]>=200 && r[0]>=25);
      if(pl.length){
        const lo=Math.min(...pl.map(r=>r[1])), hi=Math.max(...pl.map(r=>r[1])), loS=Math.min(...pl.map(r=>r[0])), hiS=Math.max(...pl.map(r=>r[0]));
        const text=d.body.textContent;
        ok(coh+`: speed caption "Between ${loS} and ${hiS} km/h the apparent ratio stays within ${lo}–${hi}%"`, text.includes(`Between ${loS} and ${hiS} km/h the apparent ratio stays within ${lo}–${hi}%`));
      }
      ok(coh+': no retired wording in the speed view', !/One series, all measured|Capture sits on a|upper-bounded proxy/.test(d.body.textContent));
    }
    // zone and type views
    click(btn('By Speed Zone'));await sleep(250);
    const svgZ=d.querySelector('svg[data-regen-view="zone"]');
    ok(coh+': zone chart rendered', !!svgZ);
    if(svgZ){
      const zr=(A.seasonalCharts.charts.RegenByZone.data[coh]||[]);const zm=Math.max(...zr.map(z=>z.pct||0)), zy=+svgZ.getAttribute('data-ymax'), zs=zm<60?10:20;
      ok(coh+`: zone y extent ${zy} >= max share ${zm} and a multiple of ${zs}`, zy>=zm && zy%zs===0);
      ok(coh+': no undefined / empty-range artefact in the zone view', !/undefined|~-%|NaN/.test(secEl().textContent));
    }
    click(btn('Charge Sources'));await sleep(250);
    ok(coh+': no undefined / literal-range artefact in the type view', !/undefined|~-%|NaN|roughly 0-51%/.test(secEl().textContent));
  }
  console.log(fails?`FAIL: ${fails} check(s) failed`:'OK test_regen_axes');
  process.exit(fails?1:0);
})();
