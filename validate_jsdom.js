// jsdom 10-tab click-through validation for xtrail_dashboard.html.
// Follows the project's React-18/jsdom timing notes: MessageChannel polyfill
// via setImmediate, 800ms initial settle, 320ms inter-click, and
// dispatchEvent(MouseEvent{bubbles:true}) rather than .click().
const fs = require('fs');
const { JSDOM } = require('jsdom');

if (typeof globalThis.MessageChannel === 'undefined') {
  globalThis.MessageChannel = class {
    constructor() {
      this.port1 = { onmessage: null, postMessage: (d) => setImmediate(() => this.port1.onmessage && this.port1.onmessage({ data: d })) };
      this.port2 = { postMessage: (d) => setImmediate(() => this.port1.onmessage && this.port1.onmessage({ data: d })) };
    }
  };
}

const html = fs.readFileSync('xtrail_dashboard.html', 'utf8');
const errors = [];
const dom = new JSDOM(html, {
  runScripts: 'dangerously', pretendToBeVisual: true,
  beforeParse(w) {
    w.MessageChannel = globalThis.MessageChannel;
    const wrap = (fn) => (...a) => { errors.push(a.map(String).join(' ')); };
    w.console.error = wrap();
    w.console.warn = () => {};
    w.addEventListener('error', e => errors.push('window error: ' + (e.error ? e.error.stack : e.message)));
  },
});
const { window } = dom;
const doc = window.document;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const click = el => el.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));

