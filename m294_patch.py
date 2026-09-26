#!/usr/bin/env python3
"""m294_patch.py (M294, 2026-09-25) — audit-2026-09-24 prose/label corrections.

Applies the Section 5/6/4/7b/11 wording corrections of the 24 Sep independent audit to
xtrail_summary.jsx (reader-facing prose only, every number bound to S.*), to the
record notes emitted by compute_summary_arrays._records (source + shipped payload),
and fixes three payload-metadata staleness defects found on the live 446-drive basis:
  * seasonalCharts._meta.corpusMd5 / seasonalMasterMd5 stale (cbc206a8 / 8900e9ad, 09-19)
  * ThermalFuelPenalty (seasonal copy) malformed dateSpan ["2026-09-","20260910"]
  * _artifactStamps[*].upstreamHashes carried rawManifestError (manifest absent at build)
No drive_master.csv byte changes. Idempotent: every replacement asserts it either
applies exactly as expected or has already been applied.
"""
import hashlib, json, os, re, sys

W = os.path.dirname(os.path.abspath(__file__))
P = lambda n: os.path.join(W, n)
fails = []


def sub(txt, old, new, n=1, label=""):
    c = txt.count(old)
    if c == n:
        return txt.replace(old, new)
    if c == 0 and new in txt:
        return txt  # already applied
    fails.append(f"{label or old[:60]!r}: expected {n}, found {c}")
    return txt


# ───────────────────────────── JSX ─────────────────────────────
jsx = open(P("xtrail_summary.jsx"), encoding="utf-8").read()

# helper block: derived (not hand-typed) quantities used by the rewritten prose
HELPER_ANCHOR = "const S = buildS(config, arrays);\n"
HELPER = HELPER_ANCHOR + r'''
// M294 (audit 2026-09-24): derived prose quantities. Every sentence corrected in M294 binds to
// these values (computed from the live payload), never to a hand-typed count.
const M294 = (() => {
  const mc = S.metricConvention || {};
  const g = mc.grossThroughputKwh, d = mc.grossDischargeKwh, c = mc.grossChargeKwh;
  const E = S.energyPath || {};
  const src = Object.fromEntries((E.chargeSources || []).map(s => [s.key, s]));
  const cold = S.cRateRefLines?.zones?.coldBelowC ?? 20;
  const pts = S.cRatePoints || [];
  const coldPts = pts.filter(p => p[0] < cold);
  const peak = pts.length ? pts.reduce((a, b) => (b[1] > a[1] ? b : a)) : null;
  const win = (S.socBandReset?.windows || []);
  const firstElev = win.find(w => w.elevated);
  const firstNs = win.find(w => !w.elevated);
  const dr = S.meta?.dateRange || S.dateRange;
  const cc = S.seasonalCharts?._meta?.cohortCounts || {};
  const regimes = ["warm", "shoulder", "cold"].filter(k => (cc[k] || 0) > 0)
    .map(k => k[0].toUpperCase() + k.slice(1));
  return {
    grossOverDischarge: (g && d) ? (g / d).toFixed(3) : "—",
    chargeOverDischarge: (c && d) ? (c / d).toFixed(3) : "—",
    grossKwh: g, dischargeKwh: d, chargeKwh: c,
    engOnNonBrakePct: src.eng_only?.pct, overlapPct: src.dual?.pct,
    engOffBrakePct: src.pure_regen?.pct, engOffResidPct: src.lowtq_engoff?.pct,
    engOnPct: E.engOnChargePct, brakingStatesPct: E.regenTouchedPct,
    coldC: cold, nColdPts: coldPts.length, nPts: pts.length,
    maxColdC: coldPts.length ? Math.max(...coldPts.map(p => p[1])).toFixed(1) : null,
    minPtT: pts.length ? Math.min(...pts.map(p => p[0])) : null,
    peakC: peak ? peak[1] : null, peakT: peak ? peak[0] : null,
    socFirstElevH: firstElev ? firstElev.withinH : null,
    socFirstNsH: firstNs ? firstNs.withinH : null,
    socFirstNsP: firstNs ? firstNs.pVsBaseline : null,
    socWin6: win.find(w => w.withinH === 6) || null,
    socWin24: win.find(w => w.withinH === 24) || null,
    dateRange: dr,
    regimesObserved: regimes.length ? regimes.join("/") : "—",
    coldObserved: (cc.cold || 0) > 0,
  };
})();
'''
if "const M294 = (() =>" not in jsx:
    jsx = sub(jsx, HELPER_ANCHOR, HELPER, label="M294 helper")

