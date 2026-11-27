// test_fuel_stopped_redesign.js (M778, Wave 0/A of the dashboard rework): the Fuel tab block "Fuel used while stopped" leads with one sentence, a 100% strip and a
// dot chart of the stopped share by trip length; every number equals S.fuelStates.groups (lead and strip at 1 dp, bands at 1 dp), the old forest and tables stay
// available behind the "How we calculated it" disclosure.
const fs = require('fs'); const { JSDOM } = require('jsdom');
if (typeof globalThis.MessageChannel === 'undefined') { globalThis.MessageChannel = class { constructor() { this.port1 = { onmessage: null, postMessage: d => setImmediate(() => this.port2.onmessage && this.port2.onmessage({ data: d })) }; this.port2 = { onmessage: null, postMessage: d => setImmediate(() => this.port1.onmessage && this.port1.onmessage({ data: d })) }; } }; }
const html = fs.readFileSync(process.env.XT_HTML || 'xtrail_dashboard.html', 'utf8');
const A = JSON.parse(fs.readFileSync('summary_arrays.json', 'utf8'));
let fails = 0; const ok = (label, c) => { console.log((c ? 'PASS ' : 'FAIL ') + label); if (!c) fails++; };
const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, beforeParse(w) { w.MessageChannel = globalThis.MessageChannel; w.console.error = () => {}; w.console.warn = () => {}; } });
const d = dom.window.document, sleep = ms => new Promise(r => setTimeout(r, ms)), click = el => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
const G = A.fuelStates.groups, p1 = v => (v * 100).toFixed(1);
(async () => {
  await sleep(1000);
  click([...d.querySelectorAll('button')].find(b => b.textContent.trim().toLowerCase() === 'fuel')); await sleep(500);
  const lead = d.querySelector('[data-fuel-states-lead]'); ok('lead block present', !!lead); if (!lead) process.exit(1);
  const a = G.all, t = lead.querySelector('p').textContent;
  ok('lead states the overall stationary share and its interval (1 dp)', t.includes(p1(a.stationaryShare.est) + '%') && t.includes(p1(a.stationaryShare.ci95[0]) + '%') && t.includes(p1(a.stationaryShare.ci95[1]) + '%'));
  ok('lead states the trip and day counts', t.includes(a.nTrips + ' trips') && t.includes(a.nDays + ' days'));
  const strip = lead.querySelector('[data-share-strip]'); ok('100% strip present with a text alternative', !!strip && /moving/.test(strip.getAttribute('aria-label')));
  ok('strip carries stationary and moving shares', strip.getAttribute('aria-label').includes(p1(a.stationaryShare.est) + '%') && strip.getAttribute('aria-label').includes(p1(a.movingShare.est) + '%'));
  const bands = ['band 0.5-2', 'band 2-5', 'band 5-10', 'band 10-20', 'band 20+'].filter(k => G[k]);
  const rows = [...lead.querySelectorAll('[data-fuel-states-bands] [data-forest-row]')];
  ok('one dot row per trip-length band (' + bands.length + ')', rows.length === bands.length);
  bands.forEach((k, i) => { const s = G[k].stationaryShare, r = rows[i]; if (!r) return;
    ok(k + ': value, interval, trips and days equal the payload', r.textContent.includes(p1(s.est)) && r.textContent.includes(p1(s.ci95[0])) && r.textContent.includes(p1(s.ci95[1])) && r.textContent.includes(G[k].nTrips + ' trips') && r.textContent.includes(G[k].nDays + ' days')); });
  const labs = [...lead.querySelectorAll('[data-fuel-states-bands] [data-dot-label]')];
  ok('each dot carries its value as a label above it (' + bands.length + ' labels)', labs.length === bands.length && bands.every((k, i) => labs[i] && labs[i].textContent === p1(G[k].stationaryShare.est) + '%'));
  const notes = d.querySelector('[data-fuel-states]').querySelector('details.xt-notes'); ok('the detailed groups, definitions and sensitivities sit behind the disclosure', !!notes && !!notes.querySelector('[data-fuel-states-forest]'));
  console.log(fails ? 'FAILED ' + fails : 'ALL PASS'); process.exit(fails ? 1 : 0);
})();
