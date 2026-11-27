// test_fuel_distribution_redesign.js (M782, Wave A #1 of the dashboard rework, audit section 2 item 1): the Fuel-tab section "Fuel use across trips and over time" leads with one bound sentence,
// a horizontal box-and-whisker of the trip consumption (trip-count or distance-weighted toggle, median labelled, 10th/90th percentile endpoints named, median interval) and one point with its
// interval per 14-day window beside a kilometre strip; every number equals S.fuelAnalytics.fuel11; the full distributions and tables stay behind "How we calculated it".
const fs = require('fs'); const { JSDOM } = require('jsdom');
if (typeof globalThis.MessageChannel === 'undefined') { globalThis.MessageChannel = class { constructor() { this.port1 = { onmessage: null, postMessage: d => setImmediate(() => this.port2.onmessage && this.port2.onmessage({ data: d })) }; this.port2 = { onmessage: null, postMessage: d => setImmediate(() => this.port1.onmessage && this.port1.onmessage({ data: d })) }; } }; }
const html = fs.readFileSync(process.env.XT_HTML || 'xtrail_dashboard.html', 'utf8');
const A = JSON.parse(fs.readFileSync('summary_arrays.json', 'utf8'));
let fails = 0; const ok = (label, c) => { console.log((c ? 'PASS ' : 'FAIL ') + label); if (!c) fails++; };
const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, beforeParse(w) { w.MessageChannel = globalThis.MessageChannel; w.console.error = () => {}; w.console.warn = () => {}; } });
const d = dom.window.document, sleep = ms => new Promise(r => setTimeout(r, ms)), click = el => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
const F = A.fuelAnalytics.fuel11, D = F.distribution.primary_km_ge_2, tw = D.est.tripWeighted, dw = D.est.distanceWeighted, c = D.ci95;
const f1 = v => Number(v).toFixed(1);
(async () => {
  await sleep(1000);
  click([...d.querySelectorAll('button')].find(b => b.textContent.trim().toLowerCase() === 'fuel')); await sleep(500);
  const top = d.querySelector('[data-fuel-dist-top]'); ok('top block present', !!top); if (!top) process.exit(1);
  const lead = top.querySelector('[data-fuel-dist-lead]').textContent;
  ok('lead states the middle half, the median and its interval from the payload', lead.includes(f1(tw.q25) + ' and ' + f1(tw.q75) + ' L/100 km') && lead.includes('median trip used ' + f1(tw.q50)) && lead.includes(f1(c.trip_q50[0]) + ' to ' + f1(c.trip_q50[1])));
  ok('lead states the trip and day counts', lead.includes(D.nTrips + ' trips on ' + D.nDays + ' days'));
  ok('no "typical" and no unsupported ordering in the lead', !/typical/i.test(lead));
  const bw = () => top.querySelector('[data-box-whisker]');
  const txt = () => bw().textContent;
  ok('trip-count view: median, 10th and 90th percentile and quartiles equal the payload', txt().includes('median ' + f1(tw.q50)) && txt().includes('10th percentile ' + f1(tw.q10)) && txt().includes('90th percentile ' + f1(tw.q90)) && txt().includes(f1(tw.q25)) && txt().includes(f1(tw.q75)));
  ok('median interval printed', txt().includes('95% interval of the median ' + f1(c.trip_q50[0]) + ' to ' + f1(c.trip_q50[1])));
  const btns = [...top.querySelectorAll('[data-fuel-dist-view]')]; ok('two labelled weighting buttons', btns.length === 2 && btns.some(b => /Each trip counts once/.test(b.textContent)) && btns.some(b => /Each kilometre counts once/.test(b.textContent)));
  ok('default is the trip-count view', btns.find(b => b.getAttribute('data-fuel-dist-view') === 'trips').getAttribute('aria-pressed') === 'true');
  click(btns.find(b => b.getAttribute('data-fuel-dist-view') === 'distance')); await sleep(300);
  ok('distance-weighted view: values equal the payload', txt().includes('median ' + f1(dw.q50)) && txt().includes('10th percentile ' + f1(dw.q10)) && txt().includes('90th percentile ' + f1(dw.q90)) && txt().includes('95% interval of the median ' + f1(c.dist_q50[0]) + ' to ' + f1(c.dist_q50[1])));
  ok('box-whisker has a text alternative', /10th percentile/.test(bw().getAttribute('aria-label')) && /median/.test(bw().getAttribute('aria-label')));
  // window series
  const win = F.trend.windows14, ws = top.querySelector('[data-window-series]'); ok('window series present', !!ws);
  const t0 = Date.parse(win[0].start), t1 = Date.parse(win[win.length - 1].start), step = F.trend.primaryWindowDays * 86400000; const slots = []; for (let t = t0; t <= t1 + 1; t += step) slots.push(new Date(t).toISOString().slice(0, 10));
  win.forEach(w => { const g = ws.querySelector('[data-window-point="' + w.start + '"]'); ok(w.start + ': point, km and short-trip share equal the payload', !!g && g.textContent.includes(w.pooledL100.est.toFixed(1)) && g.textContent.includes(Math.round(w.km) + ' km') && g.textContent.includes(Math.round(100 * w.shareKmInTripsUnder5km) + '% short')); });
  slots.filter(s => !win.some(w => w.start === s)).forEach(s => ok(s + ': an empty window is drawn blank and says so', !!ws.querySelector('[data-window-empty="' + s + '"]') && /no fuel-logged trips/.test(ws.querySelector('[data-window-empty="' + s + '"]').textContent)));
  ok('the windows are called 14-day windows (not calendar fortnights)', /14-day window/.test(top.textContent));
  const notes = d.querySelector('[data-fuel-distribution]').querySelector('details.xt-notes'); ok('the full distributions and tables sit behind the disclosure', !!notes && !!notes.querySelector('[data-fx-ecdf]') && !!notes.querySelector('[data-fx-trend]') && notes.querySelectorAll('table').length >= 2);
  console.log(fails ? 'FAILED ' + fails : 'ALL PASS'); process.exit(fails ? 1 : 0);
})();