# ---- Conclusions: wrong comparator (P0) ----
jsx = sub(jsx,
    'metric={`gross throughput ${S.grossThroughputKwh?.toLocaleString()} kWh vs ${S.metricConvention?.chargeDischargeRatio ?? "~2"}× the net SoC change`}',
    'metric={`gross throughput ${M294.grossKwh?.toLocaleString()} kWh = ${M294.grossOverDischarge}× gross discharge (${M294.dischargeKwh?.toLocaleString()} kWh) · charge/discharge ${M294.chargeOverDischarge}`}',
    label="C1 metric")
jsx = sub(jsx,
    'Gross throughput (energy cycled through the cells) runs about twice net discharge, and on most drives the pack ends at equal-or-higher SoC than it started — the buffer lands near where it began rather than being drained."',
    'Pack-terminal gross throughput (charge + discharge) is about twice gross discharge because charge and discharge are nearly equal; the per-drive SoC change is small relative to either, so the buffer lands near where it began rather than being drained. Net SoC change is a percentage signal, not a measured energy — it is not converted to kWh here without a capacity/OCV model."',
    label="C1 text")
jsx = sub(jsx,
    'caveat="Interpretation of an observed usage pattern, not a measured chemistry or capacity. Every throughput figure scales with the unverified 2.1 kWh capacity constant."',
    'caveat="Interpretation of an observed usage pattern, not a measured chemistry or capacity. Pack-terminal kWh (∫V·I dt) are measured and do NOT depend on pack capacity; GTC/FCE and C-rate are normalised by the unverified 2.1 kWh constant and scale with it; rainflow EFC is derived from SoC percentage amplitudes and does not."',
    label="C1 caveat")

# ---- Conclusions: source attribution (P0) ----
jsx = sub(jsx,
    'title="Generator charging supplies most of the measured pack-charge energy; regenerative braking is a bounded minority"',
    'title="Pack charge by operating state: most charge arrives while the engine is on; engine-off braking is the clearest regenerative proxy"',
    label="regen title")
jsx = sub(jsx,
    'metric={`regen ${S.regenByTypeMeta?.regenShareLoPct}–${S.regenByTypeMeta?.regenShareHiPct}% vs generator ${S.regenByTypeMeta?.generatorShareLoPct}–${S.regenByTypeMeta?.generatorShareHiPct}% of ${S.regenByTypeMeta?.totalKwh} kWh charged`}',
    'metric={`engine-on ${M294.engOnPct}% (non-braking ${M294.engOnNonBrakePct}% + braking overlap ${M294.overlapPct}%) · engine-off braking ${M294.engOffBrakePct}% · engine-off residual ${M294.engOffResidPct}% of ${S.energyPath?.chargeKwh} kWh pack charge`}',
    label="regen metric")
jsx = sub(jsx,
    'generator charging dominates measured pack-charge energy and regenerative braking supplies a bounded minority. This describes CHARGE-SOURCE composition only:',
    'the shares are OPERATING-STATE tallies of measured pack charge, not metered sources: charge while the engine is on is likely engine-driven but the pack shunt does not meter generator output; engine-off braking charge is the strongest identifiable regenerative-braking-at-pack proxy; in the engine-on/braking overlap the physical generator/regen split is unidentified; the engine-off residual is unattributed. This describes operating-state composition only:',
    label="regen text")
jsx = sub(jsx,
    '<GeneralConclusion status="derived" text="Generator charging dominates pack input and regenerative braking is a bounded minority of charge; net SoC change is a poor work metric because the buffer usually lands near where it started." metric={`regen ${S.regenByTypeMeta?.regenShareLoPct}–${S.regenByTypeMeta?.regenShareHiPct}%`} />',
    '<GeneralConclusion status="derived" text={`${M294.engOnPct}% of observed pack charge occurred with the engine on; ${M294.engOffBrakePct}% occurred during engine-off braking; a further ${M294.overlapPct}% overlapped braking and engine-on, where the physical generator/regen split is unidentified. Net SoC change is a poor work metric because the buffer usually lands near where it started.`} metric={`engine-off braking ${M294.engOffBrakePct}%`} />',
    label="GC regen")

# ---- Conclusions: SoC ceiling reset (P1) ----
jsx = sub(jsx,
    'title="The highway ceiling elevation is short-lived and largely concurrent"',
    'title="The highway ceiling elevation is concurrent with highway driving and is not resolved afterwards"',
    label="socReset title")
jsx = sub(jsx,
    'metric={`highway ceiling median ${S.socBandReset?.highwayCeilMedPct}% vs urban baseline ${S.socBandReset?.baselineCeilMedPct}% · indistinguishable by ~12 h`}',
    'metric={`highway ceiling median ${S.socBandReset?.highwayCeilMedPct}% vs urban baseline ${S.socBandReset?.baselineCeilMedPct}% · later urban drives: ≤6 h ${M294.socWin6?.ceilMedPct ?? "—"}% (p=${M294.socWin6?.pVsBaseline ?? "—"}), ≤24 h ${M294.socWin24?.ceilMedPct ?? "—"}% (p=${M294.socWin24?.pVsBaseline ?? "—"})`}',
    label="socReset metric")
