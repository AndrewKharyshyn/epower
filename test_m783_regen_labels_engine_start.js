// test_m783_regen_labels_engine_start.js (M783, owner requests 2026-11-27): (1) the apparent KE recovery vs speed chart of the Regenerative Energy section prints each dot's value above it
// (value equals the day-clustered estimate of the cell, 1 dp; a thin cell is marked with ~); (2) the "Engine-start rate (RPM onsets), pooled ratio of sums" block no longer repeats the four drive-class
// rows that the starts chart above already draws as pooled diamonds: its All view lists the thermal cohorts (All data, Warm, Shoulder, Cold when supported), says what the block adds, and keeps the
// detector definition, first-onset split, coolant bands and sensitivity behind "How we calculated it".
const fs = require('fs'); const { JSDOM } = require('jsdom');
if (typeof globalThis.MessageChannel === 'undefined') { globalThis.MessageChannel = class { constructor() { this.port1 = { onmessage: null, postMessage: d => setImmediate(() => this.port2.onmessage && this.port2.onmessage({ data: d })) }; this.port2 = { onmessage: null, postMessage: d => setImmediate(() => this.port1.onmessage && this.port1.onmessage({ data: d })) }; } }; }
const html = fs.readFileSync(process.env.XT_HTML || 'xtrail_dashboard.html', 'utf8');
const A = JSON.parse(fs.readFileSync('summary_arrays.json', 'utf8'));
let fails = 0; const ok = (label, c) => { console.log((c ? 'PASS ' : 'FAIL ') + label); if (!c) fails++; };
const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, beforeParse(w) { w.MessageChannel = globalThis.MessageChannel; w.console.error = () => {}; w.console.warn = () => {}; } });
const d = dom.window.document, sleep = ms => new Promise(r => setTimeout(r, ms)), click = el => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
(async () => {
  await sleep(1000);
  click([...d.querySelectorAll('button')].find(b => b.textContent.trim().toLowerCase() === 'charts')); await sleep(600);
  // (1) regeneration speed chart
  const panel = d.querySelector('[data-regen-v2="panel"][data-regen-view="efficiency"]'); ok('the speed view is the default regeneration view', !!panel); if (!panel) process.exit(1);
  const labs = [...panel.querySelectorAll('[data-regen-dot-label="speed"]')]; ok('dot labels present on the speed view', labs.length > 0);
  const groups = [...panel.querySelectorAll('svg g')].filter(g => g.querySelector(':scope > [data-regen-dot-label]') && g.querySelector(':scope > title'));
  ok('every labelled dot has a label equal to its estimate (1 dp, ~ for a thin cell)', groups.length === labs.length && groups.every(g => { const t = g.querySelector('title').textContent, m = t.match(/:\s*(-?[\d.]+) %/); const l = g.querySelector('[data-regen-dot-label]').textContent; return !!m && l.replace('~', '') === Number(m[1]).toFixed(1) + '%'; }));
  const dots = [...panel.querySelectorAll('svg circle')].filter(c => c.getAttribute('r')); ok('one label per plotted dot', dots.length >= labs.length);
  // (2) engine-start block
  const blk = d.querySelector('[data-engine-start-rate]'); ok('engine-start block present', !!blk); if (!blk) process.exit(1);
  const E = A.engineStartRate, P = E.primary, coldOpen = !!P.cold;
  const rows = [...blk.querySelectorAll('[data-forest-row]')].map(r => r.textContent);
  const want = ['All data', 'Warm', 'Shoulder'].concat(coldOpen ? ['Cold'] : []);
  ok('the All view lists the thermal cohorts (' + want.join(', ') + ')', rows.length === want.length && want.every((w, i) => rows[i].includes(w)));
  ok('no drive-class row repeats the pooled diamonds of the starts chart', !/class:/i.test(blk.textContent) && !rows.some(r => /urban|mixed|highway/i.test(r)));
  ok('each cohort row carries the payload estimate (1 dp)', want.every((w, i) => { const e = P[w === 'All data' ? 'all' : w.toLowerCase()]; return rows[i].includes(w + Number(e.est).toFixed(1)); }));
  ok('the block says what it adds and where the class rates are', /pooled rate for each drive class is the diamond in the starts chart above/.test(blk.querySelector('[data-engine-start-purpose]').textContent));
  const notes = blk.querySelector('details.xt-notes'); ok('detector, first-onset split, coolant bands and sensitivity sit behind the disclosure', !!notes && /Detector: engine speed above/.test(notes.textContent) && /First onset in a log file versus later onsets/.test(notes.textContent) && /Detector-defined count/.test(notes.textContent) && /onsets by engine-coolant temperature/.test(notes.textContent));
  const cls = [...d.querySelectorAll('[data-starts-pooled]')]; ok('the starts chart still draws the pooled class diamonds', cls.length >= 4);
  console.log(fails ? 'FAILED ' + fails : 'ALL PASS'); process.exit(fails ? 1 : 0);
})();
