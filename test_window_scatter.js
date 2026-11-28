// M793 (analyses/M793_spec.md Rev 2): known-answer test of the pure scatter model windowScatterModel and a view test of the per-drive scatter in "How far the battery charge moves on a drive":
// one dot per drive with non-zero net swing, ranges only when lower < 0.8 x upper, a 1:1 line, the median-R line labelled "not a fitted line", printed counts, one stratum at a time.
const fs = require('fs');
const src = fs.readFileSync('xtrail_summary.jsx', 'utf8');
const m = src.match(/\/\*M793-MODEL-BEGIN\*\/([\s\S]*?)\/\*M793-MODEL-END\*\//); if (!m) { console.error('FAIL: model not found'); process.exit(1); }
const { windowScatterModel } = new Function(m[1] + ';return {windowScatterModel};')();
let f = 0; const t = (n, c) => { if (!c) { f++; console.log('FAIL', n); } else console.log('  ok:', n); };
const P = { kwhUpper: [0.5, 2, 0, 1], kwhLower: [0.5, 1.0, 0, 0.9], gross: [1, 8, 0.3, 3], durationS: [600, 1200, 60, 900], day: [0, 1, 1, 0], days: ['2026-01-01', '2026-01-02'] };
const M = windowScatterModel(P);
t('a zero-swing drive is counted and not drawn', M.nZero === 1 && M.nDrawn === 3 && M.points.every(p => p.x > 0));
t('a range is drawn only when lower < 0.8 x upper (drive 1: 1.0 < 1.6 yes; drive 3: 0.9 < 0.8 no)', M.nRange === 1 && M.points.find(p => p.i === 1).range === true && M.points.find(p => p.i === 3).range === false && M.points.find(p => p.i === 0).range === false);
t('the dot sits at the upper bracket and carries the date', M.points.find(p => p.i === 1).x === 2 && M.points.find(p => p.i === 1).day === '2026-01-02');
t('axes are whole decades covering every value (0.5 .. 8 -> 0.1 .. 10)', Math.abs(M.x0 - 0.1) < 1e-12 && M.x1 === 10 && M.ticks.length === 3);
t('empty and malformed input degrade', windowScatterModel(undefined).nDrawn === 0 && windowScatterModel({}).points.length === 0);
if (typeof globalThis.MessageChannel === 'undefined') { globalThis.MessageChannel = class { constructor() { this.port1 = { onmessage: null, postMessage: d => setImmediate(() => this.port2.onmessage && this.port2.onmessage({ data: d })) }; this.port2 = { onmessage: null, postMessage: d => setImmediate(() => this.port1.onmessage && this.port1.onmessage({ data: d })) }; } }; }
const { JSDOM } = require('jsdom');
const HTML = fs.readFileSync(process.env.XT_HTML || 'xtrail_dashboard.html', 'utf8');
const B = JSON.parse(fs.readFileSync('summary_arrays.json', 'utf8')).windowUse;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const dom = new JSDOM(HTML, { runScripts: 'dangerously', pretendToBeVisual: true, beforeParse(w) { w.MessageChannel = globalThis.MessageChannel; w.console.error = () => {}; } });
const d = dom.window.document, click = el => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
(async () => {
  await sleep(900); click([...d.querySelectorAll('button')].find(b => b.textContent.trim().toLowerCase() === 'records')); await sleep(400);
  for (const k of ['fast', 'slow']) {
    click(d.querySelector(`[data-window-stratum="${k}"]`)); await sleep(250);
    const D = B.strata[k], P = D.perDrive, sc = d.querySelectorAll('[data-window-scatter]');
    t(k + ': exactly one scatter is drawn (one stratum at a time)', sc.length === 1 && sc[0].getAttribute('data-window-scatter') === k);
    const nz = P.kwhUpper.filter(v => v > 0).length, dots = sc[0].querySelectorAll('[data-window-dot]');
    t(k + ': dots = drives with non-zero swing (' + nz + ') = throughputOverExcursion.nDrives', dots.length === nz && nz === D.throughputOverExcursion.nDrives);
    t(k + ': range dots = nRangeDrawn from the payload (' + P.nRangeDrawn + ')', sc[0].querySelectorAll('[data-window-dot="range"]').length === P.nRangeDrawn);
    t(k + ': 1:1 line and the median-R line are drawn, the latter says it is not a fitted line', !!sc[0].querySelector('[data-window-one-to-one]') && !!sc[0].querySelector('[data-window-r-line-draw]') && /not a fitted line/.test(sc[0].textContent));
    const note = sc[0].querySelector('[data-window-scatter-note]').textContent;
    t(k + ': note prints the counts and the two payload shares', note.includes(nz + ' drives drawn') && note.includes((100 * P.shareRAtMost1p05).toFixed(1) + ' %') && note.includes((100 * P.shareRBelow2).toFixed(1) + ' %') && note.includes(P.nLowerBelowUpper + ' drives have a gap-bounded'));
    t(k + ': no forbidden wording (capacity, usable, typical, efficiency, state of health)', !/capacity|usable|typical|efficien|state of health|measured/i.test(sc[0].textContent));
  }
  console.log(f ? 'WINDOW SCATTER TEST FAILED' : 'WINDOW SCATTER TEST PASSED'); process.exit(f ? 1 : 0);
})();
