// M787 (owner request 2026-11-27, audit Wave A #5): the cell-spread relaxation sensitivity panel draws, per cadence group, the published rule and every pairing / fill / gap variant and the placebo as dots with day-clustered intervals on one axis; the table moves behind "Show table". Values from S.cellSpreadRelaxationSensitivity.
const fs = require('fs'); const { JSDOM } = require('jsdom');
if (typeof globalThis.MessageChannel === 'undefined') { globalThis.MessageChannel = class { constructor() { this.port1 = { onmessage: null, postMessage: d => setImmediate(() => this.port2.onmessage && this.port2.onmessage({ data: d })) }; this.port2 = { onmessage: null, postMessage: d => setImmediate(() => this.port1.onmessage && this.port1.onmessage({ data: d })) }; } }; }
const HTML = fs.readFileSync(process.env.XT_HTML || 'xtrail_dashboard.html', 'utf8');
const B = JSON.parse(fs.readFileSync('summary_arrays.json', 'utf8')).cellSpreadRelaxationSensitivity;
const sleep = ms => new Promise(r => setTimeout(r, ms)); let fails = 0; const ok = (l, c) => { console.log((c ? 'PASS ' : 'FAIL ') + l); if (!c) fails++; };
const dom = new JSDOM(HTML, { runScripts: 'dangerously', pretendToBeVisual: true, beforeParse(w) { w.MessageChannel = globalThis.MessageChannel; w.console.error = () => {}; } });
const d = dom.window.document, click = el => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
(async () => {
  await sleep(900); click([...d.querySelectorAll('button')].find(b => b.textContent.trim().toLowerCase() === 'distribution')); await sleep(500);
  for (const k of Object.keys(B.strata)) {
    const c = d.querySelector(`[data-csr-chart="${k}"]`); ok(k + ': chart drawn', !!c); if (!c) continue;
    const st = B.strata[k], n = 1 + Object.keys(st.familyA_fixedWindows).length + Object.keys(st.familyB_windowSet).length + 1;
    ok(k + ': one row per variant (' + n + ')', c.querySelectorAll('[data-forest-row]').length === n);
    ok(k + ': reference median and interval printed', c.textContent.includes(st.V0.median.toFixed(2) + ' (' + st.V0.ci95[0].toFixed(2) + ', ' + st.V0.ci95[1].toFixed(2) + ')'));
    ok(k + ': table kept behind Show table', !!d.querySelector(`[data-csr-stratum="${k}"] details table`) && !!d.querySelector(`[data-csr-row="${k}-V0"]`));
  }
  console.log(fails ? 'CSR CHART TEST FAILED' : 'CSR CHART TEST PASSED'); process.exit(fails ? 1 : 0);
})();
