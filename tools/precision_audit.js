// precision_audit.js - p16.7 scoping: per-LEAF-element rendered-text scan for numbers with long decimals.
// Reads xtrail_dashboard.html in jsdom (same harness as dump_tabs.js), visits every leaf element's OWN text
// (never concatenated table cells), and writes analyses/p16_7_precision_scan.json (counts by decimals,
// top offenders with tab/mode/element path). Read-only; no payload or dashboard change.
const fs = require('fs'); const { JSDOM } = require('jsdom');
if (typeof globalThis.MessageChannel === 'undefined') { globalThis.MessageChannel = class { constructor() { this.port1 = { onmessage: null, postMessage: d => setImmediate(() => this.port1.onmessage && this.port1.onmessage({ data: d })) }; this.port2 = { postMessage: d => setImmediate(() => this.port1.onmessage && this.port1.onmessage({ data: d })) }; } }; }
const html = fs.readFileSync(process.env.XT_HTML || 'xtrail_dashboard.html', 'utf8'); const errs = [];
const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, beforeParse(w) { w.MessageChannel = globalThis.MessageChannel; w.console.error = (...a) => errs.push(a.join(' ')); w.console.warn = () => {}; } });
const d = dom.window.document, sleep = ms => new Promise(r => setTimeout(r, ms)), click = el => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
const TABS = ['overview', 'charts', 'fuel', 'distribution', 'highway vs city', 'thermal', 'records', 'health', 'cross-vehicle', 'conclusions'];
const NUM = /(?<![\w.])-?\d[\d,]*\.(\d+)(?![\d])/g;
const hist = {}, seen = new Map();
function scan(tab, mode) {
  const root = d.getElementById('root');
  for (const el of root.querySelectorAll('*')) {
    if (['SCRIPT', 'STYLE'].includes(el.tagName)) continue;
    const own = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.nodeValue).join(' ');
    if (!own.trim()) continue;
    let m; NUM.lastIndex = 0;
    while ((m = NUM.exec(own))) {
      const dec = m[1].length; hist[dec] = (hist[dec] || 0) + 1;
      if (dec >= 4) {
        const k = tab + '|' + m[0] + '|' + own.trim().slice(0, 80);
        if (!seen.has(k)) seen.set(k, { tab, mode, value: m[0], decimals: dec, tag: el.tagName, text: own.trim().slice(0, 120) });
      }
    }
  }
}
(async () => {
  await sleep(800);
  const btns = () => [...d.querySelectorAll('button')];
  for (const t of TABS) {
    click(btns().find(b => b.textContent.trim().toLowerCase() === t)); await sleep(250);
    for (const b of btns().filter(b => !TABS.includes(b.textContent.trim().toLowerCase()) && !b.hasAttribute('data-cohort-btn') && !b.hasAttribute('data-cmp-btn') && /▸|▶|show|expand|more|details/i.test(b.textContent)).slice(0, 150)) { click(b); await sleep(3); }
    await sleep(120);
    for (const m of ['all', 'warm', 'shoulder']) {
      const b = d.querySelector(`button[data-cohort-btn="${m}"]`); if (!b || b.disabled) continue;
      click(b); await sleep(180); scan(t, m);
    }
    const a = d.querySelector('button[data-cohort-btn="all"]'); if (a) click(a); await sleep(120);
  }
  fs.mkdirSync('analyses', { recursive: true });
  const rows = [...seen.values()];
  fs.writeFileSync('analyses/p16_7_precision_scan.json', JSON.stringify({ decimalsHistogram: hist, nLongDecimal: rows.length, consoleErrors: errs.length, byTab: rows.reduce((a, r) => (a[r.tab] = (a[r.tab] || 0) + 1, a), {}), rows }, null, 1));
  console.log('histogram', JSON.stringify(hist), 'long(>=4 dec) distinct', rows.length, 'console errors', errs.length);
  process.exit(0);
})();
