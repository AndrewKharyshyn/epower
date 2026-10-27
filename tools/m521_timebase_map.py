#!/usr/bin/env python3
"""M521 (analyses/M521_spec.md): read-only mapping of the dashboard lines that quote engine-on time to the payload key, producer and denominator (time base).
Reads xtrail_summary.jsx, compute_summary_arrays.py, summary_arrays.json. Writes analyses/M521_mapping.json. Changes nothing else; no new estimator.
Base codes: B1 = eng_rpm > 300 on the 1 Hz grid, time-weighted (rpmDistribution, engineOnDuration); B1n = rpm > 300 on native-cadence rows, row-count share (engineOnBySpeed); B2 = eng_rpm > 400 inside RPM-supported intervals (M512
engineRuntime); B3 = B2 duration-scaled imputed; B4 = eng_rpm > 400 on the 1 Hz grid with a moving filter (rsync/dst blocks); B5 = boost-PID-drives sample-weighted
share over RPM bands (turboByRpm); B6 = detector-defined (engineStartRate); X = base not identified from code (left unchanged)."""
import json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
J = open(os.path.join(ROOT, "xtrail_summary.jsx"), encoding="utf-8").read().split("\n")
P = open(os.path.join(ROOT, "compute_summary_arrays.py"), encoding="utf-8").read().split("\n")
A = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
INV = json.load(open(os.path.join(ROOT, "analyses", "M520_timebase_inventory.json"), encoding="utf-8"))

# line -> (anchor substring that must be on the line, payload key, producer anchor in compute_summary_arrays.py, base, note). Curated from the code read for M521;
# every anchor is verified below so a drifted line number fails loudly instead of mapping the wrong text.
MAP = {
 1462: ("engine-on time share", "engineOnBySpeed", "# ---- engineOnBySpeed ----", "B1n", "blind audit: share of native-cadence valid speed+rpm rows with rpm > 300 per speed zone (row count, not time-weighted)"),
 5428: ("OPT", "rpmFinding", "rpmFinding", "X", "denominator of the band share not traced in M521 step 1; unresolved"),
 5518: ("charge-and-drive", "simultaneity", "simultaneity", "X", "state shares of engine-on time; engine-on rule of the simultaneity block not traced; unresolved"),
 5521: ("Basis note", "simultaneity", "simultaneity", "X", "names its basis (per-second, M265) but not the engine-on threshold"),
 6077: ("Engine off", "rpmDistribution", "out['rpmDistribution'] = {", "B1", "pooled hours; engine-off bin = rpm <= 300; text already says 'all gridded time'"),
 9581: ("of engine-on time clamped", "rpmSyncPoint", "_RSYNC_ENG_ON = 400.0", "B4", "rpm > 400 on the 1 Hz grid with speed >= _RSYNC_MOVE_V (moving); per-drive fraction"),
 9604: ("peakPctOfEngineOn", "rpmDistribution", "out['rpmDistribution'] = {", "B1", "peak bin hours / sum(bins[1:]) = pooled rpm>300 hours"),
 9609: ("engine-on hours", "rpmDistribution", "out['rpmDistribution'] = {", "B1", "pooled share contrasted with per-drive median of B4 load-point fraction: two different bases in one sentence"),
 9611: ("engine-on hours", "rpmDistribution", "out['rpmDistribution'] = {", "B1", "same sentence as 9609"),
 10502: ("RPM occupancy", "rpmDistribution", "out['rpmDistribution'] = {", "B1", "pct of engine-on (bins[1:]) per state"),
 10874: ("RPM-band occupancy", "engineStateMachine", "engineStateMachine", "X", "state machine occupancy; engine-on rule not traced"),
 10983: ("Engine-on time share", "engineOnBySpeed", "# ---- engineOnBySpeed ----", "B1n", "see 1462"),
 11630: ("RPM above", "engineStartRate", "engineStartRate", "B6", "detector-defined ON runs; the line states the detector rpm"),
 12008: ("boost-pressure", "turboMeta", "out['turboMeta'] = {", "B5", "drives carrying boost and rpm PIDs; hours = duration of those drives"),
 12010: ("ENGINE-ON time", "turboByRpm", "out['turboByRpm'] = tr", "B5", "sample-weighted mean of activePct over rpm bands (boost > 0.1 bar)"),
 12014: ("engine-on time, &gt;0.1 bar", "turboBySpeedCtx", "turboBySpeedCtx", "B5", "blind audit: rpm > 300 and boost non-NaN rows per speed zone, boost > 0.1 bar"),
 12059: ("engine-ON hours", "rpmDistribution", "out['rpmDistribution'] = {", "B1", "code comment"),
 12061: ("all engine-on time", "rpmDistribution", "out['rpmDistribution'] = {", "B1", "code comment"),
 12070: ("Manufacturer cross-check", "rpmDistribution", "out['rpmDistribution'] = {", "B1", "peakPctOfEngineOn on B1"),
 12076: ("declared time base", "engineRuntime", "M512", "B2", "names its base (M512)"),
 12080: ("Per class", "engineRuntime", "M512", "B2", "per-class hour totals on B2; the line says neither threshold nor base (the table above states 'RPM-supported')"),
 12089: ("Engine-on hours", "engineRuntime", "M512", "B3", "column header 'duration-scaled, imputed' (names B3)"),
 12119: ("engine-on time", "engineHoursByType", "engineOnHours", "B3", "blind audit: sum(duration_s x engine_on_pct) from drive_master (duration-scaled imputed); the line itself names it"),
}
rows, errs = [], []
for r in INV["rows"]:
    ln = r["line"]
    m = MAP.get(ln)
    if not m:
        errs.append(f"line {ln}: not in curated map"); continue
    anchor, key, prod, base, note = m
    if anchor.lower() not in J[ln - 1].lower() and anchor.lower() not in r["text"].lower():
        errs.append(f"line {ln}: anchor {anchor!r} not found"); continue
    pl = [i + 1 for i, s in enumerate(P) if prod in s]
    rows.append({"line": ln, "namesBaseOnLine": r["namesTimeBase"], "payloadKey": key, "payloadKeyPresent": key in A, "producerAnchor": prod,
                 "producerLines": pl[:3], "base": base, "note": note})
