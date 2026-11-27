// M790 (audit Wave B #9, owner plan 2026-11-27): the out-of-time panel is titled "How well did the model work on later drives?" and draws paired observed / expected event-count bars for START and STOP. Values from S.socHysteresisV2.outOfTimeEvaluation (expected = observed / O/E).
const fs = require('fs'); const { JSDOM } = require('jsdom');
if (typeof globalThis.MessageChannel === 'undefined') { globalThis.MessageChannel = class { constructor() { this.port1 = { onmessage: null, postMessage: d => setImmediate(() => this.port2.onmessage && this.port2.onmessage({ data: d })) }; this.port2 = { onmessage: null, postMessage: d => setImmediate(() => this.port1.onmessage && this.port1.onmessage({ data: d })) }; } }; }
const HTML = fs.readFileSync(process.env.XT_HTML || 'xtrail_dashboard.html', 'utf8');
const E = JSON.parse(fs.readFileSync('summary_arrays.json', 'utf8')).socHysteresisV2.outOfTimeEvaluation;
const sleep = ms => new Promise(r => setTimeout(r, ms)); let fails = 0; const ok = (l, c) => { console.log((c ? 'PASS ' : 'FAIL ') + l); if (!c) fails++; };
const dom = new JSDOM(HTML, { runScripts: 'dangerously', pretendToBeVisual: true, beforeParse(w) { w.MessageChannel = globalThis.MessageChannel; w.console.error = () => {}; } });
const d = dom.window.document, click = el => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
(async () => {
  await sleep(900); let g = null;
  for (const nm of ['highway vs city', 'overview', 'charts', 'fuel', 'distribution', 'thermal', 'records', 'health']) { const b = [...d.querySelectorAll('button')].find(x => x.textContent.trim().toLowerCase() === nm); if (!b) continue; click(b); await sleep(350); g = d.querySelector('[data-obs-exp]'); if (g) break; }
  ok('observed / expected bars present', !!g); if (!g) process.exit(1);
  ok('plain title above the evaluation', /How well did the model work on later drives\?/.test(d.querySelector('[data-oot-title]').textContent) && /Out-of-time evaluation of the frozen design/.test(d.querySelector('[data-out-of-time]').textContent));
  ['start', 'stop'].forEach((k, i) => { const r = g.querySelectorAll('[data-obs-exp-row]')[i], e = E[k], exp = Math.round(e.later.events / e.OE.point);
    ok(k + ': observed ' + e.later.events + ', expected ' + exp + ' and the ratio ' + e.OE.point.toFixed(2) + ' with its interval are printed', !!r && r.textContent.includes(e.later.events + ' observed') && r.textContent.includes(exp + ' expected') && r.textContent.includes(e.OE.point.toFixed(2)) && r.textContent.includes(e.OE.ci95[0].toFixed(2)) && r.textContent.includes(e.later.nDrives + ' later drives, ' + e.later.nDays + ' days')); });
  console.log(fails ? 'OOT OBS-EXP TEST FAILED' : 'OOT OBS-EXP TEST PASSED'); process.exit(fails ? 1 : 0);
})();
