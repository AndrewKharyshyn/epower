// M644 (self-audit UI-01): real-browser scan of the Compare frames (jsdom has no layout engine).
// Load it in the page (for example the Claude browser pane on a local static server) with:
//   (0, eval)(await (await fetch('/tools/ui_scan_compare.js')).text()); JSON.stringify(await window.__scanCompare())
// For every tab with a Compare mode: select Compare, expand collapsibles, then for every [data-cmp-frame] count its SVG texts, the texts whose rendered size is below 9 px
// (font size x the svg's viewBox scale) and the overlapping text-box pairs (intersection above 20 % of the smaller box). Also reports horizontal page overflow.
window.__scanCompare = async function () {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const TABS = ['overview', 'charts', 'fuel', 'distribution', 'highway vs city', 'thermal', 'records', 'health', 'cross-vehicle', 'conclusions'];
  const click = el => el && el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  const btns = () => [...document.querySelectorAll('button')];
  const out = { width: innerWidth, frames: 0, texts: 0, small: 0, overlap: 0, kinds: {}, worst: [], pageOverflowPx: 0 };
  const seen = new Set(), rows = [];
  for (const t of TABS) {
    click(btns().find(b => b.textContent.trim().toLowerCase() === t)); await sleep(250);
    const cb = document.querySelector('button[data-cohort-btn="compare"]'); if (!cb || cb.disabled) continue;
    click(cb); await sleep(300);
    for (const b of btns().filter(b => !TABS.includes(b.textContent.trim().toLowerCase()) && !b.hasAttribute('data-cohort-btn') && !b.hasAttribute('data-cmp-btn') && /▸|▶|show|expand|more|details/i.test(b.textContent)).slice(0, 150)) { click(b); await sleep(3); }
    await sleep(300);
    out.pageOverflowPx = Math.max(out.pageOverflowPx, document.documentElement.scrollWidth - innerWidth);
    for (const fr of document.querySelectorAll('[data-cmp-frame="1"]')) {
      const title = (fr.firstElementChild.firstElementChild.textContent || '').slice(0, 70);
      if (seen.has(t + title)) continue; seen.add(t + title);
      const kind = (fr.querySelector('[data-cmp-kind]') || { getAttribute: () => 'other' }).getAttribute('data-cmp-kind');
      let nT = 0, small = 0, ov = 0;
      for (const svg of fr.querySelectorAll('svg')) {
        const sr = svg.getBoundingClientRect(); if (sr.width < 5) continue;
        const vb = svg.viewBox && svg.viewBox.baseVal; const sc = (vb && vb.width) ? sr.width / vb.width : 1;
        const texts = [...svg.querySelectorAll('text')].filter(x => x.textContent.trim().length > 0).map(x => ({ r: x.getBoundingClientRect(), fs: parseFloat(getComputedStyle(x).fontSize) * sc })).filter(o => o.r.width > 0 && o.r.height > 0);
        texts.forEach(o => { if (o.fs < 9) small++; });
        for (let i = 0; i < texts.length; i++) for (let j = i + 1; j < texts.length; j++) {
          const a = texts[i].r, b = texts[j].r, ix = Math.min(a.right, b.right) - Math.max(a.left, b.left), iy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
          if (ix > 1 && iy > 1 && ix * iy > 0.2 * Math.min(a.width * a.height, b.width * b.height)) ov++;
        }
        nT += texts.length;
      }
      out.frames++; out.texts += nT; out.small += small; out.overlap += ov;
      const k = out.kinds[kind] || (out.kinds[kind] = { frames: 0, texts: 0, small: 0, overlap: 0 }); k.frames++; k.texts += nT; k.small += small; k.overlap += ov;
      rows.push([kind, t, title, nT, small, ov]);
    }
  }
  out.worst = rows.sort((a, b) => (b[5] * 3 + b[4]) - (a[5] * 3 + a[4])).slice(0, 8);
  return out;
};
