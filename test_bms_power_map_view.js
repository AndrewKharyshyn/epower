// test_bms_power_map_view.js (M779 spec Rev 3, M781 owner request 2026-11-27: one view, all values in kW, both logging periods drawn together, never pooled): the Thermal-tab section
// "BMS-reported possible input and output power by pack temperature" displays S.bmsPowerMap ladder-first; every number equals the payload; values at the logged maximum are printed as text,
// never as a kW number; no era toggle; period labels from dateFrom/dateTo; disclosures present.
const fs = require('fs'); const { JSDOM } = require('jsdom');
if (typeof globalThis.MessageChannel === 'undefined') { globalThis.MessageChannel = class { constructor() { this.port1 = { onmessage: null, postMessage: d => setImmediate(() => this.port2.onmessage && this.port2.onmessage({ data: d })) }; this.port2 = { onmessage: null, postMessage: d => setImmediate(() => this.port1.onmessage && this.port1.onmessage({ data: d })) }; } }; }
const html = fs.readFileSync(process.env.XT_HTML || 'xtrail_dashboard.html', 'utf8');
const A = JSON.parse(fs.readFileSync('summary_arrays.json', 'utf8'));
let fails = 0; const ok = (label, c) => { console.log((c ? 'PASS ' : 'FAIL ') + label); if (!c) fails++; };
const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, beforeParse(w) { w.MessageChannel = globalThis.MessageChannel; w.console.error = () => {}; w.console.warn = () => {}; } });
const d = dom.window.document, sleep = ms => new Promise(r => setTimeout(r, ms)), click = el => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
const B = A.bmsPowerMap, flag = Number(B.rules.loggedMaximumFlagKw).toFixed(2), pc1 = v => (v * 100).toFixed(1), f2 = v => Number(v).toFixed(2);
const bins = L => Object.keys(L).sort((a, b) => a - b); const plu = (n, w) => n + ' ' + w + (n === 1 ? '' : 's');
const eras = ['hp', 'kW'].filter(e => B.eras[e]); const eraShort = e => e === 'hp' ? 'Earlier logs' : 'Later logs'; const eraTiny = e => e === 'hp' ? 'Earlier' : 'Later';
const eraName = e => eraShort(e) + ' (' + B.eras[e].input.dateFrom + ' to ' + B.eras[e].input.dateTo + ')';
(async () => {
  await sleep(1000);
  click([...d.querySelectorAll('button')].find(b => b.textContent.trim().toLowerCase() === 'thermal')); await sleep(600);
  const host = d.querySelector('[data-bms-map]'); ok('section present on the Thermal tab', !!host); if (!host) process.exit(1);
  ok('no era toggle: one view', ![...host.querySelectorAll('button')].some(b => /Logger columns|Earlier logs|Later logs/.test(b.textContent)));
  const lead = host.querySelector('[data-bms-lead]').textContent;
  ok('lead says all in kW and names both periods with the payload dates, drives and days', /all in kW/.test(lead) && eras.every(e => lead.includes(eraName(e)) && lead.includes(plu(B.eras[e].input.drives, 'drive')) && lead.includes(plu(B.eras[e].input.days, 'day'))));
  const leg = host.querySelector('[data-bms-legend]').textContent; ok('legend names both periods', eras.every(e => leg.includes(eraName(e))));
  const pn = host.querySelector('[data-bms-periodnote]').textContent;
  ok('period note names every way the periods differ, from the payload (conversion, highest logged value, polling mix) and says no difference is estimated', /recorded in horsepower and converted to kW/.test(pn) && eras.every(e => pn.includes(Number(B.eras[e].input.saturation.eraMaximumKw).toFixed(2) + ' kW')) && eras.every(e => { const R = B.eras[e].input.cadenceRegimeSensitivity; return pn.includes(plu(R.fast.nDrives, 'fast-polled drive')) && pn.includes(plu(R.slow.nDrives, 'slow-polled drive')); }) && /No difference between the two dots of a bin is estimated/.test(pn) && /not a period, update or temperature effect/.test(pn));
  ok('no pooling or contrast wording', /not pooled or compared/.test(host.textContent) && !/than in the (earlier|later|hp|kw)/i.test(host.textContent));
  for (const dir of ['input', 'output']) {
    const pane = host.querySelector('[data-bms-dir="' + dir + '"]'); ok(dir + ': panel present', !!pane); if (!pane) continue;
    const share = [...pane.querySelectorAll('[data-bms-share] [data-forest-row]')];
    const allBins = [...new Set(eras.flatMap(e => bins(B.eras[e][dir].ladderSoc55to66)))].sort((a, b) => a - b);
    const shownCells = []; allBins.forEach(b => eras.forEach(e => { const c = B.eras[e][dir].ladderSoc55to66[b]; if (c && c.status !== 'not shown') shownCells.push([e, b, c]); }));
    const noneBins = allBins.filter(b => !eras.some(e => { const c = B.eras[e][dir].ladderSoc55to66[b]; return c && c.status !== 'not shown'; }));
    ok(dir + ': one share row per shown (period, bin) plus one per bin shown in neither period (' + (shownCells.length + noneBins.length) + ')', share.length === shownCells.length + noneBins.length);
    shownCells.forEach(([e, b, c]) => { const r = share.find(x => x.textContent.includes(eraTiny(e) + ' · ' + plu(c.nDrives, 'drive') + ' · ' + plu(c.nDays, 'day') + ' · ' + c.status) && x.textContent.includes(pc1(c.maxShare)));
      ok(dir + ' ' + e + ' ' + b + ': status readable in full (not truncated)', !!r && !/…/.test(r.textContent));
      ok(dir + ' ' + e + ' ' + b + ': exploratory rows are muted per period, supported rows are not', !!r && r.getAttribute('opacity') === (c.status === 'exploratory' ? '0.4' : '1'));
      ok(dir + ' ' + e + ' ' + b + ': marker shape codes the period (square = earlier, circle = later)', !!r && !!r.querySelector('[data-marker="' + (e === 'hp' ? 'square' : 'circle') + '"]'));
      ok(dir + ' ' + e + ' ' + b + ': share at the logged maximum, counts and status equal the payload', !!r); });
    noneBins.forEach(b => ok(dir + ' ' + b + ': bin shown in neither period says so', share.some(x => /not observed at this support in either logging period/.test(x.textContent))));
    const labs = [...pane.querySelectorAll('[data-bms-belowmax] [data-dot-label]')].map(x => x.textContent);
    const want = shownCells.filter(([e, b, c]) => c.belowMaxMedian != null).map(([e, b, c]) => Number(c.belowMaxMedian).toFixed(2) + ' kW');
    ok(dir + ': below-maximum median dot labels equal the payload (in kW, bin order)', JSON.stringify(labs) === JSON.stringify(want));
    eras.forEach(e => { const X = B.eras[e][dir]; ok(dir + ' ' + e + ': payload monotone text quoted verbatim', pane.textContent.includes(X.monotone.maxShare) && pane.textContent.includes(X.monotone.belowMaxMedian)); });
    const bmRows = [...pane.querySelectorAll('[data-bms-belowmax] [data-forest-row]')];
    shownCells.forEach(([e, b, c]) => { const ci = c.ci95 && c.ci95.belowMaxMedian; if (c.belowMaxMedian != null && ci && ci[0] === ci[1]) { const r = bmRows.find(x => x.textContent.includes(eraTiny(e) + ' · ' + plu(c.nDrives, 'drive')) && /degenerate interval/.test(x.textContent)); ok(dir + ' ' + e + ' ' + b + ': degenerate below-maximum interval printed as such', !!r); } });
    eras.forEach(e => {
      const X = B.eras[e][dir], L = X.ladderSoc55to66; const tab = host.querySelector('[data-bms-ladder="' + e + '|' + dir + '"]'); ok(dir + ' ' + e + ': ladder table present', !!tab); if (!tab) return;
      bins(L).forEach(b => { const c = L[b]; const tr = tab.querySelector('[data-bms-row="' + e + '|' + dir + '|' + b + '"]'); if (!tr || c.status === 'not shown') return;
        const cells = [...tr.querySelectorAll('td')].map(t => t.textContent);
        if (c.medianAtLoggedMaximum) ok(dir + ' ' + e + ' ' + b + ': median at the maximum printed as text', /at the logged maximum/.test(cells[4]) && !/kW$/.test(cells[4]));
        else ok(dir + ' ' + e + ' ' + b + ': median equals the payload', cells[4] === f2(c.median) + ' kW');
        ok(dir + ' ' + e + ' ' + b + ': bootDropRate printed', /bootstrap draws dropped/.test(tr.textContent)); });
      Object.keys(X.cells).filter(k => X.cells[k].estimatorDependent).forEach(k => { const ct = host.querySelector('[data-bms-cells="' + e + '|' + dir + '"]'); ok(dir + ' ' + e + ' cell ' + k + ': estimator-dependent marker shown', !!ct && /estimator-dependent/.test(ct.textContent)); });
    });
  }
  ok('output panel carries the logged-maximum marker wording (O1)', /not a ceiling/.test(host.querySelector('[data-bms-dir="output"]').textContent));
  ok('input panel states generator charging and regeneration', /generator charging and regeneration/.test(host.querySelector('[data-bms-dir="input"]').textContent));
  ok('the note states every value is in kW, the hp conversion, the grid share from the payload and glosses hp era as Earlier logs', /All values are in kW/.test(host.textContent) && /converted to kW/.test(host.textContent) && eras.every(e => host.textContent.includes(eraTiny(e).toLowerCase() + ': ' + pc1(B.eras[e].input.gridShareOn0p05kW) + '%')) && /"hp era" means the Earlier logs/.test(host.textContent));
  const dis = host.querySelector('[data-bms-disclosures]'); ok('every disclosure and reading item present', !!dis && B.disclosures.every(t => dis.textContent.includes(t)) && B.reading.every(t => dis.textContent.includes(t)));
  ok('notIndependentlyReproduced listed (display labels)', B.notIndependentlyReproduced.every(t => dis.textContent.includes(t === 'longestRunAtMaximumS' ? 'longest run at the maximum' : t)));
  ok('polling regimes are a disclosure only (no interval forest for them)', !!host.querySelector('[data-bms-regime]') && !host.querySelector('[data-bms-regime] [data-interval-forest]'));
  console.log(fails ? 'FAILED ' + fails : 'ALL PASS'); process.exit(fails ? 1 : 0);
})();
