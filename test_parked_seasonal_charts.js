// M791 (audit Wave B #11, owner plan 2026-11-27): the parked-time section shows a study-window strip (driving / parked / unassigned) and aligned driving-hours (filled) and parked-hours (hatched, grid range) bars by band; the seasonal section shows three small multiples with the earlier-assumption band. Values from S.parkedTimeBudget and S.seasonalFits.
const fs = require('fs'); const { JSDOM } = require('jsdom');
if (typeof globalThis.MessageChannel === 'undefined') { globalThis.MessageChannel = class { constructor() { this.port1 = { onmessage: null, postMessage: d => setImmediate(() => this.port2.onmessage && this.port2.onmessage({ data: d })) }; this.port2 = { onmessage: null, postMessage: d => setImmediate(() => this.port1.onmessage && this.port1.onmessage({ data: d })) }; } }; }
const HTML = fs.readFileSync(process.env.XT_HTML || 'xtrail_dashboard.html', 'utf8');
const A = JSON.parse(fs.readFileSync('summary_arrays.json', 'utf8')), P = A.parkedTimeBudget, F = A.seasonalFits;
const sleep = ms => new Promise(r => setTimeout(r, ms)); let fails = 0; const ok = (l, c) => { console.log((c ? 'PASS ' : 'FAIL ') + l); if (!c) fails++; };
const dom = new JSDOM(HTML, { runScripts: 'dangerously', pretendToBeVisual: true, beforeParse(w) { w.MessageChannel = globalThis.MessageChannel; w.console.error = () => {}; } });
const d = dom.window.document, click = el => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
(async () => {
  await sleep(900); click([...d.querySelectorAll('button')].find(b => b.textContent.trim().toLowerCase() === 'thermal')); await sleep(500);
  const pt = d.querySelector('[data-pt-chart]'); ok('parked-time chart block present', !!pt); if (!pt) process.exit(1);
  const ac = P.accounting, leg = pt.querySelector('[data-pt-legend]').textContent;
  ok('legend gives driving, parked and unassigned hours from the accounting', leg.includes(ac.drivingHours.toFixed(0) + ' h') && leg.includes(ac.parkedAssignedHours.toFixed(0) + ' h') && leg.includes(ac.unassignedGapHours.toFixed(0) + ' h'));
  const bands = P.B1.bands, drv = pt.querySelector('[data-hours-bars="drv"]'), prk = pt.querySelector('[data-hours-bars="prk"]');
  ok('one row per band in both panels (' + bands.length + ')', drv.querySelectorAll('[data-hours-row]').length === bands.length && prk.querySelectorAll('[data-hours-row]').length === bands.length);
  ok('bands the table does not show stay "not shown", never zero', bands.filter(b => b.status === 'not shown').length === prk.querySelectorAll('[data-hours-row="none"]').length);
  ok('parked bars are hatched, driving bars are filled', prk.innerHTML.includes('url(#hb-prk)') && !drv.innerHTML.includes('url(#hb-drv)'));
  const m = [...d.querySelectorAll('[data-mini-estimate]')]; ok('three small multiples', m.length === 3);
  ok('the consumption multiple carries the earlier-assumption band; the others do not', m[0].querySelector('[data-mini-band]') !== null && m[1].querySelector('[data-mini-band]') === null && m[2].querySelector('[data-mini-band]') === null);
  ok('fitted values printed from the payload', m[1].textContent.includes(F.Q2.primary.estimate.toFixed(2)) && m[2].textContent.includes(F.Q3.primary.tauH.toFixed(1)));
  console.log(fails ? 'PARKED SEASONAL CHART TEST FAILED' : 'PARKED SEASONAL CHART TEST PASSED'); process.exit(fails ? 1 : 0);
})();
