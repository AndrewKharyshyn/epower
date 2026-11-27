// test_bms_power_map_view.js (M779, spec analyses/M779_spec.md Rev 3): the Thermal-tab section "BMS-reported possible input and output power by pack temperature" displays S.bmsPowerMap
// ladder-first; every number equals the payload; values at the logged maximum are printed as text, never as a kW number; one era at a time; era labels from dateFrom/dateTo; disclosures present.
const fs = require('fs'); const { JSDOM } = require('jsdom');
if (typeof globalThis.MessageChannel === 'undefined') { globalThis.MessageChannel = class { constructor() { this.port1 = { onmessage: null, postMessage: d => setImmediate(() => this.port2.onmessage && this.port2.onmessage({ data: d })) }; this.port2 = { onmessage: null, postMessage: d => setImmediate(() => this.port1.onmessage && this.port1.onmessage({ data: d })) }; } }; }
const html = fs.readFileSync(process.env.XT_HTML || 'xtrail_dashboard.html', 'utf8');
const A = JSON.parse(fs.readFileSync('summary_arrays.json', 'utf8'));
let fails = 0; const ok = (label, c) => { console.log((c ? 'PASS ' : 'FAIL ') + label); if (!c) fails++; };
const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, beforeParse(w) { w.MessageChannel = globalThis.MessageChannel; w.console.error = () => {}; w.console.warn = () => {}; } });
const d = dom.window.document, sleep = ms => new Promise(r => setTimeout(r, ms)), click = el => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
const B = A.bmsPowerMap, flag = Number(B.rules.loggedMaximumFlagKw).toFixed(2), pc1 = v => (v * 100).toFixed(1), f2 = v => Number(v).toFixed(2);
const bins = L => Object.keys(L).sort((a, b) => a - b); const plu = (n, w) => n + ' ' + w + (n === 1 ? '' : 's');
(async () => {
  await sleep(1000);
  click([...d.querySelectorAll('button')].find(b => b.textContent.trim().toLowerCase() === 'thermal')); await sleep(600);
  const host = d.querySelector('[data-bms-map]'); ok('section present on the Thermal tab', !!host); if (!host) process.exit(1);
  const eras = ['kW', 'hp'].filter(e => B.eras[e]);
  for (const era of eras) {
    const E = B.eras[era];
    const btn = [...host.querySelectorAll('button')].find(b => b.textContent.includes(E.input.dateFrom) && b.textContent.includes(E.input.dateTo));
    ok(era + ': era button labelled from dateFrom/dateTo', !!btn); if (!btn) continue;
    click(btn); await sleep(300);
    ok(era + ': pressed state', btn.getAttribute('aria-pressed') === 'true');
    const lead = host.querySelector('[data-bms-lead]').textContent;
    ok(era + ': lead names the era dates, drives and days', lead.includes(E.input.dateFrom) && lead.includes(E.input.dateTo) && lead.includes(plu(E.input.drives, 'drive')) && lead.includes(plu(E.input.days, 'day')));
    ok(era + ': no era contrast wording', !/than in the (hp|kw) era/i.test(host.textContent));
    for (const dir of ['input', 'output']) {
      const X = E[dir]; const pane = host.querySelector('[data-bms-dir="' + dir + '"]');
      if (X.coverageFalsification) { ok(era + ' ' + dir + ': coverageFalsification draws no map', !!pane && !pane.querySelector('svg')); continue; }
      ok(era + ' ' + dir + ': panel present', !!pane); if (!pane) continue;
      const L = X.ladderSoc55to66, shown = bins(L).filter(b => L[b].status !== 'not shown');
      const rows = [...pane.querySelectorAll('[data-bms-share] [data-forest-row]')];
      ok(era + ' ' + dir + ': one share row per bin (' + bins(L).length + ')', rows.length === bins(L).length);
      bins(L).forEach((b, i) => { const c = L[b], r = rows[i]; if (!r) return;
        if (c.status === 'not shown') { ok(era + ' ' + dir + ' ' + b + ': not shown bin says so', /not observed at this support/.test(r.textContent)); return; }
        ok(era + ' ' + dir + ' ' + b + ': share at the logged maximum and counts equal the payload', r.textContent.includes(pc1(c.maxShare)) && r.textContent.includes(plu(c.nDrives, 'drive')) && r.textContent.includes(plu(c.nDays, 'day'))); });
      const bm = [...pane.querySelectorAll('[data-bms-belowmax] [data-dot-label]')].map(x => x.textContent);
      const want = shown.filter(b => L[b].belowMaxMedian != null).map(b => Number(L[b].belowMaxMedian).toFixed(2) + ' kW');
      ok(era + ' ' + dir + ': below-maximum median labels equal the payload', JSON.stringify(bm) === JSON.stringify(want));
      ok(era + ' ' + dir + ': payload monotone text quoted verbatim', pane.textContent.includes(X.monotone.maxShare) && pane.textContent.includes(X.monotone.belowMaxMedian));
      // Director display review: degenerate intervals are printed as such, bootDropRate and estimatorDependent are shown
      const bmRows = [...pane.querySelectorAll('[data-bms-belowmax] [data-forest-row]')];
      shown.forEach(b => { const c = L[b], i = bins(L).indexOf(b), ci = c.ci95 && c.ci95.belowMaxMedian; if (c.belowMaxMedian != null && ci && ci[0] === ci[1] && bmRows[i]) ok(era + ' ' + dir + ' ' + b + ': degenerate below-maximum interval printed as such', /degenerate interval/.test(bmRows[i].textContent) && !/\(\s*[\d.]+,\s*[\d.]+\)/.test(bmRows[i].textContent.replace(/\d+ drives.*$/, ''))); });
      const lt = host.querySelector('[data-bms-ladder="' + dir + '"]');
      shown.forEach(b => { const tr = lt.querySelector('[data-bms-row="' + dir + '|' + b + '"]'); ok(era + ' ' + dir + ' ' + b + ': bootDropRate printed', !!tr && /bootstrap draws dropped/.test(tr.textContent)); });
      Object.keys(X.cells).filter(k => X.cells[k].estimatorDependent).forEach(k => { const [tb, sb] = k.split('|'); const ct = host.querySelector('[data-bms-cells="' + dir + '"]'); ok(era + ' ' + dir + ' cell ' + k + ': estimator-dependent marker shown', !!ct && /estimator-dependent/.test(ct.textContent)); });
      // detailed ladder table: at-maximum quantities are text, never a kW number
      const tab = host.querySelector('[data-bms-ladder="' + dir + '"]');
      bins(L).forEach(b => { const c = L[b]; const tr = tab && tab.querySelector('[data-bms-row="' + dir + '|' + b + '"]'); if (!tr || c.status === 'not shown') return;
        const cells = [...tr.querySelectorAll('td')].map(t => t.textContent);
        if (c.medianAtLoggedMaximum) ok(era + ' ' + dir + ' ' + b + ': median at the maximum printed as text', /at the logged maximum/.test(cells[4]) && !/kW$/.test(cells[4]));
        else ok(era + ' ' + dir + ' ' + b + ': median equals the payload', cells[4] === f2(c.median) + ' kW'); });
    }
    ok(era + ': output panel carries the logged-maximum marker wording (O1)', /not a ceiling/.test(host.querySelector('[data-bms-dir="output"]').textContent));
    ok(era + ': input panel states generator charging and regeneration', /generator charging and regeneration/.test(host.querySelector('[data-bms-dir="input"]').textContent));
  }
  const dis = host.querySelector('[data-bms-disclosures]'); ok('every disclosure and reading item present', !!dis && B.disclosures.every(t => dis.textContent.includes(t)) && B.reading.every(t => dis.textContent.includes(t)));
  ok('notIndependentlyReproduced listed (display labels)', B.notIndependentlyReproduced.every(t => dis.textContent.includes(t === 'longestRunAtMaximumS' ? 'longest run at the maximum' : t)));
  ok('polling regimes are a disclosure only (no interval forest for them)', !!host.querySelector('[data-bms-regime]') && !host.querySelector('[data-bms-regime] [data-interval-forest]'));
  console.log(fails ? 'FAILED ' + fails : 'ALL PASS'); process.exit(fails ? 1 : 0);
})();