jsx = sub(jsx,
    'This is demand-triggered adaptation, not a decaying learned state.`}',
    '${M294.socFirstElevH != null ? `An elevation remains resolved in urban drives within ${M294.socFirstElevH} h of highway driving; none is resolved at longer windows.` : `No ceiling elevation is resolved in later urban drives at any tested window (≤6 h onward).`} Non-significance at a later window does not prove a reset or a controller memory mechanism; the data are consistent with demand-triggered adaptation.`}',
    label="socReset text")
jsx = sub(jsx,
    '<GeneralConclusion status="measured" text="The controller raises the SoC ceiling on the highway to reserve transient headroom, and lets it relax back into subsequent urban driving within hours — a demand-triggered adaptation, not a persistent learned state." metric={`+${ceilDeltaMed} pp ceiling`} />',
    '<GeneralConclusion status="measured" text={`The SoC ceiling is higher during highway driving; in subsequent urban drives ${M294.socFirstElevH != null ? `an elevation is resolved only within ${M294.socFirstElevH} h` : "no elevation is resolved at any tested window"}. This is consistent with demand-triggered adaptation; non-significance does not prove a reset mechanism.`} metric={`+${ceilDeltaMed} pp ceiling`} />',
    label="GC socReset")

# ---- Conclusions: DoD spec-cycle comparator (P1) ----
jsx = sub(jsx,
    'shows most cycles are tiny; even the deepest is shallow against a ~25\\u201330% spec cycle.',
    'shows most cycles are tiny: ${S.rfDodHistogram?.le2PctShare}% of counted cycles have DoD \\u22642% and the deepest reaches ${S.rfDodHistogram?.maxDodPct}%.',
    label="rainflow text")

# ---- Conclusions: date / regime binding (P1) ----
jsx = sub(jsx,
    'coverage="Warm-season data only (May–Aug); no cold-pack thermal behaviour observed."',
    'coverage={`Observed ${M294.dateRange} temperature regimes (${M294.regimesObserved}; no Cold); no cold-pack thermal behaviour observed.`}',
    label="thermal coverage")
jsx = sub(jsx,
    'All measured cycle-intensity inputs are May–Aug data — winter cold-start driving, the study\'s highest-priority gap, is not yet captured."',
    'All measured inputs span ${M294.dateRange} (${M294.regimesObserved} regimes; no Cold) — winter cold-start driving, the study\'s highest-priority gap, is not yet captured.`}',
    label="cap text end")
jsx = sub(jsx,
    'text="The 2.1 kWh figure is an assumed normalization constant; it is unverified and not an OEM nameplate figure, and every GTC/FCE/C-rate figure scales with it.',
    'text={`The 2.1 kWh figure is an assumed normalization constant; it is unverified and not an OEM nameplate figure. GTC/FCE and C-rate scale with it; measured pack-terminal kWh and SoC-derived rainflow EFC do not.',
    label="cap text start")
jsx = sub(jsx,
    '<GeneralConclusion status="measured" text="Within this warm-season window the pack showed a bounded thermal ceiling under sustained highway load, with a small, consistent probe-to-mean gradient."',
    '<GeneralConclusion status="measured" text={`Within the observed ${M294.dateRange} window (${M294.regimesObserved}; no Cold) the pack showed a bounded thermal ceiling under sustained highway load, with a small, consistent probe-to-mean gradient.`}',
    label="GC thermal")
jsx = sub(jsx,
    '<GeneralConclusion status="limited" text="This is single-vehicle observational telemetry over one warm season, with an assumed pack capacity',
    '<GeneralConclusion status="limited" text={`This is single-vehicle observational telemetry over ${M294.dateRange} (${M294.regimesObserved} regimes; no Cold), with an assumed pack capacity',
    label="GC boundaries start")
jsx = sub(jsx,
    'it makes no fleet-level or causal claims and quotes no end-of-life year." />',
    'it makes no fleet-level or causal claims and quotes no end-of-life year.`} />',
    label="GC boundaries end")

# ---- Conclusions / thermal: heat-soak overinterpretation (P1) ----
jsx = sub(jsx,
    'title="Pack warms with a characteristic time constant, and cools far more slowly"',
    'title="Pack warm-up is fast relative to inter-drive cooling (descriptive; soak fit unvalidated)"',
    label="soak title")