for ln in MAP:
    if ln not in {r["line"] for r in INV["rows"]}:
        errs.append(f"mapped line {ln} absent from the M520 inventory")
rd = A["rpmDistribution"]; h = rd["pooledHours"]; t = A["engineRuntime"]["totals"]
totals = {"B1_onHours": round(sum(h[1:]), 3), "B1_griddedHours": round(sum(h), 3), "B1_transientBin300_1400_hours": h[1], "B1_threshold": rd["params"]["engineOnThresholdRpm"],
          "B2_supportedOnHours": t["supportedOnHours"], "B2_supportedHours": t["supportedHours"], "B2_elapsedHours": t["elapsedHours"], "B3_scaledImputedHours": t["scaledImputedHours"]}
totals["gapB1minusB2_hours"] = round(totals["B1_onHours"] - totals["B2_supportedOnHours"], 3)
totals["gapPctOfB2"] = round(100 * totals["gapB1minusB2_hours"] / totals["B2_supportedOnHours"], 2)
import numpy as np
m_edges = re.search(r"RPM_HIST_EDGES = \[([^\]]*)\]", chr(10).join(P))
edges = [float(x) for x in m_edges.group(1).replace(chr(10), " ").split(",") if x.strip()]
feasible = 400.0 in edges
b1, b2, b3 = totals["B1_onHours"], totals["B2_supportedOnHours"], totals["B3_scaledImputedHours"]
recon = {"storedEdgesHead": edges[:4], "closure": "np.histogram bins=RPM_HIST_EDGES (left-closed, right-open except the last bin)", "threshold400Feasible": feasible,
         "decomposition": {"pairs": ["B1 vs B2", "B1 vs B3"], "gapB1B2_h": round(b1 - b2, 3), "gapB1B3_h": round(b1 - b3, 3),
           "a_threshold_term": "not separable: 400 is not a stored edge; bound = 300-1400 bin hours %.3f" % h[1],
           "b_denominator_support": {"B1_gridded_h": totals["B1_griddedHours"], "B2_supported_h": totals["B2_supportedHours"], "B2_elapsed_h": totals["B2_elapsedHours"],
                                     "griddedMinusSupported_h": round(totals["B1_griddedHours"] - totals["B2_supportedHours"], 3)},
           "c_residual_integration": "remainder, unexplained (no raw or 1 Hz re-integration in M521)"},
         "result": "reconciliation INFEASIBLE from stored data; difference listed as an unresolved time-base difference; 'closed' is not claimed"}
# hard-coded literals: digits left in a line after removing {...} expressions (flag only, nothing edited)
def _lit(t):
    t2 = re.sub(r"\{[^{}]*\}", "", t)
    return re.findall(r"~?\d+(?:\.\d+)?\s?(?:%|h|hours|rpm)", t2)
for r in rows:
    r["hardcodedLiteralCandidates"] = _lit(J[r["line"] - 1])
# seeded blind sample (seed 42): 8 fixed lines + 3 drawn from the no-base lines + 1 config string
FIXED = [9609, 9611, 12080, 12010, 12014, 10983, 12076, 12119]
pool = sorted(r["line"] for r in rows if not r["namesBaseOnLine"] and r["line"] not in FIXED)
rng = np.random.default_rng(42)
drawn = sorted(int(x) for x in rng.choice(pool, size=3, replace=False))
cfg = ["/oemTechReview/fixedPointOperation/note", "/oemTechReview/engineFloor/note"]
cfg_pick = cfg[int(rng.integers(0, len(cfg)))]
blind = {"seed": 42, "fixedLines": FIXED, "poolSize": len(pool), "drawnLines": drawn, "configPath": cfg_pick,
         "auditorGets": "line text (from xtrail_summary.jsx / summary_config.json) and summary_arrays.json path; no B labels"}
BLIND = {"nItems": 12, "agreeFull": ["L9609", "L9611", "L12008", "L12010", "L12070", "L12076", "L12080", "CFG1"],
         "disagreedOrUnresolved": {"L1462": "mine 1 Hz grid; auditor native-cadence row count (auditor adopted)", "L10983": "same as L1462", "L12014": "mine unresolved; auditor resolved to the boost base (adopted)",
                                   "L12119": "mine B2; the line text itself says duration-scaled imputed, auditor B3 (adopted)"}, "agreementKOverN": "8/12",
         "finding": "CFG1: summary_config.json oemTechReview.engineFloor.note quotes ~4%% of engine-on time for the 300-1400 rpm band; the payload gives %.2f%% (hard-coded literal, flagged, not edited)" % (100 * h[1] / sum(h[1:]))}
out = {"spec": "analyses/M521_spec.md", "errors": errs, "nLines": len(rows), "nBaseNamedOnLine": sum(r["namesBaseOnLine"] for r in rows),
       "byBase": {b: sum(1 for r in rows if r["base"] == b) for b in sorted({r["base"] for r in rows})}, "totals": totals, "reconciliation": recon, "blindSample": blind, "blindResult": BLIND, "rows": rows}
json.dump(out, open(os.path.join(ROOT, "analyses", "M521_mapping.json"), "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False)
print(json.dumps({k: out[k] for k in ("errors", "nLines", "nBaseNamedOnLine", "byBase", "totals")}, indent=1))
sys.exit(1 if errs else 0)
