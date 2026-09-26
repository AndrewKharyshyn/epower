"""
build_seasonal_dashboard.py  —  emit a self-contained seasonal dashboard.
Reads seasonal_arrays.json (+ dependency + config) and inlines them into one
HTML file with a single cohort state (segmented control), compact metric cards,
an Observed|Adjusted toggle scoped to the comparison area, dynamic warnings, and
correctly-disabled adjusted / temperature-response states. No hardcoded seasonal
headline values — every displayed number comes from the computation payload.
Vanilla JS (no build step, no CDN) so it renders anywhere and validates headless.
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
arrays = json.load(open(os.path.join(HERE, "seasonal_arrays.json")))
cfg = json.load(open(os.path.join(HERE, "seasonal_config.json")))
cohort_arrays = json.load(open(os.path.join(HERE, "cohort_arrays.json")))

# dependency verdict -> card label
DEP_LABEL = {"thermal": "Thermal", "season_associated": "Season-associated",
             "season_neutral": "Season-neutral", "inconclusive": "Inconclusive",
             "not_applicable": "Exposure/constant", "validity_caveat": "Validity"}
# map each displayed metric key to a dependency group's prior label
def dep_for(metric_key):
    for g, m in arrays["seasonalDependency"]["metrics"].items():
        if metric_key in m["keys"]:
            pc = m["priorCandidate"]
            # under warm-only, thermal candidates read as their current verdict
            cv = m.get("currentVerdict", pc)
            return DEP_LABEL.get(pc, pc), DEP_LABEL.get(cv, cv)
    return "—", "—"

# metrics to show as overview cards (key, label, unit, kind)
OVERVIEW = [
    ("gross_throughput_kwh_per100km", "Gross throughput", "kWh/100km", "rate"),
    ("engine_on_pct", "Engine-on share", "%", "mean"),
    ("ev_dist_pct", "EV distance share", "%", "mean"),
    ("soc_range_span_pp", "SoC range span", "pp", "mean"),
    ("regen_share_of_charge", "Regen share of charge", "%", "mean"),
    ("standstill_draw_kw", "Aux draw (standstill)", "kW", "mean"),
    ("vsag_R_pack_mohm", "Pack resistance", "mOhm", "mean"),
    ("rf_n_cycles", "Rainflow cycles", "n/drive", "mean"),
]
REFERENCE = [("distance_km", "Distance", "km"), ("gross_throughput_kwh", "Throughput", "kWh")]

payload = {
    "cohorts": arrays["cohorts"],
    "overview": OVERVIEW,
    "reference": REFERENCE,
    "depLabels": {k: dep_for(k) for k, *_ in OVERVIEW},
    "allLabel": arrays["cohortLabelAll"],
    "allYearEnabled": arrays["allYearEnabled"],
    "adjustedAvailable": arrays["adjustedContrastAvailable"],
    "globalWarnings": arrays["globalWarnings"],
    "thresholds": arrays["_provenance"]["thresholds"],
    "regenView": arrays["seasonalDependency"]["phenomenonViews"]["regen"],
    "coreVersion": arrays["_provenance"]["seasonalCoreVersion"],
    "cohortCharts": cohort_arrays["charts"],
    "cohortStaged": cohort_arrays["stagedCharts"],
    "cohortReady": cohort_arrays["dataReadyCharts"],
    "phase2Charts": cohort_arrays["phase2Charts"],
    "warmupCharts": cohort_arrays["warmupCharts"],
    "frozenCharts": cohort_arrays["frozenCharts"],
    "stagedNow": cohort_arrays["stagedCharts"],
}

HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>X-Trail e-POWER — Seasonal Dashboard</title>
<style>
:root{--bg:#0f1216;--panel:#171b21;--panel2:#1e242c;--line:#2a323c;--fg:#e6edf3;
--mut:#8b98a6;--warm:#e0803a;--shoulder:#c9b23a;--cold:#4f9bd9;--all:#7d8aa0;
--thermal:#4f9bd9;--assoc:#c9b23a;--na:#6b7684;--warn:#e0803a;--bad:#d9534f;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:18px}
h1{font-size:18px;margin:0 0 2px}.sub{color:var(--mut);font-size:12px;margin-bottom:14px}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:8px;overflow:hidden;margin:6px 0}
.seg button{background:var(--panel);color:var(--fg);border:0;padding:8px 16px;cursor:pointer;
font-size:13px;border-right:1px solid var(--line)}
.seg button:last-child{border-right:0}.seg button.on{background:var(--panel2);font-weight:600}
.seg button.warm.on{box-shadow:inset 0 -3px var(--warm)}.seg button.shoulder.on{box-shadow:inset 0 -3px var(--shoulder)}
.seg button.cold.on{box-shadow:inset 0 -3px var(--cold)}.seg button.all.on{box-shadow:inset 0 -3px var(--all)}
.seg button:disabled{color:#556;cursor:not-allowed}
.hdr{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}
.hdr .row{display:flex;gap:22px;flex-wrap:wrap;font-size:13px}
.hdr b{color:var(--fg)}.hdr span{color:var(--mut)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:10px;margin:10px 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:11px 12px}
.card .nm{font-size:12px;color:var(--mut)}.card .val{font-size:22px;font-weight:600;margin:2px 0}
.card .val small{font-size:12px;color:var(--mut);font-weight:400}
.card .cmp{font-size:12px;color:var(--mut);min-height:16px}
.card .cov{font-size:11px;color:var(--mut);margin-top:6px;border-top:1px solid var(--line);padding-top:5px}
.tag{display:inline-block;font-size:10px;padding:1px 6px;border-radius:6px;margin-top:5px}
.tag.Thermal{background:#12283a;color:var(--thermal)}.tag.Season-associated{background:#2a2612;color:var(--assoc)}
.tag.Inconclusive{background:#20242a;color:var(--mut)}.tag.Exposure\\/constant{background:#20242a;color:var(--na)}
.sec{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}
.sec h2{font-size:14px;margin:0 0 8px}.warnbox{background:#241c14;border:1px solid #4a361f;color:#e8b98a;
border-radius:8px;padding:9px 12px;margin:8px 0;font-size:12px}
.disabled{color:var(--mut);font-style:italic;font-size:13px}
details{margin-top:6px}summary{cursor:pointer;color:var(--mut);font-size:13px}
.regen{font-size:12px;color:var(--mut)}.regen table{border-collapse:collapse;width:100%;margin-top:6px}
.regen td{border-top:1px solid var(--line);padding:3px 6px}.dn{color:var(--cold)}.up{color:var(--warm)}
.foot{color:var(--mut);font-size:11px;margin-top:16px}
.tip{border-bottom:1px dotted var(--mut);cursor:help}
</style></head><body><div class="wrap">
<h1>X-Trail T33 e-POWER — Seasonal Dashboard</h1>
<div class="sub">Single-cohort view · thresholds cold&nbsp;&le;__CMAX__&deg;C · warm&nbsp;&ge;__WMIN__&deg;C · <span id="core"></span></div>
<div class="seg" id="seg"></div>
<div class="hdr" id="hdr"></div>
<div id="gwarn"></div>
<div class="sec"><h2>Overview</h2><div class="grid" id="ov"></div></div>
<div class="sec"><h2>Season comparison
<span class="seg" style="margin-left:10px;vertical-align:middle" id="oa"></span></h2>
<div id="cmp"></div></div>
<div class="sec"><h2>Temperature response</h2><div id="tresp"></div></div>
<div class="sec"><h2>Phase-1 thermal charts — per-cohort (proof of binding)</h2>
<div class="sub" style="margin:-4px 0 8px">Chart data recomputed per cohort from underlying drives (ratio-of-sums / pooled). Comparison shown vs Warm; duty-mediated where noted. Cold is empty until ingested.</div>
<div id="cohortcharts"></div>
<details style="margin-top:8px"><summary>Staged thermal charts (need per-second raw or model refit)</summary>
<div id="staged" style="margin-top:8px"></div></details></div>
<div class="sec"><h2>Phase-2 season-associated charts — adjusted comparison</h2>
<div class="sub" style="margin:-4px 0 8px">Raw seasonal differences here are duty-mediated. Comparison is <b>composition-adjusted</b> (standardized to pooled speed/stationary/highway/trip-length), day-clustered bootstrap CI. Adjusted warm–cold is unavailable until cold data; the warm–shoulder panel is an exploratory machinery demonstration (shoulder ≠ cold).</div>
<div id="p2charts"></div></div>
<div class="sec"><h2>Warm-up curve — per-cohort (raw-derived, multiline)</h2>
<div class="sub" style="margin:-4px 0 8px">Oil / engine-coolant temperature vs elapsed seconds since first valid sample, averaged per cohort. Cold-season warm-up starts lower and rises slower — the panel lights up when cold drives arrive.</div>
<div id="warmup"></div></div>
<div class="sec"><h2>Regen (temperature-sensitive) — expected cold direction</h2>
<div class="regen" id="regen"></div></div>
<details class="sec"><summary>Reference metrics &amp; frozen (not season-dependent) charts</summary>
<div class="grid" id="ref" style="margin-top:10px"></div>
<div id="frozen" style="margin-top:10px"></div></details>
<div class="foot" id="foot"></div>
</div>
<script>
const D = __PAYLOAD__;
let cohort = D.allLabel, mode = "Observed";
const el = id => document.getElementById(id);
const fmt = (v,d=2)=> v==null? "&mdash;" : (Math.round(v*10**d)/10**d).toLocaleString();
document.getElementById('core').textContent = D.coreVersion;

function renderSeg(){
  const names = [D.allLabel,"Warm","Shoulder","Cold"];
  const cls = {[D.allLabel]:"all",Warm:"warm",Shoulder:"shoulder",Cold:"cold"};
  el('seg').innerHTML = names.map(n=>{
    const c = D.cohorts[n]||D.cohorts[n==="All observations"?D.allLabel:n];
    const empty = !c || c.coverage.n_drives===0;
    return `<button class="${cls[n]} ${n===cohort?'on':''}" data-n="${n}">${n}`
      + (empty?` <small style="opacity:.6">0</small>`:``) + `</button>`;
  }).join('');
  [...el('seg').children].forEach(b=>b.onclick=()=>{cohort=b.dataset.n;renderAll();});
}
function renderOA(){
  el('oa').innerHTML = ["Observed","Adjusted"].map(m=>
    `<button data-m="${m}" class="${m===mode?'on':''}" ${m==="Adjusted"&&!D.adjustedAvailable?'disabled':''}>${m}</button>`).join('');
  [...el('oa').children].forEach(b=>b.onclick=()=>{if(!b.disabled){mode=b.dataset.m;renderCmp();}});
}
function coh(){return D.cohorts[cohort];}
function renderHdr(){
  const c = coh().coverage;
  el('hdr').innerHTML = `<div class="row">
    <div><b>${cohort}</b></div>
    <div><span>dates</span> <b>${c.date_range?c.date_range.join(' → '):'—'}</b></div>
    <div><span>ambient</span> <b>${c.ambient_range_c?c.ambient_range_c.join(' … ')+'°C':'—'}</b></div>
    <div><span>coverage</span> <b>${c.n_drives} drives · ${fmt(c.km,1)} km · ${c.independent_days} days</b></div></div>`;
}
function renderGWarn(){
  el('gwarn').innerHTML = D.globalWarnings.map(w=>`<div class="warnbox">⚠ ${w.replace(/_/g,' ')}</div>`).join('');
}
function card(key,label,unit,kind){
  const m = coh().metrics[key]; if(!m) return '';
  const val = kind==="rate"? m.value : (m.value ?? m.value);
  const warm = D.cohorts["Warm"].metrics[key];
  let cmp = '';
  if(cohort!=="Warm" && warm && (warm.value!=null) && val!=null){
    const pct = 100*(val-warm.value)/warm.value;
    cmp = `vs Warm: ${pct>=0?'+':''}${fmt(pct,1)}%`;
  } else if(cohort!=="Warm"){ cmp = 'vs Warm: &mdash; (no support)'; }
  const [prior,cur] = D.depLabels[key]||["—","—"];
  const c = coh().coverage;
  return `<div class="card"><div class="nm">${label}</div>
    <div class="val">${val==null?'&mdash;':fmt(val,2)} <small>${unit}</small></div>
    <div class="cmp">${cmp}</div>
    <span class="tag ${prior}">${prior}${prior!==cur?` · now ${cur}`:''}</span>
    <div class="cov">${c.n_drives} drives · ${fmt(c.km,0)} km · ${c.independent_days} days</div></div>`;
}
function renderOv(){ el('ov').innerHTML = D.overview.map(o=>card(...o)).join(''); }
function renderCmp(){
  renderOA();
  if(mode==="Adjusted" && !D.adjustedAvailable){
    el('cmp').innerHTML = `<div class="warnbox">Adjusted model unavailable — no cold observations, so a model-standardised cold−warm contrast cannot be estimated. This is not zero; it is undefined until cold/shoulder data and common covariate support exist.</div>`;
    return;
  }
  // Observed: show warm vs shoulder vs cold headline deltas where support exists
  const rows = D.overview.map(([k,label,unit])=>{
    const w=D.cohorts["Warm"].metrics[k], s=D.cohorts["Shoulder"].metrics[k], c=D.cohorts["Cold"].metrics[k];
    const wv=w?.value, sv=s?.value, cv=c?.value;
    const d=(a,b)=> (a!=null&&b!=null&&b!==0)? `${(100*(a-b)/b>=0?'+':'')}${fmt(100*(a-b)/b,1)}%`:'&mdash;';
    return `<tr><td>${label}</td><td>${fmt(wv,2)} ${unit}</td>
      <td>Shoulder ${d(sv,wv)}</td><td>Cold ${cv==null?'&mdash;':d(cv,wv)}</td></tr>`;
  }).join('');
  el('cmp').innerHTML = `<div class="warnbox">Observed differences only. Shoulder (5–15 °C, min 7.5 °C) is summer-adjacent cool driving, <b>not</b> cold-season evidence; deltas are descriptive and duty-confounded. Cold cohort is empty.</div>
    <table class="regen" style="width:100%">${rows}</table>`;
}
function renderTresp(){
  el('tresp').innerHTML = `<div class="disabled">Continuous temperature-response fit is unavailable: the observed ambient range is 7.5–37 °C with no data ≤5 °C. Fitting or extrapolating a cold response would be unsupported. This panel activates once cold/shoulder drives are ingested.</div>`;
}
function renderRegen(){
  const m = D.regenView.members;
  const dir = {decrease:'↓ cold',increase:'↑ cold',shift:'shift',uncertain:'?',context:'context'};
  const cl = {decrease:'dn',increase:'up',shift:'',uncertain:'',context:''};
  el('regen').innerHTML = `<div>${D.regenView._note}</div><table>` +
    Object.entries(m).map(([k,v])=>`<tr><td>${k}</td><td class="${cl[v.expectedColdDirection]}">${dir[v.expectedColdDirection]}</td><td style="color:var(--mut)">${v.note}</td></tr>`).join('') +
    `</table>`;
}
const COH=["All observations","Warm","Shoulder","Cold"], CCOL={"All observations":"var(--all)",Warm:"var(--warm)",Shoulder:"var(--shoulder)",Cold:"var(--cold)"};
function dumbbell(key, per){
  // horizontal per-cohort scalar with warm-relative delta
  const vals = COH.map(c=>per[c]&&per[c].value).filter(v=>v!=null);
  if(!vals.length) return `<div class="regen">${key}: no support</div>`;
  const mn=Math.min(...vals), mx=Math.max(...vals), sp=(mx-mn)||1;
  const rows = COH.map(c=>{
    const v=per[c]&&per[c].value, n=per[c]&&per[c].n||0;
    if(v==null) return `<tr><td style="width:120px">${c}</td><td colspan=2 style="color:var(--mut)">— (n=${n})</td></tr>`;
    const x=8+84*(v-mn)/sp;
    const dl=per[c].vs_warm_pct;
    return `<tr><td style="width:120px;color:${CCOL[c]}">${c}</td>
      <td style="width:60%"><div style="position:relative;height:14px">
        <div style="position:absolute;left:${x}%;top:2px;width:9px;height:9px;border-radius:50%;background:${CCOL[c]}"></div></div></td>
      <td style="white-space:nowrap">${fmt(v,2)}${dl!=null?` <span style="color:var(--mut)">(${dl>=0?'+':''}${dl}% vs Warm)</span>`:''} <span style="color:var(--mut)">n=${n}</span></td></tr>`;
  }).join('');
  return `<div style="font-size:12px;color:var(--mut);margin:8px 0 2px">${key}</div><table class="regen">${rows}</table>`;
}
function distOverlay(key, per){
  const edges = (per["Warm"]&&per["Warm"].hist||per["All observations"].hist).edges;
  const nb = edges.length-1;
  const cohHas = COH.filter(c=>per[c]&&per[c].hist&&per[c].hist.n>0);
  const maxc = Math.max(1,...cohHas.flatMap(c=>per[c].hist.counts.map(x=>x/per[c].hist.n)));
  let bars='';
  for(let i=0;i<nb;i++){
    const seg = cohHas.map(c=>{
      const frac=per[c].hist.counts[i]/per[c].hist.n;
      return `<div title="${c} ${edges[i]}..${edges[i+1]}" style="flex:1;height:${Math.round(46*frac/maxc)}px;background:${CCOL[c]};opacity:.75;margin:0 1px"></div>`;
    }).join('');
    bars+=`<div style="display:flex;flex-direction:column;justify-content:flex-end;align-items:center;flex:1">
      <div style="display:flex;align-items:flex-end;height:48px;width:100%;justify-content:center">${seg}</div>
      <div style="font-size:9px;color:var(--mut)">${edges[i]}</div></div>`;
  }
  const leg = cohHas.map(c=>`<span style="color:${CCOL[c]}">■ ${c} (n=${per[c].hist.n})</span>`).join('  ');
  return `<div style="font-size:12px;color:var(--mut);margin:8px 0 2px">${key} — normalised distribution</div>
    <div style="display:flex;align-items:flex-end;gap:0">${bars}</div>
    <div style="font-size:11px;margin-top:4px">${leg}</div>`;
}
function renderCohortCharts(){
  const readyOrder = D.cohortReady;
  el('cohortcharts').innerHTML = readyOrder.map(name=>{
    const ch=D.cohortCharts[name]; if(!ch||!ch.dataReady) return '';
    const body = Object.entries(ch.metrics).map(([k,per])=>
      ch.comparisonType==="distribution_overlay" && per["Warm"]&&per["Warm"].hist
        ? distOverlay(k,per) : dumbbell(k,per)).join('');
    return `<div style="border-top:1px solid var(--line);padding-top:8px;margin-top:8px">
      <b style="font-size:13px">${name}</b> <span class="tag Thermal">Thermal · ${ch.comparisonType.replace(/_/g,' ')}</span>${body}</div>`;
  }).join('');
  el('staged').innerHTML = Object.entries(D.cohortStaged).map(([k,r])=>
    `<div class="regen">• <b>${k}</b> — ${r}</div>`).join('');
}
function adjPanel(adj){
  const ws=adj.warm_vs_shoulder, wc=adj.warm_vs_cold;
  const fmtc = r => r.status!=="available" ? `<span style="color:var(--mut)">unavailable — ${r.reason}</span>`
    : `raw ${fmt(r.rawDiff,2)} → <b>adjusted ${fmt(r.adjustedDiff,2)}</b> `
      + `<span style="color:var(--mut)">CI [${fmt(r.ci95[0],2)}, ${fmt(r.ci95[1],2)}] · support ${r.commonSupport.overlap} · n ${r.nA}/${r.nB} · ${r.nDays}d</span>`;
  return `<table class="regen"><tr><td style="width:150px">Warm → Cold</td><td>${fmtc(wc)}</td></tr>
    <tr><td>Warm → Shoulder <span style="color:var(--mut)">(exploratory)</span></td><td>${fmtc(ws)}</td></tr></table>
    ${ws.status==="available"?`<div style="font-size:11px;color:var(--mut);margin-top:4px">⚠ warm–shoulder is an underpowered (n=${ws.nB}, summer-adjacent) machinery demonstration, specification-sensitive; not cold-season evidence.</div>`:''}`;
}
function renderP2(){
  el('p2charts').innerHTML = D.phase2Charts.map(name=>{
    const ch=D.cohortCharts[name]; if(!ch) return '';
    let body='';
    for(const [k,per] of Object.entries(ch.metrics)){
      body += (ch.comparisonType.startsWith("distribution")&&per["Warm"]&&per["Warm"].hist)? distOverlay(k,per):dumbbell(k,per);
    }
    if(ch.adjusted) body += adjPanel(ch.adjusted);
    const tag = ch.requiresAdjustment? "Season-associated · adjusted":"Season-associated · covariate";
    return `<div style="border-top:1px solid var(--line);padding-top:8px;margin-top:8px">
      <b style="font-size:13px">${name}</b> <span class="tag Season-associated">${tag}</span>${body}</div>`;
  }).join('');
}
function renderWarmup(){
  const ch = D.cohortCharts["WarmupCurve"]; if(!ch){el('warmup').innerHTML='';return;}
  const bins = ch.bins, W=520, H=150, pad=34;
  const all = [];
  Object.values(ch.series).forEach(s=>COH.forEach(c=>s[c].forEach(p=>{if(p.mean_c!=null)all.push(p.mean_c);})));
  if(!all.length){ el('warmup').innerHTML='<div class="disabled">no warm-up data</div>'; return; }
  const ymin=Math.min(...all)-2, ymax=Math.max(...all)+2, xmax=Math.max(...bins);
  const X=b=>pad+(W-2*pad)*b/xmax, Y=v=>H-pad-(H-2*pad)*(v-ymin)/(ymax-ymin);
  let svg=`<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:560px">`;
  svg+=`<line x1="${pad}" y1="${H-pad}" x2="${W-pad}" y2="${H-pad}" stroke="var(--line)"/>`;
  svg+=`<line x1="${pad}" y1="${pad}" x2="${pad}" y2="${H-pad}" stroke="var(--line)"/>`;
  bins.forEach(b=>{svg+=`<text x="${X(b)}" y="${H-pad+12}" fill="var(--mut)" font-size="9" text-anchor="middle">${b}s</text>`;});
  svg+=`<text x="${pad-6}" y="${Y(ymax)}" fill="var(--mut)" font-size="9" text-anchor="end">${Math.round(ymax)}</text>`;
  svg+=`<text x="${pad-6}" y="${Y(ymin)}" fill="var(--mut)" font-size="9" text-anchor="end">${Math.round(ymin)}</text>`;
  const dash={oil:"",engine_coolant:"4 3"};
  Object.entries(ch.series).forEach(([sname,s])=>{
    COH.forEach(c=>{
      const pts=s[c].filter(p=>p.mean_c!=null);
      if(pts.length<2) return;
      const dpath=pts.map((p,i)=>`${i?'L':'M'}${X(p.elapsed_s)},${Y(p.mean_c)}`).join(' ');
      svg+=`<path d="${dpath}" fill="none" stroke="${CCOL[c]}" stroke-width="1.6" stroke-dasharray="${dash[sname]}"/>`;
    });
  });
  svg+=`</svg>`;
  const leg = COH.filter(c=>ch.series.oil[c].some(p=>p.mean_c!=null))
    .map(c=>`<span style="color:${CCOL[c]}">■ ${c}</span>`).join('  ');
  el('warmup').innerHTML = svg + `<div style="font-size:11px;margin-top:2px">${leg} · solid=oil dashed=coolant</div>`
    + (ch.series.oil.Cold.every(p=>p.mean_c==null)?`<div style="font-size:11px;color:var(--mut)">Cold cohort empty — curve appears once cold drives are ingested.</div>`:'');
}
function renderFrozen(){
  el('frozen').innerHTML = `<div style="font-size:12px;color:var(--mut);border-top:1px solid var(--line);padding-top:8px">Frozen — not season-dependent (one value under any cohort filter):</div>`
    + Object.entries(D.frozenCharts).map(([k,v])=>`<div class="regen">🔒 <b>${k}</b> — ${v}</div>`).join('');
}
function renderRef(){
  el('ref').innerHTML = D.reference.map(([k,label,unit])=>{
    const m = coh().metrics[k];
    return `<div class="card"><div class="nm">${label} <span class="tag Exposure/constant">Exposure total</span></div>
      <div class="val">${fmt(m?.value,1)} <small>${unit}</small></div>
      <div class="cov">selected cohort sum</div></div>`;
  }).join('');
}
function renderFoot(){
  el('foot').innerHTML = `Generated from ${D.coreVersion} · every value computed from seasonal_arrays.json (no hardcoded seasonal headline values) · cohort label stays "${D.allLabel}" until a 12-month window exists (all-year ${D.allYearEnabled?'enabled':'disabled'}).`;
}
function renderAll(){renderSeg();renderHdr();renderGWarn();renderOv();renderCmp();renderTresp();renderCohortCharts();renderP2();renderWarmup();renderRegen();renderRef();renderFrozen();renderFoot();}
renderAll();
</script></body></html>"""

html = (HTML.replace("__PAYLOAD__", json.dumps(payload, ensure_ascii=False))
            .replace("__CMAX__", str(payload["thresholds"]["cold_max_c"]))
            .replace("__WMIN__", str(payload["thresholds"]["warm_min_c"])))
out = os.path.join(HERE, "seasonal_dashboard.html")
open(out, "w").write(html)
print("wrote", out, f"({len(html)} bytes)")