jsx = sub(jsx,
    'The pack cools on the order of ${(() => { const c=S.heatSoakCarryover, t=S.thermalStepResponse; return (c?.soakTauH!=null && t?.tauWarmupMinMedian!=null) ? Math.round(c.soakTauH*60/t.tauWarmupMinMedian) : "\\u2014"; })()}× slower than it heats.`}',
    'The warm-up \\u03C4 rests on ${S.thermalStepResponse?.nFits} of ${S.thermalStepResponse?.nCandidates} gated candidates, and the soak time constant is a Sen-slope summary with recorded fit R\\u00B2=${S.heatSoakCarryover?.tauFitR2} over ${S.heatSoakCarryover?.tauFitN} pairs \\u2014 a negative R\\u00B2 means the first-order model does not describe the pairs, so no heat-up/cool-down time-constant ratio is claimed as a property of the pack.`}',
    label="soak text")
jsx = sub(jsx,
    'metric={`warmup \\u03C4 ${S.thermalStepResponse?.tauWarmupMinMedian} min (${S.thermalStepResponse?.nFits} fits, R\\u00B2 ${S.thermalStepResponse?.fitR2Median}) vs heat-soak \\u03C4 ${S.heatSoakCarryover?.soakTauH} h`}',
    'metric={`warmup \\u03C4 ${S.thermalStepResponse?.tauWarmupMinMedian} min (${S.thermalStepResponse?.nFits}/${S.thermalStepResponse?.nCandidates} fits, R\\u00B2 ${S.thermalStepResponse?.fitR2Median}) · soak summary ${S.heatSoakCarryover?.soakTauH} h (fit R\\u00B2 ${S.heatSoakCarryover?.tauFitR2}, unvalidated)`}',
    label="soak metric")
jsx = sub(jsx,
    '<GeneralConclusion status="modelled" text="The pack warms in tens of minutes but sheds heat over roughly half a day, so a warm pack carries thermal state across short inter-drive gaps." metric={`soak τ ${S.heatSoakCarryover?.soakTauH} h`} />',
    '<GeneralConclusion status="measured" text="Observed inter-drive pairs show a warm pack retains part of its above-ambient excess across short gaps; the first-order soak fit does not describe these pairs (negative R²), so no cooling time constant is claimed as a pack property." metric={`soak fit R² ${S.heatSoakCarryover?.tauFitR2}`} />',
    label="GC soak")
jsx = sub(jsx,
    '["Time constant (\\u03C4) / half-life","How fast something heats or cools; the pack cools ~29\\u00D7 slower than it heats."],',
    '["Time constant (\\u03C4) / half-life","How fast something heats or cools under a first-order model; only meaningful where the fit describes the data (R\\u00B2 > 0)."],',
    label="glossary tau")

# ---- Conclusions: regen efficiency -> apparent KE recovery proxy (P1) ----
jsx = sub(jsx, 'title="Regen capture efficiency rises with speed to a plateau"',
          'title="Apparent kinetic-energy recovery proxy rises with speed to a plateau"', label="regen cap title")
jsx = sub(jsx, 'text="Apparent capture efficiency climbs from very low at crawl speeds',
          'text="The apparent kinetic-energy recovery proxy (measured pack charge ÷ assumed-mass ½m·Δv², no grade, friction, aero or rolling loss) climbs from very low at crawl speeds', label="regen cap text")
jsx = sub(jsx, '<GeneralConclusion status="derived" text="Regen capture efficiency rises with speed to a plateau and is weak at crawl;',
          '<GeneralConclusion status="derived" text="The apparent kinetic-energy recovery proxy (assumed mass, no grade/loss terms) rises with speed to a plateau and is weak at crawl;', label="GC regen cap")
jsx = sub(jsx, 'title:"Regen capture efficiency by ambient bin (%)"', 'title:"Apparent KE recovery proxy by ambient bin (%)"', label="chart1")
jsx = sub(jsx, 'title:"Regen capture efficiency vs speed (%)"', 'title:"Apparent KE recovery proxy vs speed (%)"', label="chart2")
jsx = sub(jsx, 'title:"Regen capture efficiency by speed zone (%)"', 'title:"Apparent KE recovery proxy by speed zone (%)"', label="chart3")

# ---- Conclusions: power fade / capacity (P1) ----
jsx = sub(jsx,
    'Resistance rise is the more plausible functional limit for a hard-worked buffer, and it is the only degradation axis this dataset can observe at all.`}',
    'A power (resistance) proxy can be monitored with this design; capacity SOH cannot. Resistance rise is a plausible functional limit for a hard-worked buffer, but that is a hypothesis, not an observation.`}',
    label="power fade text")
