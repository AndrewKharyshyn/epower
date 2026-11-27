// M784 (owner request 2026-11-27): (1) known-answer test of the pure cluster model crateClusterModel extracted from xtrail_summary.jsx; (2) view test of the peak-charge risk map: a scatter in which drives
// that sit close together are ONE representative dot (area = number of drives), single and never-merged drives are individual dots, every plotted drive is accounted for, the axis follows the data
// (the coldest drives are no longer clipped), a planted sub-zero drive extends the axis and draws a dashed 0 C line, and the "Every drive" toggle brings the one-dot-per-drive view back.
const fs = require('fs');
const src = fs.readFileSync('xtrail_summary.jsx', 'utf8');
const m = src.match(/\/\*M784-MODEL-BEGIN\*\/([\s\S]*?)\/\*M784-MODEL-END\*\//); if (!m) { console.error('FAIL: model not found'); process.exit(1); }
const { crateClusterModel, crateMedian } = new Function(m[1] + ';return {crateClusterModel,crateMedian};')();
let f = 0; const t = (n, c) => { if (!c) { f++; console.log('FAIL', n); } else console.log('  ok:', n); };
t('median of odd, even and empty lists', crateMedian([3, 1, 2]) === 2 && crateMedian([4, 1, 2, 3]) === 2.5 && crateMedian([]) === null);
const P = (tt, v, i, type = 'city', c = v / 5) => ({ i, t: tt, v, c, type });
// cells are dx = 2 wide and dy = 10 tall, anchored at 0; exact edges belong to the upper cell, negatives floor
const vals = [P(10, 50, 0), P(11, 55, 1), P(11, 59, 2, 'mixed'), P(12, 50, 3), P(-1, 5, 4), P(-2, 5, 5), P(30, 200, 6), P(40, 100, 7)];
const M = crateClusterModel(vals, 2, 10, p => p.v >= 200);
t('the never-merged drive stays individual', M.kept.length === 1 && M.kept[0].i === 6);
t('cell (10-12 C, 50-60) holds drives 0, 1, 2 as one group; drive 3 (12 C) is in the next cell and stays single',
  M.groups.some(g => g.n === 3 && g.members.slice().sort().join() === '0,1,2') && M.singles.some(p => p.i === 3));
t('cell (-2..0 C, 0-10) holds the two sub-zero drives (floor, not truncation)', M.groups.some(g => g.n === 2 && g.members.slice().sort().join() === '4,5'));
const g3 = M.groups.find(g => g.n === 3);
t('the group dot is at the median temperature and value, with the range of its drives', g3.t === 11 && g3.v === 55 && g3.tMin === 10 && g3.tMax === 11 && g3.vMin === 50 && g3.vMax === 59);
t('the dominant class is the most common one (city 2 of 3)', g3.dominant === 'city' && g3.types.city === 2 && g3.types.mixed === 1);
t('a drive alone in its cell is a single (drive 7)', M.singles.some(p => p.i === 7));
t('every drive is accounted for exactly once', M.groups.reduce((a, g) => a + g.n, 0) + M.singles.length + M.kept.length === vals.length && M.nDrives === vals.length);
t('extent is rounded outwards to 5 C and covers below zero', M.xMin === -5 && M.xMax === 40);
const dom = crateClusterModel([P(5, 10, 0), P(5, 10, 1), P(5, 10, 2), P(5, 10, 3)], 2, 10, null, p => (p.i < 2 ? 'a' : 'b'));
t('a tie in the dominant class resolves deterministically (alphabetical)', dom.groups[0].dominant === 'a');
t('non-finite values are ignored; an empty input degrades', crateClusterModel([{ t: NaN, v: 1 }, { t: 3, v: Infinity }], 2, 10).nDrives === 0 && crateClusterModel(undefined, 2, 10).groups.length === 0 && crateClusterModel([], 2, 10).xMin === null);
// readability: the number of drawn dots grows far more slowly than the number of drives
const many = Array.from({ length: 1200 }, (_, k) => P(10 + (k % 40), 40 + ((k * 7) % 160), k));
const MM = crateClusterModel(many, 2, 7, null);
t('1,200 drives are drawn as far fewer dots (' + (MM.groups.length + MM.singles.length) + ')', MM.groups.length + MM.singles.length < 600);

// ---- view test
if (typeof globalThis.MessageChannel === 'undefined') { globalThis.MessageChannel = class { constructor() { this.port1 = { onmessage: null, postMessage: d => setImmediate(() => this.port2.onmessage && this.port2.onmessage({ data: d })) }; this.port2 = { onmessage: null, postMessage: d => setImmediate(() => this.port1.onmessage && this.port1.onmessage({ data: d })) }; } }; }
const { JSDOM } = require('jsdom');
const html0 = fs.readFileSync(process.env.XT_HTML || 'xtrail_dashboard.html', 'utf8');
const A = JSON.parse(fs.readFileSync('summary_arrays.json', 'utf8'));
async function load(html) {
  const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, beforeParse(w) { w.MessageChannel = globalThis.MessageChannel; w.console.error = () => {}; w.console.warn = () => {}; } });
  const d = dom.window.document, sleep = ms => new Promise(r => setTimeout(r, ms));
  await sleep(1000);
  [...d.querySelectorAll('button')].find(b => b.textContent.trim().toLowerCase() === 'charts').dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
  await sleep(600);
  return { d, dom, sleep };
}
(async () => {
  let { d, dom, sleep } = await load(html0);
  const pts = A.cRatePointsAK.filter(p => typeof p[3] === 'number');
  const cl = [...d.querySelectorAll('[data-crate-cluster]')], sg = [...d.querySelectorAll('[data-crate-single]')];
  t('grouped dots are the default view (clusters present)', cl.length > 0 && d.querySelector('[data-crate-grouped]') !== null);
  t('every plotted drive is accounted for: cluster sizes plus single dots = ' + pts.length, cl.reduce((a, c) => a + Number(c.getAttribute('data-crate-cluster')), 0) + sg.length === pts.length);
  t('a cluster stands for at least two drives', cl.every(c => Number(c.getAttribute('data-crate-cluster')) >= 2));
  t('fewer dots are drawn than drives (' + (cl.length + sg.length) + ' for ' + pts.length + ')', cl.length + sg.length < pts.length);
  const circ = c => c.querySelector('circle'); const rs = cl.map(c => ({ n: Number(c.getAttribute('data-crate-cluster')), r: Number(circ(c).getAttribute('r')) }));
  t('the dot radius grows with the number of drives', rs.every(a => rs.every(b => a.n <= b.n || a.r >= b.r - 1e-9)));
  t('the hover text of a cluster gives the number of drives, the ranges and the median position', /drives, .* °C, .*; shown at the median/.test(cl[0].querySelector('title').textContent));
  const ax = [...d.querySelectorAll('svg text')].map(x => x.textContent);
  const minT = Math.min(...pts.map(p => p[0]));
  t('the x axis starts at 0 C so the drives below 8 C (clipped before) are plotted', minT < 8 ? ax.includes('0°C') : true);
  t('no zero line while no drive is below 0 C', !d.querySelector('[data-zero-line]'));
  const note = d.querySelector('[data-crate-group-note]'); t('the note explains grouping, colour, size and the never-merged drives', !!note && /one dot at their median/.test(note.textContent) && /dot area grows/.test(note.textContent) && /never merged/.test(note.textContent));
  const tg = [...d.querySelectorAll('[data-crate-mode]')]; t('two mode buttons, grouped pressed', tg.length === 2 && tg.find(b => b.getAttribute('data-crate-mode') === 'grouped').getAttribute('aria-pressed') === 'true');
  tg.find(b => b.getAttribute('data-crate-mode') === 'drives').dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true })); await sleep(300);
  t('every-drive mode draws no grouped dots', d.querySelectorAll('[data-crate-cluster]').length === 0 && !d.querySelector('[data-crate-grouped]'));
  // planted sub-zero drive: the A view places each drive at the T1 sample nearest its current peak (S.powerPeakTemperature.acViewX)
  const first = A.cRatePointsAK[0][5], x0 = A.powerPeakTemperature.acViewX[first].x;
  const html1 = html0.replace('"acViewX":{"' + first + '":{"x":' + x0 + ',', '"acViewX":{"' + first + '":{"x":-3,');
  t('the planted copy differs from the page', html1 !== html0);
  ({ d } = await load(html1));
  t('planted sub-zero drive: dashed 0 C line drawn', !!d.querySelector('[data-zero-line]'));
  t('planted sub-zero drive: a negative tick is labelled', [...d.querySelectorAll('svg text')].some(x => /^-\d+°C$/.test(x.textContent)));
  console.log(f ? 'CRATE CLUSTER TEST FAILED' : 'CRATE CLUSTER TEST PASSED'); process.exit(f ? 1 : 0);
})();
