// Build xtrail_dashboard.html from xtrail_summary.jsx + the two JSON artefacts.
// In-browser Babel cannot resolve module imports, so we inline the JSON as
// consts and strip the import lines before transpiling the component code.
const fs=require('fs');
const babel=require('@babel/core');

let src=fs.readFileSync('xtrail_summary.jsx','utf8');

// ── JSX COMPONENT-CONTRACT GATE (2026-09-11, drift prevention) ──────────────
// The data-side REQUIRED_BLOCKS gate below verifies summary_arrays.json carries
// each dashboard-bound key. It does NOT verify that the JSX COMPONENT which
// renders a key is present and structurally intact. That gap allowed a silent
// regression: a session rebuilt the dashboard from a xtrail_summary.jsx whose
// §4b GeneratorTractionRecon() had reverted to a pre-revision body (Sankey +
// consolidated Key-findings/Limitations lost) while the generatorTractionRecon
// DATA was still present — so every data gate passed and the reverted section
// shipped. This gate asserts, per protected component, that its function
// definition AND a distinctive structural marker unique to the current revision
// are both present in the JSX source. A reverted/removed component fails the
// build loudly instead of rendering a stale section. Markers are chosen to be
// specific to the shipped revision (not just the function name), so a revert to
// an older body trips the gate even though the function name still exists.
const JSX_COMPONENT_CONTRACT=[
  // component-defining signature            // revision-distinctive marker(s)
  {name:'GeneratorTractionRecon', def:'function GeneratorTractionRecon()',
   markers:['function RTFlowSchematic','conserved cascade','◆ Key findings','⚠ Limitations','RTFlowSchematic F={F}'],
   note:'§4b Generator→Traction: Sankey + consolidated Key-findings/Limitations (M249)'},
];
const contractFailures=[];
for(const c of JSX_COMPONENT_CONTRACT){
  if(src.indexOf(c.def)<0){contractFailures.push(`${c.name}: definition "${c.def}" missing — ${c.note}`);continue;}
  const miss=c.markers.filter(m=>src.indexOf(m)<0);
  if(miss.length)contractFailures.push(`${c.name}: present but ${miss.length} structural marker(s) missing [${miss.join(' | ')}] — likely reverted to an older body. ${c.note}`);
}
if(contractFailures.length){
  console.error('BUILD ABORTED — JSX component-contract gate failed (a dashboard section reverted/regressed in xtrail_summary.jsx):');
  for(const f of contractFailures)console.error('  • '+f);
  console.error('Restore the current component body before building; do not ship a reverted section.');
  process.exit(1);
}
console.log(`JSX component-contract gate: ${JSX_COMPONENT_CONTRACT.length} protected component(s) intact.`);
// ────────────────────────────────────────────────────────────────────────────

const config=fs.readFileSync('summary_config.json','utf8');
// XT_ARRAYS / XT_OUT (M284): optional overrides so integration fixtures (e.g. the synthetic
// Cold-cohort test) can be built without touching the release artefacts.
const arrays=fs.readFileSync(process.env.XT_ARRAYS||'summary_arrays.json','utf8');
// M34: optional illustrative SoC-pattern asset (extract_soc_patterns.py);
// build degrades gracefully to null and the JSX section hides itself.
let socp='null';
try{socp=fs.readFileSync('soc_patterns.json','utf8');}catch(e){console.warn('soc_patterns.json absent — SoC-patterns section will be hidden');}

// strip ESM imports (react + json); provide them as globals instead
src=src.replace(/^\s*import\s+\{\s*useState\s*\}\s+from\s+"react";\s*$/m,'');
src=src.replace(/^\s*import\s+config\s+from\s+"\.\/summary_config\.json";\s*$/m,'');
src=src.replace(/^\s*import\s+arrays\s+from\s+"\.\/summary_arrays\.json";\s*$/m,'');
src=src.replace(/^\s*import\s+socPatterns\s+from\s+"\.\/soc_patterns\.json";\s*$/m,'');

