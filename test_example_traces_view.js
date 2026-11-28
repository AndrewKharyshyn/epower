// M795 (analyses/M795_spec.md Rev 2): known-answer test of the pure trace helpers (gaps are breaks) and a view test of the three example traces: each is drawn once on its tab, bound to S.exampleTraces,
// labelled as one drive chosen by a fixed rule (not an average), shows the month only (no date, no file name), keeps the 400 rpm line, and carries no forbidden wording.
const fs = require('fs');
const src = fs.readFileSync('xtrail_summary.jsx', 'utf8');
const m = src.match(/\/\*M795-MODEL-BEGIN\*\/([\s\S]*?)\/\*M795-MODEL-END\*\//); if (!m) { console.error('FAIL: model not found'); process.exit(1); }
const { traceSegments, traceExtent } = new Function(m[1] + ';return {traceSegments,traceExtent};')();
let f = 0; const t = (n, c) => { if (!c) { f++; console.log('FAIL', n); } else console.log('  ok:', n); };
const sg = traceSegments([0, 1, 2, 3, 4, 5], [1, 2, null, 4, NaN, 6]);
t('a null or NaN second breaks the line into segments', sg.length === 3 && sg[0].length === 2 && sg[1].length === 1 && sg[2][0][0] === 5);
t('an all-null series has no segment', traceSegments([0, 1], [null, null]).length === 0 && traceSegments(undefined, undefined).length === 0);
const ex = traceExtent({ a: [2, 4, null], b: [10] }, ['a', 'b'], 0, null); t('extent covers every key and ignores nulls', ex[0] === 2 && ex[1] === 10);
t('a floor of zero is included', traceExtent({ a: [5, 9] }, ['a'], 0, 0)[0] === 0 && traceExtent({}, ['a']) === null);
if (typeof globalThis.MessageChannel === 'undefined') { globalThis.MessageChannel = class { constructor() { this.port1 = { onmessage: null, postMessage: d => setImmediate(() => this.port2.onmessage && this.port2.onmessage({ data: d })) }; this.port2 = { onmessage: null, postMessage: d => setImmediate(() => this.port1.onmessage && this.port1.onmessage({ data: d })) }; } }; }
const { JSDOM } = require('jsdom');
const HTML = fs.readFileSync(process.env.XT_HTML || 'xtrail_dashboard.html', 'utf8');
const B = JSON.parse(fs.readFileSync('summary_arrays.json', 'utf8')).exampleTraces;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const dom = new JSDOM(HTML, { runScripts: 'dangerously', pretendToBeVisual: true, beforeParse(w) { w.MessageChannel = globalThis.MessageChannel; w.console.error = () => {}; w.console.warn = () => {}; } });
const d = dom.window.document, click = el => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
(async () => {
  await sleep(900);
  const seen = {};
  for (const b of [...d.querySelectorAll('button')].filter(b => b.parentElement && b.parentElement.tagName !== 'DETAILS')) {
    const label = b.textContent.trim(); if (!/^[a-z][a-z &]+$/.test(label) || label.length > 40) continue;   // tab buttons only (cohort buttons start with a capital)
    click(b); await sleep(300);
    d.querySelectorAll('[data-example-trace]').forEach(e => { const k = e.getAttribute('data-example-trace'); if (!seen[k]) seen[k] = { tab: label, el: e }; });
    if (Object.keys(seen).length === 3) break;
  }
  for (const k of ['T7', 'T8', 'T9']) {
    const s = seen[k]; t(k + ': drawn on a tab (' + (s && s.tab) + ')', !!s); if (!s) continue;
    const e = s.el, T = B.traces[k], txt = e.textContent;
    t(k + ': one chart with the payload line count', e.querySelectorAll('[data-trace]').length === 1);
    const nPanels = e.querySelectorAll('[data-trace-panel]').length; t(k + ': panels = ' + nPanels, nPanels === { T7: 3, T8: 2, T9: 4 }[k]);
    t(k + ': month label only, no date or file name', txt.includes(T.month) && !/20\d\d-\d\d-\d\d/.test(txt) && !/\.csv/.test(txt) && !/\b\d{8}_\d{6}\b/.test(txt) && !/\b\d{1,2}:\d{2}(:\d{2})?\b/.test(txt));
    if (k !== 'T8') t(k + ': says one drive chosen by a fixed rule, not an average or representative', /chosen by a fixed rule/.test(txt) && /not an average or representative drive/.test(txt));
    else t('T8: labelled a record, the extreme run', /\(a record\)/.test(txt) && /not an example of the usual one/.test(txt));
    if (k !== 'T9') t(k + ': 400 rpm cutoff line drawn', /400 rpm cutoff/.test(e.querySelector('svg').textContent));
    t(k + ': no forbidden wording (typical, measured, generates, charges the battery, combustion shown)', !/typical|measured|engine charges|generating the|combustion (?:occurs|occurred|is shown)/i.test(txt));
    const keyed = k === 'T7' ? ['rpm', 'powerKw', 'coolantC'] : k === 'T8' ? ['speed', 'rpm'] : ['speed', 'pedal', 'powerKw', 'rpm'];
    const gaps = keyed.reduce((a, c) => a + (T[c].some(v => v === null) ? 1 : 0), 0);
    const polys = keyed.reduce((a, c) => a + e.querySelectorAll(`[data-trace-line="${c}"]`).length, 0);
    const segs = keyed.reduce((a, c) => a + traceSegments(T.t, T[c]).length, 0);
    t(k + ': one polyline per non-null segment (' + segs + '; ' + gaps + ' channels have gaps drawn as breaks)', polys === segs);
  }
  const s8 = seen.T8 && seen.T8.el; if (s8) { t('T8: the shaded run is drawn and the caption prints the run from the payload', !!s8.querySelector('[data-trace-span]') && s8.textContent.includes(B.traces.T8.run.km + ' km of integrated distance (odometer-scaled) in ' + B.traces.T8.run.durationS + ' s')); }
  const s9 = seen.T9 && seen.T9.el; if (s9) { t('T9: the peak annotation is bound to the payload', [...s9.querySelectorAll('[data-trace-mark]')].some(x => x.textContent.includes(B.traces.T9.peakKw.toFixed(1) + ' kW')) && /interpretation of the telemetry/.test(s9.textContent)); }
  const s7 = seen.T7 && seen.T7.el; if (s7) { t('T7: the denominators are printed (eligible of candidates)', s7.textContent.includes(B.selection.T7.eligible + ' of ' + B.selection.T7.candidates)); }
  console.log(f ? 'EXAMPLE TRACES TEST FAILED' : 'EXAMPLE TRACES TEST PASSED'); process.exit(f ? 1 : 0);
})();
