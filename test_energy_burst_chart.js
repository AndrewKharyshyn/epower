// M785 (owner request 2026-11-27): the Records-tab section "How much energy moves in one charge or discharge burst" draws median / p90 / p99 run energy as dots with intervals on a log axis,
// a complete-runs versus lower-bound switch, and the count share versus energy share of runs below 1 Wh. Values come from S.energyPackets only.
const fs = require('fs'); const { JSDOM } = require('jsdom');
if (typeof globalThis.MessageChannel === 'undefined') { globalThis.MessageChannel = class { constructor() { this.port1 = { onmessage: null, postMessage: d => setImmediate(() => this.port2.onmessage && this.port2.onmessage({ data: d })) }; this.port2 = { onmessage: null, postMessage: d => setImmediate(() => this.port1.onmessage && this.port1.onmessage({ data: d })) }; } }; }
const HTML = fs.readFileSync(process.env.XT_HTML || 'xtrail_dashboard.html', 'utf8');
const B = JSON.parse(fs.readFileSync('summary_arrays.json', 'utf8')).energyPackets;
const sleep = ms => new Promise(r => setTimeout(r, ms)); let fails = 0; const ok = (l, c) => { console.log((c ? 'PASS ' : 'FAIL ') + l); if (!c) fails++; };
const dom = new JSDOM(HTML, { runScripts: 'dangerously', pretendToBeVisual: true, beforeParse(w) { w.MessageChannel = globalThis.MessageChannel; w.console.error = () => {}; } });
const d = dom.window.document, click = el => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
(async () => {
  await sleep(900);
  click([...d.querySelectorAll('button')].find(b => b.textContent.trim().toLowerCase() === 'records')); await sleep(400);
  const ch = d.querySelector('[data-packets-chart]'); ok('chart drawn', !!ch);
  const rows = () => [...ch.querySelectorAll('[data-forest-row]')];
  ok('six rows: median, p90, p99 for discharge and charge', rows().length === 6);
  const k = Object.keys(B.strata).filter(x => x !== 'unknown')[0], D = B.strata[k], fWh = x => x >= 100 ? x.toFixed(0) : x >= 10 ? x.toFixed(1) : x.toFixed(2);
  const m = D.discharge.energyWh.completeOnly.median;
  ok('median discharge value printed with its interval', ch.textContent.includes(fWh(m.value) + ' Wh (' + fWh(m.ci95[0]) + '\u2013' + fWh(m.ci95[1]) + ')'));
  ok('log axis labelled', /log axis/.test(ch.textContent));
  const strip = d.querySelector('[data-packets-share-strip]'); ok('share strip has four rows (runs and energy, two directions)', !!strip && strip.querySelectorAll('svg > g').length === 4);
  ok('energy share of sub-1 Wh runs is printed', strip.textContent.includes(D.discharge.below1Wh.energySharePct.pct.toFixed(2) + ' %'));
  click(d.querySelector('[data-packets-basis="allRunsCensoredAsLowerBounds"]')); await sleep(250);
  const lb = D.discharge.energyWh.allRunsCensoredAsLowerBounds.median;
  ok('lower-bound basis switches the plotted values', d.querySelector('[data-packets-chart]').textContent.includes(fWh(lb.value) + ' Wh') && d.querySelector('[data-packets-basis="allRunsCensoredAsLowerBounds"]').getAttribute('aria-pressed') === 'true');
  console.log(fails ? 'ENERGY BURST CHART TEST FAILED' : 'ENERGY BURST CHART TEST PASSED'); process.exit(fails ? 1 : 0);
})();
