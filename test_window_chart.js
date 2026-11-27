// M786 (owner request 2026-11-27): "How far the battery charge moves on a drive" leads with one plain sentence, then two percentile dot-and-interval charts (SoC points, net Ah) and the R line; the tables and method notes sit behind "How we calculated it". Values from S.windowUse.
const fs = require('fs'); const { JSDOM } = require('jsdom');
if (typeof globalThis.MessageChannel === 'undefined') { globalThis.MessageChannel = class { constructor() { this.port1 = { onmessage: null, postMessage: d => setImmediate(() => this.port2.onmessage && this.port2.onmessage({ data: d })) }; this.port2 = { onmessage: null, postMessage: d => setImmediate(() => this.port1.onmessage && this.port1.onmessage({ data: d })) }; } }; }
const HTML = fs.readFileSync(process.env.XT_HTML || 'xtrail_dashboard.html', 'utf8');
const B = JSON.parse(fs.readFileSync('summary_arrays.json', 'utf8')).windowUse;
const sleep = ms => new Promise(r => setTimeout(r, ms)); let fails = 0; const ok = (l, c) => { console.log((c ? 'PASS ' : 'FAIL ') + l); if (!c) fails++; };
const dom = new JSDOM(HTML, { runScripts: 'dangerously', pretendToBeVisual: true, beforeParse(w) { w.MessageChannel = globalThis.MessageChannel; w.console.error = () => {}; } });
const d = dom.window.document, click = el => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
(async () => {
  await sleep(900); click([...d.querySelectorAll('button')].find(b => b.textContent.trim().toLowerCase() === 'records')); await sleep(400);
  const ch = d.querySelector('[data-window-chart]'); ok('chart block drawn', !!ch);
  for (const k of ['fast', 'slow']) {
    click(d.querySelector(`[data-window-stratum="${k}"]`)); await sleep(250);
    const R = B.strata[k].referenceFree, c = d.querySelector('[data-window-chart]');
    ok(k + ': two charts with three rows each', c.querySelectorAll('[data-interval-forest]').length === 2 && c.querySelectorAll('[data-forest-row]').length === 6);
    ok(k + ': median SoC excursion printed with its interval', c.textContent.includes(R.reportedSocExcursionPoints.p50.value.toFixed(0) + ' (' + R.reportedSocExcursionPoints.p50.ci95[0].toFixed(0) + '\u2013'));
    const lead = d.querySelector('[data-section-lead]').textContent;
    ok(k + ': lead sentence gives median and 95th-percentile swings and says it is not a capacity', lead.includes(R.reportedSocExcursionPoints.p50.value.toFixed(0) + ' points') && lead.includes(R.netChargeExcursionAhUpper.p95.value.toFixed(1) + ' Ah') && /not a capacity or a limit/.test(lead));
    ok(k + ': R line states support', d.querySelector('[data-window-r-line]').textContent.includes(B.strata[k].throughputOverExcursion.nDrives + ' drives'));
  }
  const notes = d.querySelector('[data-window-note]').closest('details'); ok('method note and tables are behind the Notes disclosure', !!notes && !!notes.querySelector('[data-window-ref]') && !!notes.querySelector('[data-window-footnote]'));
  console.log(fails ? 'WINDOW CHART TEST FAILED' : 'WINDOW CHART TEST PASSED'); process.exit(fails ? 1 : 0);
})();