jsx = sub(jsx,
    '<GeneralConclusion status="limited" text="Capacity fade cannot be identified from this telemetry at all; power (resistance) fade is the only degradation axis this design can partially track, through a load-excited proxy rather than an isolated DC-resistance measurement." />',
    '<GeneralConclusion status="limited" text="Capacity SOH cannot be identified from this telemetry; a power proxy can be monitored, through a load-excited regression rather than an isolated DC-resistance measurement, and the cell-voltage spread is a second, separate indicator." />',
    label="GC power fade")

# ---- Methods note: net discharge vs cell-load (P1) ----
jsx = sub(jsx,
    '<strong style={{color:"#4ade80"}}>net discharge</strong> (net SoC change per km) for battery-draw / cell-load tracking,',
    '<strong style={{color:"#4ade80"}}>net discharge</strong> (net SoC change per km) for SoC drift only (a signed balance, not a load measure); gross discharge per 100 km for outbound battery work;',
    label="net discharge")

# ---- Health: cold-start charging row (P0) ----
jsx = sub(jsx,
    '"Cold-start high-rate charging": {\n                status:"NOT YET MEASURABLE",\n                detail:`Remains the study\'s #1 named risk on chemistry grounds \\u2014 lithium plating on charge below ~${S.cRateRefLines?.zones?.coldBelowC ?? "\\u2014"}\\u00B0C \\u2014 but it is asserted, not demonstrated. The coldest pack means logged reach ~12\\u00B0C, yet those earliest May drives predate the HV-current PID, so the coldest drive carrying a usable charge C-rate sits near the zone boundary itself. No measured charge C-rate therefore exists for a genuinely cold pack anywhere in the corpus, and the previously quoted "9.7-34.5C at 10-12\\u00B0C cells" does not reproduce from drive_master.csv. Closing this needs winter logging with the full PID set.`',
    '"Cold-start high-rate charging": {\n                status:"MODERATELY COOL EXPOSURE MEASURED",\n                detail:`Moderately cool charging exposure is measured: ${M294.nColdPts} of ${M294.nPts} plotted per-drive charge peaks sit below the ${M294.coldC}\\u00B0C reference line (co-timed battery temperature, coldest ${M294.minPtT}\\u00B0C; highest ${M294.maxColdC ?? "\\u2014"}C on the assumed-capacity C scale). Plating occurrence and winter cold-pack behaviour are unmeasured: no drive with ambient \\u2264${S.seasonalCharts?._meta?.thresholds?.cold?.replace("<=","") ?? "5"}\\u00B0C exists (Cold cohort n=${S.seasonalCharts?._meta?.cohortCounts?.cold ?? 0}), and a charge peak at a cool temperature is an exposure, not evidence of chemical damage. The ${M294.coldC}\\u00B0C line is generic Li-ion guidance, not a validated Nissan limit. Closing the gap needs winter logging with the full PID set.`',
    label="health cold row")

# ---- Health / thermal: C-rate section stale literals (P1) ----
jsx = sub(jsx,
    'All occur in the optimal temperature zone — thermal risk is low, but cumulative frequency matters. v3 convention: C = A / 5.86 Ah measured capacity.{" "}',
    'The highest plotted peak ({M294.peakC}C) was co-timed with a {M294.peakT}°C pack; {M294.nColdPts} of {M294.nPts} peaks sit below the {M294.coldC}°C line (highest there {M294.maxColdC ?? "—"}C). C-rate convention: C = A ÷ ({S.constantProvenance?.CAP_KWH?.value ?? 2.1} kWh assumed capacity ÷ nominal pack voltage) — an ASSUMED Ah denominator, not a measured capacity; the current in A is the measured quantity.{" "}',
    label="crate zone sentence")
jsx = sub(jsx,
    '6 points move from the optimal band into the cold-risk zone (10 → 16 points below {S.cRateRefLines?.zones?.coldBelowC ?? 20}°C; the highest C-rate now paired with a sub-20°C pack is 23.8C, not the previous 18.9C);',
    'points move from the optimal band into the cold-risk zone (on the live payload {M294.nColdPts} of {M294.nPts} points sit below {S.cRateRefLines?.zones?.coldBelowC ?? 20}°C; highest there {M294.maxColdC ?? "—"}C);',
    label="crate 10->16")

# ---- §4 EnergyArchitecture: masquerading source labels (P0) ----
jsx = sub(jsx,
    '          Every energy figure in this study originates at this one sensor. It measures current\n          crossing the pack terminals and nothing else — which is why the charge decomposition below\n          is exact and the fuel-side chain is absent rather than estimated.',
    '          Every PACK-TERMINAL energy figure originates at this one sensor. It measures current\n          crossing the pack terminals and nothing else — the state partition below closes by construction,\n          but it is not a metered source split. Fuel, generator and traction energies elsewhere (§4b) are modelled.',
    label="shunt hover")
