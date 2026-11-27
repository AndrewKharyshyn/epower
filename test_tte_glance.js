// M789 (audit Wave B #4, owner plan 2026-11-27): the warm-up panel opens with one lead sentence, an observed-share chart (coolant 80 C, oil 70 C; 5, 10 and 15 minutes) on one axis, an "If the drive continued" switch adding the Kaplan-Meier estimate, and a reached / trip ended / sensor lost strip. Values from S.thermalSupportLedger.timeToThreshold.cohorts.all.
const fs = require('fs'); const { JSDOM } = require('jsdom');
if (typeof globalThis.MessageChannel === 'undefined') { globalThis.MessageChannel = class { constructor() { this.port1 = { onmessage: null, postMessage: d => setImmediate(() => this.port2.onmessage && this.port2.onmessage({ data: d })) }; this.port2 = { onmessage: null, postMessage: d => setImmediate(() => this.port1.onmessage && this.port1.onmessage({ data: d })) }; } }; }
const HTML = fs.readFileSync(process.env.XT_HTML || 'xtrail_dashboard.html', 'utf8');
const K = JSON.parse(fs.readFileSync('summary_arrays.json', 'utf8')).thermalSupportLedger.timeToThreshold.cohorts.all;
const sleep = ms => new Promise(r => setTimeout(r, ms)); let fails = 0; const ok = (l, c) => { console.log((c ? 'PASS ' : 'FAIL ') + l); if (!c) fails++; };
const dom = new JSDOM(HTML, { runScripts: 'dangerously', pretendToBeVisual: true, beforeParse(w) { w.MessageChannel = globalThis.MessageChannel; w.console.error = () => {}; } });
const d = dom.window.document, click = el => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
const pct = v => (100 * v).toFixed(0) + ' %';
(async () => {
  await sleep(900); let g = null;
  for (const nm of ['overview', 'charts', 'fuel', 'distribution', 'highway vs city', 'thermal', 'records']) { const b = [...d.querySelectorAll('button')].find(x => x.textContent.trim().toLowerCase() === nm); if (!b) continue; click(b); await sleep(350); g = d.querySelector('[data-tte-glance]'); if (g) break; }
  ok('glance block present', !!g); if (!g) process.exit(1);
  const c10 = K.coolant['80'].horizons.find(h => h.h === 600).E1.point, o10 = K.oil['70'].horizons.find(h => h.h === 600).E1.point;
  const lead = g.querySelector('[data-tte-glance-lead]').textContent;
  ok('lead sentence gives the observed 10-minute shares for coolant 80 and oil 70', lead.includes(pct(c10) + ' had reached coolant 80') && lead.includes(pct(o10) + ' had reached oil 70'));
  ok('observed view: six rows (two fluids x 5, 10, 15 min)', g.querySelectorAll('[data-forest-row]').length === 6);
  click(g.querySelector('[data-tte-km="true"]')); await sleep(250);
  ok('"If the drive continued" adds the Kaplan-Meier rows (12)', d.querySelector('[data-tte-glance]').querySelectorAll('[data-forest-row]').length === 12 && /informative about comparable drives that stopped/.test(d.querySelector('[data-tte-glance]').textContent));
  const strip = g.querySelector('[data-tte-glance-strip]'); ok('support strip has one row per fluid and names sensor loss', strip.querySelectorAll('svg > g').length === 2 && /sensor readings lost/.test(strip.textContent + strip.innerHTML));
  console.log(fails ? 'TTE GLANCE TEST FAILED' : 'TTE GLANCE TEST PASSED'); process.exit(fails ? 1 : 0);
})();
