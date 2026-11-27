// M792 (audit Wave C #9; spec analyses/M792_spec.md Rev 2, Director decision section 11): the three-state strip by speed zone shows only zones that meet the display floor, a headline for the merged
// 80-120 km/h band bound to S.highwayStates (the "about half" wording is generated from the verdict), the 5 A dead-band sensitivity note, a "not shown (not zero)" line (no estimates) for a zone below the floor,
// a per-drive / pooled switch, and no forbidden wording.
const fs = require('fs'); const { JSDOM } = require('jsdom');
if (typeof globalThis.MessageChannel === 'undefined') { globalThis.MessageChannel = class { constructor() { this.port1 = { onmessage: null, postMessage: d => setImmediate(() => this.port2.onmessage && this.port2.onmessage({ data: d })) }; this.port2 = { onmessage: null, postMessage: d => setImmediate(() => this.port1.onmessage && this.port1.onmessage({ data: d })) }; } }; }
const HTML = fs.readFileSync(process.env.XT_HTML || 'xtrail_dashboard.html', 'utf8');
const A = JSON.parse(fs.readFileSync('summary_arrays.json', 'utf8')), H = A.highwayStates;
const sleep = ms => new Promise(r => setTimeout(r, ms)); let fails = 0; const ok = (l, c) => { console.log((c ? 'PASS ' : 'FAIL ') + l); if (!c) fails++; };
const dom = new JSDOM(HTML, { runScripts: 'dangerously', pretendToBeVisual: true, beforeParse(w) { w.MessageChannel = globalThis.MessageChannel; w.console.error = () => {}; } });
const d = dom.window.document, click = el => el.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
(async () => {
  await sleep(900); click([...d.querySelectorAll('button')].find(b => b.textContent.trim().toLowerCase() === 'highway vs city')); await sleep(500);
  const v = d.querySelector('[data-highway-states]'); ok('three-state block present', !!v); if (!v) process.exit(1);
  const shown = H.zones.filter(z => z.shown), hid = H.zones.filter(z => !z.shown);
  const strip = v.querySelector('[data-share-strip]'), lbl = strip ? [...strip.querySelectorAll('text')].map(t => t.textContent) : [];
  ok('one strip row per shown zone (' + shown.length + ')', shown.every(z => lbl.includes(z.zone + ' km/h')) && !hid.some(z => lbl.includes(z.zone + ' km/h')));
  const M = H.mergedBand80to120, head = v.querySelector('[data-hs-headline]').textContent;
  ok('headline gives the merged-band drives and days and both estimates', head.includes(M.nDrives + ' drives, ' + M.nDays + ' days') && head.includes(M.S1.perDriveMean.est.toFixed(1)) && head.includes(M.S1.pooled.est.toFixed(1)));
  ok('"about half" is stated only when the verdict says so', (H.claim.verdict === 'aboutHalf') === /about half of logged time/.test(head));
  ok('the dead-band note is stated when its intervals leave 40-60 %', H.claim.dead5AIntervalsInside || /near-zero current band/.test(head));
  ok('a zone below the display floor is "not shown (not zero)" with no estimate', hid.every(z => { const e = v.querySelector('[data-hs-hidden="' + z.zone + '"]'); return e && /not shown \(not zero\)/.test(e.textContent) && !/%/.test(e.textContent); }));
  ok('the flag note quotes the dead-band share for each flagged zone', (H.flags || []).filter(f => f.variant === 'dead5A').every(f => v.querySelector('[data-hs-flag]').textContent.includes(f.zone + ' km/h is ')));
  const b = k => v.querySelector('[data-hs-basis="' + k + '"]'); click(b('pooled')); await sleep(250);
  ok('the switch redraws the table from the pooled estimates', b('pooled').getAttribute('aria-pressed') === 'true' && v.querySelector('[data-hs-row="' + shown[0].zone + '"]').textContent.includes(shown[0].primary.S1.pooled.est.toFixed(1)));
  const all = v.textContent;
  ok('no forbidden wording', !/\b(measured|capability|typical|optimal|idle|generator saturation)\b/i.test(all.replace(/not generator output/g, '').replace(/not generator saturation/g, '')));
  ok('the 300 rpm threshold of the stored engine-on share is named', /above 300/.test(all));
  console.log(fails ? 'HIGHWAY STATES VIEW TEST FAILED' : 'HIGHWAY STATES VIEW TEST PASSED'); process.exit(fails ? 1 : 0);
})();