// App is referenced as a global by the render call; drop the ESM export keyword
src=src.replace(/export\s+default\s+function\s+App/,'function App');

const {code}=babel.transformSync(src,{presets:[['@babel/preset-react',{runtime:'classic'}]],
  compact:false, comments:true});

// M57 (2026-07-27): inline the React UMD bundles instead of loading them from
// a CDN. The sandbox blocks outbound CDN traffic, so the CDN build could never
// be headlessly validated -- the jsdom gate silently rendered an empty root.
// NOTE String.replace with a STRING argument would corrupt these minified
// bundles via $& / $` metacharacters; they are interpolated, never substituted.
const reactUMD=fs.readFileSync('node_modules/react/umd/react.production.min.js','utf8');
const reactDomUMD=fs.readFileSync('node_modules/react-dom/umd/react-dom.production.min.js','utf8');

const arraysObj=JSON.parse(arrays);

// P0-5 (2026-07-30): required-block schema gate. These blocks are referenced
// by the dashboard and were previously produced out-of-band; a clean rebuild
// that silently dropped them left blank sections. Fail loud instead. Any block
// added to the JSX as a hard dependency should be listed here.
const REQUIRED_BLOCKS=[
  'meta','cycleCumulative','rfCycleCumulative','riskColdEngineBattery',
  'fadeModes','ledgerCrossCheck','eligibility','observedMix','offsetUncertainty',
  'degradationTrends',
  'contaminationSensitivity','determinism','constantProvenance',
  'gpsAltitudeCoverage','rawManifest','coverageMap','sessionLedgerAudit','powerFade','_provenance',
  'regenCaptureMeta','regenByTypeMeta','regenByZone','regenByTempMeasured',
  'crawlStopGo','accelDecelEnvelopes','rpmSpeedSync','engineStartContext','bufferDebtRecovery','drivingStateTaxonomy','departureArrival','engineStateMachine','thermalWarmupLag','socBalancedFuel','handoffSequence','cellSpreadRelaxation','vgtAirPath','highSocRegen','energyShifting','baroCompensation','auxLoadAmbient','fullCellCaseStudy','thermalFuelPenalty',
  // M253: generatorTractionRecon was never added here despite every other
  // raw-pass block above being listed -- the gap that let its loss (the
  // §4b regression this milestone restores) ship silently through a build
  // with zero errors. Added now so a future drop of this key aborts the
  // build loudly instead of rendering a blank section.
  'generatorTractionRecon',
  '_artifactStamps',
  'seasonalCharts',
  'evidenceLedger',
  'masterRefitAudit',
  'spreadFitProvenance',    // M317: Huber spread-fit provenance record (tools/record_spread_fit.py) referenced by the M19 block prose
  'ambientTable',           // M314: per-drive ambient temperatures for the Thermal tab table (tools/build_ambient_table.py)
  'masterRefitProvenance',  // M311: rebuild from the repository raw archive, labelled provenance sensitivity (tools/build_refit_provenance.py)
  'provenanceSensitivity'   // M307/F03: computed provenance-sensitivity notice (f03_provenance_flag.py)
];
const missing=REQUIRED_BLOCKS.filter(k=>arraysObj[k]==null);
if(missing.length){
  console.error('BUILD ABORTED — summary_arrays.json is missing required blocks: '+missing.join(', '));
  console.error('These are dashboard-bound; a build without them would render blank sections. '
    +'Regenerate summary_arrays.json with compute_summary_arrays.build_summary_arrays (P0-5).');
  process.exit(1);
}
// M94 (2026-08-07): stale-content gate. Historical/superseded keys are relocated
// to CHANGELOG.md and must never re-enter the production payload. Fails the build
// if any forbidden KEY appears at any depth of the two JSON artefacts. Key-based,
// not substring-in-value, so legitimate prose that names a historical key is fine.
// deprecated_synthetic is deliberately EXCLUDED: it is a live provenance mechanism.
const isForbiddenKey=k=>/_superseded/.test(k)||/^_auditRemediation/.test(k)||k==='_m62LedgerReconciliation';
function scanForbidden(o,path,hits){
  if(o&&typeof o==='object'){
    if(Array.isArray(o)){o.forEach((v,i)=>scanForbidden(v,`${path}[${i}]`,hits));}
    else{for(const k of Object.keys(o)){ if(isForbiddenKey(k)) hits.push(`${path}/${k}`); scanForbidden(o[k],`${path}/${k}`,hits);}}
  }
  return hits;
}
const stale=[...scanForbidden(JSON.parse(config),'config',[]),...scanForbidden(arraysObj,'arrays',[])];
if(stale.length){
  console.error('BUILD ABORTED — stale/superseded keys present in production JSON (relocate to CHANGELOG.md):');
  stale.forEach(p=>console.error('  '+p));
  process.exit(1);
}
// ── M177 (audit 2026-08-27, P0-02/P0-03): injected / carried-forward block gate ──
// crossVehicle, energyUncertaintyMC and socHysteresisV2 are produced OUTSIDE
// build_summary_arrays() -- crosscheck_vehicles.py / crosscheck_events.py inject
// crossVehicle, energy_uncertainty_mc.py injects energyUncertaintyMC, and
// socHysteresisV2 is carried forward (OOM-heavy refit). So "rebuild" does not
// equal "release" unless (a) each block is PRESENT and (b) its corpus basis is
// current or its staleness is DISCLOSED. This gate makes that an operator-visible,
// checked condition instead of a silent one. It FAILS only on a missing block or
// on stale-AND-undisclosed; a disclosed carry-forward (by design, e.g. M119-v2)
// WARNS but never blocks the build.
{
  const curN = (arraysObj.meta||{}).totalDrives;
  const curGross = (arraysObj.meta||{}).grossThroughputKwh;
  const injected = [
    { key:'crossVehicle',
      basis:o=>o&&o._meta&&o._meta.nPrimary, kind:'drives',
      disclosed:o=>!!(o&&o._meta) },
    { key:'socHysteresisV2',
      basis:o=>o&&o.nDrivesCovered, kind:'drives',
      // P0-03/M179: require the explicit, machine-checkable freeze stamp
      // (frozenBasis===true), not just recomputeMode string equality --
      // a sanctioned carry-forward must say so unambiguously, not just look
      // like one. Recomputation happens ONLY on the user's explicit demand
      // (recompute_m119v2=True); this gate never asks for or implies it.
      disclosed:o=>!!(o&&o.recomputeMode==='carriedForward'&&o.frozenBasis===true) },
    { key:'energyUncertaintyMC',
      basis:o=>o&&o.grossThroughputMC&&o.grossThroughputMC.nominalReleasedThroughputKwh, kind:'gross',
      disclosed:o=>!!(o&&o.grossThroughputMC&&o.grossThroughputMC.dataQualityNote) },
  ];
  const provFail=[], provWarn=[], provLog=[];
  for(const b of injected){
    const o=arraysObj[b.key];
    if(o==null){ provFail.push(`${b.key}: MISSING — injected/carried-forward block absent from payload `
      +`(crosscheck_*.py / energy_uncertainty_mc.py not run, or build_summary_arrays shipped alone).`); continue; }
    const basis=b.basis(o); let stale=false, drift='current';
    if(b.kind==='drives' && curN!=null && basis!=null){
      const d=curN-basis; stale=d>0;
      drift = stale ? `basis ${basis} drives vs current ${curN} (lags ${d})` : `basis ${basis} == current ${curN}`;
    } else if(b.kind==='gross' && curGross!=null && basis!=null){
      const d=+(curGross-basis).toFixed(2), pct=+(100*d/curGross).toFixed(2);
      stale=Math.abs(pct)>=0.5;
      drift = `nominal ${basis} kWh vs current ${curGross} kWh (${d>0?'+':''}${d} kWh, ${pct}%)`;
    }
    const disc=b.disclosed?b.disclosed(o):true;
    provLog.push(`  ${b.key}: ${drift}${stale?(disc?' [stale, disclosed]':' [STALE, UNDISCLOSED]'):''}`);
    if(stale&&!disc) provFail.push(`${b.key}: STALE & UNDISCLOSED — ${drift}. Regenerate the block or add an explicit staleness disclosure.`);
    else if(stale){
      // M285 (audit 2026-09-17 follow-up): a disclosed carry-forward whose corpus basis lags the
      // live corpus no longer passes silently. M119-v2 sat at 320/410 drives across M2xx releases
      // behind a disclosure flag while the dashboard read as current. It now FAILS unless the block
      // carries an explicit non-empty `staleWaiver` string (operator-signed) or XT_ALLOW_STALE_CARRY=1.
      const waiver=(o&&typeof o.staleWaiver==='string'&&o.staleWaiver.trim())?o.staleWaiver.trim():null;
      if(b.kind==='drives' && !waiver && process.env.XT_ALLOW_STALE_CARRY!=='1')
        provFail.push(`${b.key}: STALE (disclosed carry-forward not waived) — ${drift}. Recompute the block, `
          +`or set block.staleWaiver="<reason>" / XT_ALLOW_STALE_CARRY=1 to ship knowingly stale.`);
      else provWarn.push(`${b.key}: stale but disclosed${waiver?' + WAIVED ('+waiver+')':''} — ${drift}.`);
    }
  }
  console.log('release provenance — injected / carried-forward blocks (P0-02/P0-03):');
  provLog.forEach(l=>console.log(l));
  provWarn.forEach(w=>console.warn('WARN — '+w));
  if(provFail.length){
    console.error('BUILD ABORTED — injected-block provenance gate (P0-02/P0-03):');
    provFail.forEach(f=>console.error('  '+f));
    process.exit(1);
  }
  // ── P2-01 (audit 2026-08-28, M181): one consolidated release-provenance
  // object. Previously this gate's own findings (which blocks are stale,
  // by how much) existed only as build-time console output -- invisible to
  // anyone reading the shipped dashboard. constantProvenance, rawManifest,
  // _provenance and sessionLedgerAudit remain exactly where they were
  // (nothing renamed/moved, no existing S.* consumer breaks); this adds a
  // single pointer/summary object a reader can go to for "is this release
  // internally consistent right now", generated fresh on every build from
  // the same data the gate above already checked.
  const constantsUnverified = Object.entries(arraysObj.constantProvenance||{})
    .filter(([,v])=>v && v.verified===false).map(([k])=>k);
  arraysObj.releaseProvenance = {
    _note: 'Consolidated index (P2-01, M181), generated at build time from '
      +'the same checks as the provenance gate above. Does not replace or '
      +'move constantProvenance / rawManifest / _provenance / '
      +'sessionLedgerAudit -- see those keys directly for full detail.',
    generatedAt: new Date().toISOString(),
    pipelineVersion: (arraysObj._generated&&arraysObj._generated.pipeline_version)||'?',
    corpus: { totalDrives: curN, totalKm: curGross!=null ? (arraysObj.meta||{}).totalKm : null,
      dateRange: (arraysObj.meta||{}).dateRange, corpusMd5: (arraysObj.rawManifest||{}).corpusMd5 },
    injectedBlocks: injected.map(b=>{
      const o=arraysObj[b.key];
      const basis=o!=null?b.basis(o):null;
      const stale = o==null ? null
        : b.kind==='drives' && curN!=null && basis!=null ? (curN-basis)>0
        : b.kind==='gross' && curGross!=null && basis!=null ? Math.abs(100*(curGross-basis)/curGross)>=0.5
        : false;
      return { key:b.key, present:o!=null, basis, current: b.kind==='drives'?curN:curGross,
        stale, disclosed: o!=null && b.disclosed ? b.disclosed(o) : null };
    }),
    unverifiedConstants: constantsUnverified,
    unverifiedConstantsNote: constantsUnverified.length
      ? `${constantsUnverified.length} of ${Object.keys(arraysObj.constantProvenance||{}).length} tracked constants are unverified assumptions, not measured/OEM-confirmed values: ${constantsUnverified.join(', ')}. Every derived metric that scales with one of these carries that same lack of verification forward.`
      : 'All tracked constants verified.',
  };
}
// ── M220.2 (P0.4 closure): universal artifact hash-stamping staleness gate ──
// _artifactStamps carries a machine-checkable corpusHash (MD5 of
// drive_master.csv) on every top-level key, computed at build_summary_arrays()
// time. This gate re-computes drive_master.csv's LIVE MD5 at build_html.js
// time and FAILS the build (not warn) if any stamped key's corpusHash
// disagrees -- generalizing the pattern the crossVehicle/socHysteresisV2/
// energyUncertaintyMC provenance gate above already applies individually
// into a pipeline-wide check that covers every stamped key uniformly.
{
  const crypto=require('crypto');
  const stamps=arraysObj._artifactStamps;
  if(stamps==null){
    console.error('BUILD ABORTED — _artifactStamps missing (M220.2 universal hash-stamping gate). Regenerate summary_arrays.json with the current compute_summary_arrays.build_summary_arrays.');
    process.exit(1);
  }
  let liveMd5=null;
  try{
    const dmBuf=fs.readFileSync('drive_master.csv');
    liveMd5=crypto.createHash('md5').update(dmBuf).digest('hex');
    console.log(`artifact-stamp corpus-hash gate (M220.2): live drive_master.csv MD5: ${liveMd5}`);
  }catch(e){
    // M235 (audit F09): an unreadable master previously only logged a note
    // and SKIPPED the entire comparison below, silently passing a build
    // whose corpus identity could not actually be checked -- exactly the
    // "build with an absent master" case the audit names as one that
    // must NOT pass as a verified build. Fail closed instead.
    console.error(`BUILD ABORTED — drive_master.csv unreadable at build_html.js time (${e.message}); corpusHash staleness cannot be checked, so this cannot be verified as a current build (M235, audit F09).`);
    process.exit(1);
  }
  const mismatched=[], missingOrInvalid=[], skippedFallback=[];
  // M235 (audit F09): releaseProvenance is synthesized HERE, by
  // build_html.js, AFTER summary_arrays.json (and its Python-side
  // _artifactStamps) already exist -- it structurally cannot have a
  // Python-stamped entry by construction, not by omission. This is the
  // ONLY sanctioned exception; any other unstamped key is a real gap.
  const dataKeys=Object.keys(arraysObj).filter(k=>!k.startsWith('_') && k!=='releaseProvenance');
  for(const k of dataKeys){
    const st=stamps[k];
    if(!st || typeof st.corpusHash!=='string'){
      // M235 (audit F09): previously this loop iterated Object.keys(stamps)
      // itself, so a top-level array key with NO entry at all in
      // _artifactStamps was invisible to the gate -- not merely unchecked,
      // absent from consideration entirely. Iterating the actual data
      // keys and looking each one up catches that case too.
      missingOrInvalid.push(k); continue;
    }
    // Fallback-sourced stamps (drive_master.csv absent at ARRAY-build
    // time) were never computed from the on-disk file, so they are not
    // comparable to a live file MD5 -- flagged loudly below, not silently
    // accepted as a verified match, per the audit's explicit "build with
    // an absent master" failure case.
    if(st.corpusHashSource && !st.corpusHashSource.startsWith('file:')){
      skippedFallback.push(k); continue;
    }
    if(st.corpusHash!==liveMd5) mismatched.push(k);
  }
  if(missingOrInvalid.length){
    console.error('BUILD ABORTED — missing or invalid _artifactStamps entry (M235, audit F09):');
    console.error(`  ${missingOrInvalid.length} key(s) with no valid corpusHash stamp: `+missingOrInvalid.slice(0,10).join(', ')+(missingOrInvalid.length>10?` ... (+${missingOrInvalid.length-10} more)`:''));
    console.error('  Every top-level key must be stamped by _artifact_stamp(); regenerate summary_arrays.json.');
    process.exit(1);
  }
  if(skippedFallback.length){
    console.error(`BUILD ABORTED — ${skippedFallback.length} key(s) stamped via a non-file corpusHash fallback (drive_master.csv was absent when summary_arrays.json was built), so their corpus identity was never actually verified against an on-disk file (M235, audit F09): `+skippedFallback.slice(0,10).join(', ')+(skippedFallback.length>10?` ... (+${skippedFallback.length-10} more)`:''));
    console.error('  Regenerate summary_arrays.json with drive_master.csv present, or explicitly accept this as a degraded/dev build (not a publication build).');
    process.exit(1);
  }
  if(mismatched.length){
    console.error('BUILD ABORTED — stale _artifactStamps.corpusHash vs. live drive_master.csv (M220.2):');
    console.error(`  live MD5: ${liveMd5}`);
    console.error(`  ${mismatched.length} key(s) stamped with a different corpusHash: `+mismatched.slice(0,10).join(', ')+(mismatched.length>10?` ... (+${mismatched.length-10} more)`:''));
    console.error('  Regenerate summary_arrays.json (build_summary_arrays) against the current drive_master.csv, or investigate why the stamp disagrees.');
    process.exit(1);
  }
  console.log(`  ${dataKeys.length} stamped keys checked, all match the live corpus hash.`);
}
// non-fatal: flag hardcoded snapshot literals in JSX prose that should bind to S.*
const litRe=/\b\d{2,4}\s*drives?\b|\b\d{3,5}\s*(?:GTC|FCE)\b/gi; // km dropped: units/thresholds too noisy
const jsxLits=[...src.matchAll(litRe)].map(m=>m[0]).filter(s=>!/S\./.test(s));
if(jsxLits.length){console.warn('WARN — possible hardcoded snapshot literals in JSX (should bind to S.*): '+[...new Set(jsxLits)].slice(0,12).join(', '));}