jsx = sub(jsx,
    '        Measured — where the {E.chargeKwh.toLocaleString()} kWh that entered the pack came from',
    '        Operating-state charge partition — the {E.chargeKwh.toLocaleString()} kWh of measured pack charge, by engine/braking state',
    label="partition heading")
jsx = sub(jsx,
    '[`${E.regenTouchedPct}%`,"of charge involved regen",\n           `engine-off regen plus dual-source; ${E.engOffChargePct}% arrived with the engine off entirely`,"#22c55e"],',
    '[`${E.regenTouchedPct}%`,"of charge during braking states",\n           `engine-off braking plus engine-on/braking overlap (physical split unidentified); ${E.engOffChargePct}% arrived with the engine off`,"#22c55e"],',
    label="tile regen")
jsx = sub(jsx,
    '[`${E.engOnChargePct}%`,"of charge from engine-on",\n           "generator-only plus the engine share of dual-source intervals","#f59e0b"],',
    '[`${E.engOnChargePct}%`,"of charge while engine on",\n           "engine-on non-braking plus engine-on/braking overlap — an operating state, not a metered generator share","#f59e0b"],',
    label="tile engine")
jsx = sub(jsx,
    '`${E.chargeKwh} in / ${E.dischargeKwh} out — round-trip + sensor-offset residual, see M24`',
    '`${E.chargeKwh} in / ${E.dischargeKwh} out — signed pack inflow/outflow imbalance (incl. sensor-offset residual, M24); not a measured round-trip inefficiency`',
    label="tile asym")

# ---- Cross-vehicle: CAP-invariant label (P1) ----
jsx = sub(jsx,
    'this rail is built from a separate master and only CAP-invariant quantities are shown.',
    'this rail is built from a separate master. Rows are capacity-independent (%, A, Ω, mV, °C) except GTC per 100 km, which assumes an equal 2.1 kWh capacity on both vehicles and is assumption-normalised.',
    label="xv seg")
jsx = sub(jsx, '>Metric (CAP-invariant)</th>', '>Metric (capacity-independent unless marked)</th>', label="xv th")
jsx = sub(jsx, '"e-4ORCE AWD cross-check rail (segregated, CAP-invariant only)"',
          '"e-4ORCE AWD cross-check rail (segregated; capacity-independent quantities, GTC assumption-normalised)"', label="xv index")

open(P("xtrail_summary.jsx"), "w", encoding="utf-8").write(jsx)

# ─────────────────── record prose: builder source + payload ───────────────────
REC = [
    ("'equilibrates against passive dissipation rather than running away.',",
     "'reached without runaway in these logs; a finite maximum is a sampled extremum, not a test of asymptotic thermal equilibrium.',",
     "equilibrates against passive dissipation rather than running away.",
     "reached without runaway in these logs; a finite maximum is a sampled extremum, not a test of asymptotic thermal equilibrium."),
    ("'it is also the dataset\\'s deepest single DoD event -- still shallow '\n         'against the ~25-30% DoD of a spec cycle.',",
     "'it is also the dataset\\'s deepest single DoD event.',",
     "it is also the dataset's deepest single DoD event -- still shallow against the ~25-30% DoD of a spec cycle.",
     "it is also the dataset's deepest single DoD event."),
    ("'Highest SoC the BMS allowed. The buffer ceiling is a control '\n         'decision, not a full charge -- the pack is never taken to 100%, which '\n         'is itself a life-preserving strategy.',",
     "'Highest SoC observed in these logs. It does not establish the absolute '\n         'controller ceiling or BMS intent; no logged drive reached 100%.',",
     "Highest SoC the BMS allowed. The buffer ceiling is a control decision, not a full charge -- the pack is never taken to 100%, which is itself a life-preserving strategy.",
     "Highest SoC observed in these logs. It does not establish the absolute controller ceiling or BMS intent; no logged drive reached 100%."),
    ("'Longest continuous stretch of net discharge above 130 km/h. Bounds '\n         'how long the buffer can subsidise the generator before the SoC floor '\n         'forces a speed-or-recharge compromise.',",
     "'Longest continuous stretch of net discharge above 130 km/h (an observed '\n         'run maximum, not a limit set by the SoC floor; read beside cumulative '\n         '130+ km/h exposure).',",
     "Longest continuous stretch of net discharge above 130 km/h. Bounds how long the buffer can subsidise the generator before the SoC floor forces a speed-or-recharge compromise.",
     "Longest continuous stretch of net discharge above 130 km/h (an observed run maximum, not a limit set by the SoC floor; read beside cumulative 130+ km/h exposure)."),
]
src = open(P("compute_summary_arrays.py"), encoding="utf-8").read()
for old_src, new_src, _, _ in REC:
    src = sub(src, old_src, new_src, label="src " + old_src[:40])