(async () => {
  await sleep(800);
  const root = doc.getElementById('root');
  if (!root || root.textContent.trim().length < 200) {
    console.error('FAIL: #root did not render'); process.exit(1);
  }
  // tab buttons = the 10 capitalized nav buttons at the top
  const tabLabels = ['overview', 'charts', 'fuel', 'distribution', 'highway vs city', 'thermal',
                     'records', 'health', 'cross-vehicle', 'conclusions'];
  const allBtns = () => Array.from(doc.querySelectorAll('button'));
  const tabButtons = allBtns().filter(b => tabLabels.includes(b.textContent.trim().toLowerCase()));
  let tabsClicked = 0, innerClicked = 0;
  for (const lbl of tabLabels) {
    const btn = allBtns().find(b => b.textContent.trim().toLowerCase() === lbl);
    if (!btn) { console.error('FAIL: missing tab ' + lbl); continue; }
    click(btn); tabsClicked++; await sleep(320);
    // exercise inner buttons on this tab (selectors, view toggles) -- excludes
    // the nav buttons themselves
    const inner = allBtns().filter(b => !tabLabels.includes(b.textContent.trim().toLowerCase()));
    for (const ib of inner.slice(0, 40)) { click(ib); innerClicked++; await sleep(20); }
    await sleep(60);
  }
  await sleep(200);
  const v2 = doc.body.innerHTML.includes('P(engine start next second)') ||
             doc.body.innerHTML.includes('five-variable duration');
  console.log('tabs clicked:', tabsClicked, '/ 10; inner buttons clicked:', innerClicked);
  console.log('M119-v2 section rendered:', v2);
  console.log('console errors captured:', errors.length);
  errors.slice(0, 12).forEach(e => console.log('  ERR:', e.slice(0, 200)));

  // ============================================================
  // M207 (F-03 / F-17): SEMANTIC assertions. The runtime smoke test
  // above (render + clicks + console) passes a blank release-provenance
  // sentence; these checks assert scientific-content correctness.
  // ============================================================
  const semFail = [], semWarn = [];

  // -- (a) recover the inlined arrays object from the built HTML.
  // build_html.js injects `const arrays = <minified JSON>;` on its own line.
  let arraysObj = null;
  try {
    const line = html.split('\n').find(l => l.startsWith('const arrays = ') && l.trimEnd().endsWith(';'));
    if (!line) throw new Error('inlined `const arrays = ...;` line not found');
    arraysObj = JSON.parse(line.replace(/^const arrays = /, '').replace(/;\s*$/, ''));
  } catch (e) { semFail.push('could not parse inlined arrays object: ' + e.message); }

  if (arraysObj) {
    const meta = arraysObj.meta || {};
    const rp = arraysObj.releaseProvenance;

    // (b) F-02: releaseProvenance must exist and match the live corpus.
    if (!rp || typeof rp !== 'object') semFail.push('releaseProvenance ABSENT from inlined arrays (F-02 serialization regression)');
    else {
      if (!rp.corpus || rp.corpus.totalDrives !== meta.totalDrives)
        semFail.push(`releaseProvenance.corpus.totalDrives (${rp.corpus && rp.corpus.totalDrives}) != meta.totalDrives (${meta.totalDrives})`);
      // (c) any stale injected block must be disclosed (audit: visible badge or block release)
      (rp.injectedBlocks || []).forEach(b => {
        if (b.stale === true && b.disclosed !== true)
          semFail.push(`injected block '${b.key}' is STALE & UNDISCLOSED (${b.basis} vs ${b.current})`);
        else if (b.stale === true)
          semWarn.push(`injected block '${b.key}' stale but disclosed (${b.basis} vs ${b.current}) — pending regen`);
      });
    }

    // (d) F-05: raw<->master 1:1 must be verified, not null.
    const rm = arraysObj.rawManifest || {};
    if (rm.oneToOneVerified !== true)
      semFail.push(`rawManifest.oneToOneVerified is ${JSON.stringify(rm.oneToOneVerified)} (expected true)`);

    // (d2) F-14: determinism proof must be current (regenerated on this corpus).
    const det = arraysObj.determinism || {};
    if (det.nDrives !== meta.totalDrives)
      semFail.push(`determinism.nDrives (${det.nDrives}) != meta.totalDrives (${meta.totalDrives}) — stale determinism proof`);
    else if (det.canonicalN == null)
      semFail.push('determinism.canonicalN absent (F-14)');
    else
      console.log(`  SEM-OK: determinism proof current (nDrives=${det.nDrives}, canonicalSetReproducible=${det.canonicalSetReproducible})`);

    // (e) F-06: current-integral energy family is the metric-valid denominator.
    const fams = (arraysObj.eligibility && arraysObj.eligibility.families) || [];
    const intFam = fams.find(f => /Current-integral energy/.test(f.family || ''));
    if (!intFam) semFail.push('eligibility: Current-integral energy family missing');
    else if (intFam.headerSamplePresentN == null)
      semFail.push('eligibility current-integral family missing headerSamplePresentN (F-06 header/metric separation)');
    else if (intFam.n > intFam.headerSamplePresentN)
      semFail.push(`eligibility current-integral: metric-valid n=${intFam.n} exceeds sample-present ${intFam.headerSamplePresentN} (impossible)`);
    else
      console.log(`  SEM-OK: current-integral metric-valid ${intFam.n} <= sample-present ${intFam.headerSamplePresentN}`);
  }

  // (f) rendered-DOM hygiene: no leaked undefined/NaN/placeholder, no blank provenance.
  const rootText = (doc.getElementById('root') || {}).textContent || '';
  const badTokens = ['undefined', 'NaN', 'Infinity', '${'];
  badTokens.forEach(t => { if (rootText.includes(t)) semFail.push(`rendered DOM contains leaked token '${t}'`); });
  // blank release-provenance sentence: "... build time,  drives /  km, pipeline v."
  if (/build time,\s+drives\s*\/\s+km/.test(rootText))
    semFail.push('release-provenance sentence rendered BLANK (no corpus counts)');

  // (g) F-17-lite: stale corpus-literal scan of visible/inspectable strings.
  // Flags known stale snapshot literals in prose (NOT source comments, which
  // are stripped from the runtime). Reported as warnings — F-16/F-22 stale-prose
  // remediation is tracked separately.
  const staleLiterals = ['219 canonical', '219 primary', '74% highway', '289 drive', '277 energy'];
  const hayArrays = arraysObj ? JSON.stringify(arraysObj) : '';
  staleLiterals.forEach(s => {
    if (rootText.includes(s) || hayArrays.includes(s)) semWarn.push(`stale corpus literal present: '${s}'`);
  });

  // ============================================================
  // Phase-1 front-end: 5-mode seasonal cohort selector assertions.
  // ============================================================
  {
    const errBefore = errors.length;
    const cohortBtns = () => Array.from(doc.querySelectorAll('button[data-cohort-btn]'));
    const cb = cohortBtns();
    const modes = cb.map(b => b.getAttribute('data-cohort-btn'));
    if (cb.length !== 5) semFail.push(`cohort selector: expected 5 buttons, found ${cb.length} [${modes.join(',')}]`);
    ['all','compare','warm','shoulder','cold'].forEach(m => { if (!modes.includes(m)) semFail.push(`cohort selector: missing mode '${m}'`); });
    const byMode = m => cohortBtns().find(b => b.getAttribute('data-cohort-btn') === m);
    const coldBtn = byMode('cold');
    // M284 (audit #7): Cold availability is DERIVED from cohortCounts.cold and the declared
    // minimum-support rule (COHORT_MIN_SUPPORT_DRIVES in the JSX), not asserted as a constant.
    const minSup = +((fs.readFileSync('xtrail_summary.jsx', 'utf8').match(/COHORT_MIN_SUPPORT_DRIVES\s*=\s*(\d+)/) || [])[1]);
    const coldN = arraysObj && arraysObj.seasonalCharts && arraysObj.seasonalCharts._meta && arraysObj.seasonalCharts._meta.cohortCounts
      ? arraysObj.seasonalCharts._meta.cohortCounts.cold : null;
    if (!minSup) semFail.push('cohort selector: COHORT_MIN_SUPPORT_DRIVES not declared in JSX');
    else if (typeof coldN !== 'number') semFail.push('cohort selector: seasonalCharts._meta.cohortCounts.cold missing');
    else {
      const expectDisabled = coldN < minSup;
      if (coldBtn && coldBtn.disabled !== expectDisabled)
        semFail.push(`cohort selector: Cold disabled=${coldBtn.disabled} but cohortCounts.cold=${coldN} vs min support ${minSup} expects disabled=${expectDisabled}`);
    }
    click(byMode('all')); await sleep(120);
    if (byMode('all').getAttribute('aria-pressed') !== 'true') semFail.push('cohort selector: All Data not active by default/after click');
    click(byMode('compare')); await sleep(160);
    if (!doc.querySelector('[data-cohort-compare]')) semFail.push('cohort selector: Compare panel not rendered in compare mode');
    click(byMode('warm')); await sleep(160);
    if (byMode('warm').getAttribute('aria-pressed') !== 'true') semFail.push('cohort selector: Warm not active after click');
    if (doc.querySelector('[data-cohort-compare]')) semFail.push('cohort selector: Compare panel still present after leaving compare');
    click(byMode('all')); await sleep(120);
    // M284: cohort switching on EVERY tab (previously exercised only on the last-visited tab,
    // so chart-bearing tabs were never rendered in Compare/Warm/Shoulder mode by this gate).
    let kpiCiSeen = 0, ecdfSeen = 0, violinSeen = 0, violinShapes = 0;
    for (const t of tabLabels) {
      const tb = allBtns().find(b => b.textContent.trim().toLowerCase() === t); click(tb); await sleep(200);
      for (const m of ['compare', 'warm', 'shoulder', 'all']) {
        const b = byMode(m); if (!b || b.disabled) continue;
        const e0 = errors.length; click(b); await sleep(140);
        if (errors.length > e0) semFail.push(`cohort selector: console error on tab '${t}' in mode '${m}': ${errors[e0].slice(0, 120)}`);
        { const cl = doc.body.cloneNode(true); cl.querySelectorAll('script,style').forEach(x => x.remove()); const mm = (cl.textContent || '').match(/.{0,30}\\u[0-9a-fA-F]{4}.{0,15}/); if (mm) semFail.push(`literal unicode escape rendered on tab '${t}' mode '${m}': ...${mm[0]}...`); }
        if (m === 'compare') { kpiCiSeen += doc.querySelectorAll('[data-kpi-ci]').length; ecdfSeen += doc.querySelectorAll('[data-cmp-ecdf]').length; violinSeen += doc.querySelectorAll('[data-cmp-violin]').length; violinShapes += doc.querySelectorAll('[data-cmp-violin] polygon').length; }
      }
    }
    // M284: KPI forest-plot whiskers must render in Compare whenever the payload carries ci95
    const eiData = (((arraysObj.seasonalCharts || {}).charts || {}).EnergyIntensity || {}).data || {};
    const nCi = Object.values(eiData).filter(v => v && v.ci95).length;
    if (nCi > 0 && kpiCiSeen === 0) semFail.push('Compare KPI: payload carries ci95 for ' + nCi + ' cohort(s) but no CI whisker was rendered');
    // M285b: every payload-carried per-cohort interval on a MOUNTED Compare KPI block must reach the DOM
    // (EnergyIntensity 1 metric, GeneratorTractionRecon 5, EnergyPath 1, EvTraction 1; M285c: VgtAirPath, CellSpreadRelaxation, HandoffSequence 1 each). Compare series = Warm + Shoulder (All is the baseline,
    // Cold has no data). StartsPer100km carries a CI in the payload but is not mounted (superseded by EngineStartsByType).
    { const chs = ((arraysObj.seasonalCharts || {}).charts || {});
      const cnt = (k, per) => ['warm', 'shoulder'].filter(c => ((chs[k] || {}).data || {})[c] && chs[k].data[c].ci95).length * per;
      const cntB = (k, key) => ['warm', 'shoulder'].filter(c => { const b0 = ((chs[k] || {}).data || {})[c]; const b = b0 && b0[key]; return b && Array.isArray(b.ci95) && b.ci95.length === 2 && typeof b.nDays === 'number'; }).length;
      const expect = cnt('EnergyIntensity', 1) + cnt('GeneratorTractionRecon', 5) + cnt('EnergyPath', 1) + cnt('EvTraction', 1)
        + cntB('VgtAirPath', 'absTrackingErrorBoot') + cntB('CellSpreadRelaxation', 'relaxationMagnitudeBoot') + cntB('HandoffSequence', 'loadPointLagBoot')
        // M285d: remaining raw-pass KPIs
        + cntB('EnergyShifting', 'engineOnLowSpeedBoot') + cntB('EnergyShifting', 'netKwLowSpeedBoot')
        + cntB('HighSocRegen', 'engineOnShareBoot') + cntB('HighSocRegen', 'nonDeceleratingShareBoot')
        + cntB('CellSpreadRelaxation', 'loadedSpreadBoot') + cntB('CellSpreadRelaxation', 'relaxationHalfTimeBoot')
        + cntB('HandoffSequence', 'boostInvolvementBoot');
      if (kpiCiSeen < expect) semFail.push('Compare KPI: payload carries ' + expect + ' cohort-metric interval(s) on mounted blocks but only ' + kpiCiSeen + ' whisker(s) rendered across tabs');
      console.log('  CI-OK: ' + kpiCiSeen + ' whiskers rendered across Compare views (payload-expected minimum ' + expect + ')'); }
    const nEcdf = Object.keys((arraysObj.cohortDistributions || {}).metrics || {}).length;
    if (nEcdf > 0 && violinSeen === 0) semFail.push('Compare violin: payload carries ' + nEcdf + ' distribution metric(s) but no violin panel rendered');
    if (nEcdf > 0 && violinSeen > 0 && violinShapes === 0) semFail.push('Compare violin: panels rendered but no KDE shape drawn');
    if (nEcdf > 0 && ecdfSeen === 0) semFail.push('Compare ECDF: payload carries ' + nEcdf + ' distribution metric(s) but no ECDF panel rendered');
    const cohortErrs = errors.length - errBefore;
    if (cohortErrs > 0) semFail.push(`cohort selector: ${cohortErrs} console error(s) during cohort interactions`);
    console.log(`  COHORT-OK: ${cb.length} modes [${modes.join(',')}]; cold disabled=${!!(coldBtn && coldBtn.disabled)} (n=${coldN}, min ${minSup}); compare toggles; ${cohortErrs} errors`);
  }

  semWarn.forEach(w => console.log('  SEM-WARN:', w));
  semFail.forEach(f => console.log('  SEM-FAIL:', f));

  const hardFail = errors.length || tabsClicked !== 10 || semFail.length;
  if (hardFail) { console.error('VALIDATION FAILED'); process.exit(1); }
  console.log(`VALIDATION PASSED — 10 tabs, 0 console errors, ${semWarn.length} semantic warning(s)`);
  process.exit(0);
})();