const meta=arraysObj.meta||{};
const pv=(arraysObj._generated&&arraysObj._generated.pipeline_version)||'?';
const titleStats=`${meta.totalDrives??'?'} drives / ${(meta.totalKm??0).toFixed(1)} km, v${pv}`;

const html=`<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>X-Trail e-POWER — OBD Dashboard (${titleStats})</title>
<script>${reactUMD}</script>\n<script>${reactDomUMD}</script>
<style>*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}body{font-family:system-ui,sans-serif;background:#f8fafc;color:#1e293b;min-height:100vh}#root{max-width:760px;margin:0 auto;padding:16px}svg text{font-family:system-ui,sans-serif}button{font-family:inherit}</style>
</head><body><div id="root"></div>
<script>
const { useState } = React;
/* ── machine-generated data (inlined from summary_config.json + summary_arrays.json) ── */
const config = ${config};
const arrays = ${JSON.stringify(arraysObj)};
const socPatterns = ${socp};
${code}
const _root=ReactDOM.createRoot(document.getElementById("root"));
_root.render(React.createElement(App));
</script></body></html>`;

const _out=process.env.XT_OUT||'xtrail_dashboard.html';
fs.writeFileSync(_out,html);
console.log('wrote '+_out, (html.length/1024).toFixed(0)+'KB');