open(P("compute_summary_arrays.py"), "w", encoding="utf-8").write(src)

A = json.load(open(P("summary_arrays.json"), encoding="utf-8"))
for _, _, old_p, new_p in REC:
    hit = 0
    for r in A["records"]:
        if old_p in r["note"]:
            r["note"] = r["note"].replace(old_p, new_p); hit += 1
        elif new_p in r["note"]:
            hit += 1
    if hit != 1:
        fails.append(f"payload record {old_p[:40]!r}: {hit} hits")

# ─────────────────── payload source-attribution labels ───────────────────
ep = A["energyPath"]
ep["basis"] = ep["basis"].replace("Corpus-level HV-bus energy accounting", "Corpus-level pack-terminal energy accounting")
ep["basis"] = ep["basis"].replace("The charge-source split is the M12", "The operating-state charge partition is the M12")
for s in ep["chargeSources"]:
    if s["key"] == "pure_regen":
        s["detail"] = ("engine OFF, motor braking — strongest regenerative-braking-at-pack proxy, "
                       "conditional on the torque/RPM state classification")
    if s["key"] == "dual":
        s["detail"] = ("engine ON while the motor brakes — mixed operating state; the physical split between "
                       "generator output and recovered braking energy is unidentified")
    if s["key"] == "eng_only":
        s["detail"] = ("engine ON, motor not braking (target torque >= -15 N·m) — engine contribution likely, but the "
                       "pack shunt does not meter generator output")
    if s["key"] == "lowtq_engoff":
        s["detail"] = ("engine OFF, motor not braking — unattributed by the -15 N·m threshold; not a metered "
                       "motor or generator source")
cv = A["crossVehicle"]["_meta"]
cv["admissibility"] = cv["admissibility"].replace(
    "CAP_KWH-invariant quantities only (%, A, 1/h, Ohm, mV, degC, ratios).",
    "Capacity-independent quantities (%, A, 1/h, Ohm, mV, degC, ratios); GTC per 100 km, where shown, assumes an equal 2.1 kWh capacity on both vehicles and is assumption-normalised.")

# ─────────────────── staleness defects ───────────────────
md5 = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()
live_md5 = md5(P("drive_master.csv"))
sm = A["seasonalCharts"]["_meta"]
if sm.get("corpusMd5") != live_md5:
    sm["corpusMd5PreviousStale"] = sm.get("corpusMd5")
    sm["corpusMd5"] = live_md5
    sm["seasonalMasterMd5"] = md5(P("seasonal_drive_master.csv"))
    sm["md5RestampNote"] = ("M294: _meta.corpusMd5/seasonalMasterMd5 were frozen at the 2026-09-19 build and never "
                            "re-stamped by the M290-M293 refreshes; re-stamped to the live files. Cohort counts in "
                            "this block already matched the live 446-drive corpus; per-chart carry-forward status "
                            "is in seasonalCharts._staleness.")

tfp = A["seasonalCharts"]["charts"]["ThermalFuelPenalty"]["data"]
def _iso(t):
    t = str(t)
    if re.fullmatch(r"\d{8}", t):
        return f"{t[:4]}-{t[4:6]}-{t[6:]}"
    return t if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t) else None
spans = []
for k, v in tfp.items():
    if isinstance(v, dict) and isinstance(v.get("dateSpan"), list):
        spans.append((k, v["dateSpan"]))
for k, ds in spans:
    a, b = (_iso(x) for x in ds)
    if a is None or b is None:
        # recover bounds from the cohort spans that ARE well-formed, else from the top-level block basis
        good = [(_iso(x), _iso(y)) for kk, (x, y) in spans if _iso(x) and _iso(y)]
        lo = min([g[0] for g in good], default=None) or a
        hi = max([g[1] for g in good], default=None) or b
        tfp[k]["dateSpan"] = [A["thermalFuelPenalty"]["dateSpan"][0], "2026-09-16"]
        tfp[k]["dateSpanNote"] = ("M294: source span was malformed (fn[:8] day-key defect: dashed-name drives Sep 11-16 collapsed into one "
            "'2026-09-' key). Bounds shown are the fuel-accumulator subset start (from the correctly keyed top-level thermalFuelPenalty "
            "block) and the last day of this chart's 410-drive basis (upper bound for this cohort). Exact per-cohort bounds, nDays and "
            "day-cluster CIs regenerate on the next raw-pass rebuild of this carried-forward chart.")
    else:
        tfp[k]["dateSpan"] = [a, b]

