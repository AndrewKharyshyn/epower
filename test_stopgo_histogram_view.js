// M796 (analyses/M796_spec.md Rev 2): known-answer test of the pure model stopGoHistModel (panels, shares, small-n flags, frozen caption ladder) and a view test of the per-drive stop-and-go histograms:
// one panel per drive type with at least 2 drives, bar counts equal the payload, shared y scale, small-n panels print counts and "1 drive = x %", n < 10 shows a count list, drawn in the all-data view only, no forbidden wording.
const fs = require('fs');
const src = fs.readFileSync('xtrail_summary.jsx', 'utf8');
const m = src.match(/\/\*M796-MODEL-BEGIN\*\/([\s\S]*?)\/\*M796-MODEL-END\*\//); if (!m) { console.error('FAIL: model not found'); process.exit(1); }
const { stopGoHistModel } = new Function(m[1] + ';return {stopGoHistModel};')();
let f = 0; const t = (n, c) => { if (!c) { f++; console.log('FAIL', n); } else console.log('  ok:', n); };
const mk = (counts, over, extra = {}) => { const n = counts.reduce((a, b) => a + b, 0) + over; return { nDrives: n, counts, overflow: over, median: 3, p25: 2, p75: 5, fewDrives: n < 30, countListOnly: n < 10, oneDrivePct: +(100 / n).toFixed(2), ...extra }; };
const z = Array(21).fill(0);
const c1 = z.slice(); c1[0] = 20; c1[2] = 10; c1[12] = 4; const c2 = z.slice(); c2[1] = 3; c2[4] = 3;
const B = { bins: { max: 20 }, types: { urban: mk(c1, 3), highway: mk(c2, 0), unknown: mk(z.map((v, i) => (i === 0 ? 1 : 0)), 0) }, all: { nDrives: 40, median: 3, p25: 2, p75: 5, share0to2: 0.55, share10plus: 0.12 } };
const M = stopGoHistModel(B);
t('a type with one drive is not drawn but listed; the others are sorted by drive count', M.panels.length === 2 && M.panels[0].key === 'urban' && M.single.length === 1 && M.single[0].key === 'unknown');
t('bins are the 21 integer counts plus the overflow and shares are of the type\'s drives', M.panels[0].bins.length === 22 && Math.abs(M.panels[0].share[0] - 20 / 37) < 1e-12 && M.panels[0].bins[21] === 3);
t('the y maximum ignores count-list panels', Math.abs(M.yMax - 20 / 37) < 1e-12 && M.panels[1].listOnly === true);
t('the caption ladder adds the two phrases only above the frozen thresholds', /More than half of these drives have two or fewer cycles/.test(M.caption) && /At least one drive in ten has ten or more cycles/.test(M.caption));
const M2 = stopGoHistModel({ ...B, all: { ...B.all, share0to2: 0.34, share10plus: 0.07 } });
t('below the thresholds the caption is the numeric sentence only', !/More than half|At least one drive in ten/.test(M2.caption) && /34 % have 0 to 2 cycles, 7 % have 10 or more/.test(M2.caption));
t('malformed input degrades', stopGoHistModel(undefined).panels.length === 0 && stopGoHistModel({}).caption === null);
if (typeof globalThis.MessageChannel === 'undefined') { globalThis.MessageChannel = class { constructor() { this.port1 = { onmessage: null, postMessage: d => setImmediate(() => this.port2.onmessage && this.port2.onmessage({ data: d })) }; this.port2 = { onmessage: null, postMessage: d => setImmediate(() => this.port1.onmessage && this.port1.onmessage({ data: d })) }; } }; }
const { JSDOM } = require('jsdom');
const HTML = fs.readFileSync(process.env.XT_HTML || 'xtrail_dashboard.html', 'utf8');
const P = JSON.parse(fs.readFileSync('summary_arrays.json', 'utf8')).stopGoPerDrive;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const dom = new JSDOM(HTML, { runScripts: 'dangerously', pretendToBeVisual: true, beforeParse(w) { w.MessageChannel = globalThis.MessageChannel; w.console.error = () => {}; w.console.warn = () => {}; } });
const d = dom.window.document, click = el => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
(async () => {
  await sleep(900);
  let host = null, tab = null;
  for (const b of [...d.querySelectorAll('button')].filter(b => /^[a-z][a-z &]+$/.test(b.textContent.trim()) && b.textContent.trim().length <= 40)) {
    click(b); await sleep(300); const e = d.querySelector('[data-stopgo-hist]'); if (e) { host = e; tab = b.textContent.trim(); break; }
  }
  t('the histograms are drawn on a tab (' + tab + ')', !!host); if (!host) { console.log('STOPGO HISTOGRAM TEST FAILED'); process.exit(1); }
  const drawn = Object.entries(P.types).filter(([, v]) => v.nDrives >= 2);
  const panels = [...host.querySelectorAll('[data-stopgo-panel]')];
  t('one panel per drive type with at least 2 drives (' + drawn.length + ')', panels.length === drawn.length);
  for (const [k, v] of drawn) {
    const p = host.querySelector(`[data-stopgo-panel="${k}"]`); t(k + ': panel present with n in the title', !!p && p.textContent.includes(v.nDrives + ' drives'));
    if (!p) continue;
    if (v.countListOnly) { t(k + ': n < 10 shows a count list, not bars', !!p.querySelector('[data-stopgo-list]') && p.querySelectorAll('[data-stopgo-bar]').length === 0); continue; }
    const bars = [...p.querySelectorAll('[data-stopgo-bar]')];
    t(k + ': 22 bars whose counts equal the payload', bars.length === 22 && bars.every((b, i) => Number(b.getAttribute('data-stopgo-count')) === (i < 21 ? v.counts[i] : v.overflow)));
    t(k + ': the median marker is bound to the payload', !!p.querySelector(`[data-stopgo-median="${v.median}"]`));
    if (v.fewDrives) t(k + ': a small group prints "1 drive = x %"', /1 drive = /.test(p.textContent) && p.textContent.includes(String(v.oneDrivePct)));
  }
  const cap = host.querySelector('[data-stopgo-caption]').textContent;
  t('the caption prints the numeric sentence from the payload', cap.includes(P.all.nDrives + ' drives; median ' + P.all.median) && cap.includes((100 * P.all.share0to2).toFixed(0) + ' % have 0 to 2 cycles'));
  t('the caption says counts are per drive and not a comparison between types', /not per kilometre or per minute/.test(cap) && /no comparison between types is drawn/.test(cap));
  t('no forbidden wording (typically, measured, rate of the car, cause)', !/typically|measured|cause[sd]? |more cycles because/i.test(host.textContent));
  const cell = [...d.querySelectorAll('button')].find(b => /^Warm/.test(b.textContent.trim())); if (cell) { click(cell); await sleep(400); t('the histograms are not drawn in a cohort view', !d.querySelector('[data-stopgo-hist]')); }
  console.log(f ? 'STOPGO HISTOGRAM TEST FAILED' : 'STOPGO HISTOGRAM TEST PASSED'); process.exit(f ? 1 : 0);
})();