rm = json.load(open(P("raw_manifest.json"), encoding="utf-8"))
nfix = 0
for k, st in A["_artifactStamps"].items():
    uh = st.get("upstreamHashes") if isinstance(st, dict) else None
    if isinstance(uh, dict) and "rawManifestError" in uh:
        uh.pop("rawManifestError")
        uh["rawManifestCorpusHash"] = rm.get("corpusHash")
        uh["rawManifestSnapshotId"] = rm.get("snapshotId")
        uh["rawManifestContentHash"] = rm.get("contentHash")
        uh["rawManifestBackfill"] = "M294: raw_manifest.json was absent at the M293 array build; identity backfilled from the 2026-09-25 446-drive manifest."
        nfix += 1

json.dump(A, open(P("summary_arrays.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"stamps backfilled: {nfix}; TFP spans: {[(k, tfp[k]['dateSpan']) for k, _ in spans]}")
if fails:
    print("M294 PATCH FAILED:"); [print("  -", f) for f in fails]; sys.exit(1)
print("M294 patch applied cleanly")


# ─────────── M294 addendum: remaining causal / capability wording in record notes ───────────
REC2 = [
    ("'current, brackets the C-rate envelope the buffer actually sees -- '\n         'the mechanical driver of resistance growth and power fade.',",
     "'current, brackets the observed current envelope. High current is a '\n         'plausible ageing stressor; this record is exposure, not measured damage.',",
     "With charge current, brackets the C-rate envelope the buffer actually sees -- the mechanical driver of resistance growth and power fade.",
     "With charge current, brackets the observed current envelope. High current is a plausible ageing stressor; this record is exposure, not measured damage."),
    ("'on a cold pack is the plating-risk channel; this dataset\\'s peaks all '\n         'occur warm.',",
     "'on a cold pack is the literature plating-risk channel; this absolute '\n         'peak was not set cold (see the C-rate map for sub-20 C peaks).',",
     "Charge acceptance at high C-rate on a cold pack is the plating-risk channel; this dataset's peaks all occur warm.",
     "Charge acceptance at high C-rate on a cold pack is the literature plating-risk channel; this absolute peak was not set cold (see the C-rate map for sub-20 C peaks)."),
    ("'plus regen the pack can sink at once before the BMS tapers current.',",
     "'plus regen the pack absorbed at once in these logs -- an observed '\n         'maximum, not a rated acceptance limit.',",
     "Bounds how much generator surplus plus regen the pack can sink at once before the BMS tapers current.",
     "Bounds how much generator surplus plus regen the pack absorbed at once in these logs -- an observed maximum, not a rated acceptance limit."),
    ("'Highest absolute load on the 1.5 VC-Turbo generator. In series '",
     "'Highest in-range OBD Absolute Engine Load PID value (can exceed 100% '\n         'under boost; not a rated engine capability). In series '",
     "Highest absolute load on the 1.5 VC-Turbo generator. In series",
     "Highest in-range OBD Absolute Engine Load PID value (can exceed 100% under boost; not a rated engine capability). In series"),
]
src = open(P("compute_summary_arrays.py"), encoding="utf-8").read()
for o, n, _, _ in REC2:
    src = sub(src, o, n, label="src2 " + o[:40])
open(P("compute_summary_arrays.py"), "w", encoding="utf-8").write(src)
A = json.load(open(P("summary_arrays.json"), encoding="utf-8"))
for _, _, o, n in REC2:
    hit = 0
    for r in A["records"]:
        if o in r["note"]:
            r["note"] = r["note"].replace(o, n); hit += 1
        elif n in r["note"]:
            hit += 1
    if hit != 1:
        fails.append(f"payload record2 {o[:40]!r}: {hit}")
json.dump(A, open(P("summary_arrays.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
if fails:
    print("M294 addendum FAILED:", fails); sys.exit(1)
print("M294 addendum applied")


# ─────────── M294 addendum 2: residual contradictions found in rendered-text review ───────────
jsx = open(P("xtrail_summary.jsx"), encoding="utf-8").read()
jsx = sub(jsx, 'Ordering all drives on wall-clock time, the elevation survives into later urban driving only briefly and hours-since-highway does not predict urban ceiling monotonically', 'Ordering all drives on wall-clock time, hours-since-highway does not predict the later urban ceiling monotonically', label="socReset residual")
jsx = sub(jsx, 'Fitted first-order warmup responses give a median rise time of tens of minutes; inter-drive heat-soak relaxes over ~half a day (half-life ${S.heatSoakCarryover?.soakHalfLifeH} h). ', 'Fitted first-order warmup responses give a median rise time of tens of minutes, while observed inter-drive pairs still retain part of the above-ambient excess after multi-hour gaps. ', label="soak residual")
open(P("xtrail_summary.jsx"), "w", encoding="utf-8").write(jsx)
if fails:
    print("M294 addendum2 FAILED:", fails); sys.exit(1)
