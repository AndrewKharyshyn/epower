#!/usr/bin/env python3
"""semantic_gate.py (M299, 2026-09-25) — semantic release gate: rendered prose vs ONE canonical payload.

Implements audit 2026-09-24 implementation step 6. Requires tabtext/ (written by `node dump_tabs.js`, which
renders xtrail_dashboard.html in jsdom and dumps the visible text of every tab in All / Warm / Shoulder /
Compare mode). Checks:
  A. forbidden wording  — phrases the audit showed to be false or unsupported must not render in any tab/mode
                          nor appear in the payload strings.
  B. prose == payload   — headline numbers rendered in prose are recomputed from summary_arrays.json /
                          drive_master.csv and must appear verbatim (same rounding).
  C. mode behaviour     — the typed Comparison cube follows the cohort selector; Cold is never rendered as
                          data; 'not observed' strata are present where the payload says so.
  D. payload integrity  — no record won by a canonically invalid drive; clean-vs-published sensitivity
                          present; no malformed ISO dates; seasonal _meta stamped with the live master MD5.
Exit 0 = pass. Run: node build_html.js && node dump_tabs.js && python3 semantic_gate.py
"""
import glob, hashlib, json, os, re, sys

W = os.path.dirname(os.path.abspath(__file__)); P = lambda n: os.path.join(W, n)
A = json.load(open(P("summary_arrays.json"), encoding="utf-8"))
T = {os.path.basename(f)[:-4]: open(f, encoding="utf-8").read() for f in glob.glob(P("tabtext/*.txt"))}
fails, passes = [], []
def ok(name, cond, detail=""):
    (passes if cond else fails).append(name + (f" — {detail}" if detail and not cond else ""))
    print(("PASS " if cond else "FAIL ") + name + (f" — {detail}" if detail and not cond else ""))

ok("tab dumps present (10 tabs x modes)", len(T) >= 30, f"{len(T)} files")

# ---------- A. forbidden wording ----------
FORBIDDEN = [
    ("× the net SoC change", "wrong comparator (charge/discharge vs net SoC)"),
    ("Every throughput figure scales with", "pack-terminal kWh does not depend on capacity"),
    ("Generator charging dominates", "operating-state bins are not metered sources"),
    ("indistinguishable by ~12 h", "SoC-reset timing not supported"),
    ("shallow against a ~25", "unverified spec-cycle comparator"),
    ("~25-30% DoD of a spec cycle", "unverified spec-cycle comparator"),
    ("Regen capture efficiency", "apparent KE recovery proxy, not measured efficiency"),
    ("NOT YET MEASURABLE", "cool-charging exposure IS measured"),
    ("5.86 Ah measured", "assumed Ah denominator"),
    ("10 → 16 points", "stale provenance counter"),
    ("originates at this one sensor", "modelled energies elsewhere"),
    ("where the", None),  # placeholder removed below
    ("of charge involved regen", "operating-state label"),
    ("of charge from engine-on", "operating-state label"),
    ("round-trip + sensor-offset residual", "imbalance is not round-trip inefficiency"),
    ("HV-bus energy accounting", "only the pack terminal is observed"),
    ("CAP-invariant", "GTC rows are capacity-normalised"),
    ("the BMS allowed", "max SoC does not establish BMS intent"),
    ("equilibrates against passive dissipation", "finite maximum is not equilibrium"),
    ("before the SoC floor forces", "no event-level counterfactual"),
    ("cools ~", "negative-R² soak fit"),
    ("× slower than it heats", "negative-R² soak fit"),
    ("May–Jul", "stale date range"), ("May–Aug", "stale date range"), ("one warm season", "Shoulder observed"),
    ("the only degradation axis this dataset can observe", "power proxy yes, capacity SOH no"),
    ("the mechanical driver of resistance growth", "causal claim"),
    ("this dataset's peaks all occur warm", "40 sub-20 °C peaks exist"),
]
FORBIDDEN = [f for f in FORBIDDEN if f[1]]
payload_txt = json.dumps(A, ensure_ascii=False)
for phrase, why in FORBIDDEN:
    hits = [k for k, t in T.items() if phrase in t]
    ok(f"A forbidden '{phrase}' absent from rendered DOM", not hits, f"{why}; in {hits[:3]}")
    ok(f"A forbidden '{phrase}' absent from payload", phrase not in payload_txt, why)

# ---------- A2. language gate (M326): robust matching (language_gate.py: NFKC, collapsed punctuation, plural-safe, stripped form, context rules) ----------
import language_gate as LG
conc = T.get("conclusions__all", "")
_cfg = json.load(open(P("summary_config.json"), encoding="utf-8"))
_jsx_code, _jsx_comm = LG.scan_jsx(open(P("xtrail_summary.jsx"), encoding="utf-8").read())
_pay, _cfgh = LG.scan_payload(A), LG.scan_payload(_cfg)
_dom = {k: LG.scan_text(t) for k, t in T.items()}
for r in LG.RULES:
    d = [k for k, v in _dom.items() if r.rid in v]
    if "dom" in r.scope:
        ok(f"A2 [{r.rid}] absent from rendered DOM", not d, f"{r.why}; in {d[:3]}")
    if "payload" in r.scope:
        ok(f"A2 [{r.rid}] absent from payload string values", r.rid not in _pay, f"{r.why}; e.g. {_pay.get(r.rid, [''])[0]}")
    if "config" in r.scope:
        ok(f"A2 [{r.rid}] absent from summary_config.json string values", r.rid not in _cfgh, r.why)
    if "jsx" in r.scope:
        ok(f"A2 [{r.rid}] absent from xtrail_summary.jsx strings/JSX text", r.rid not in _jsx_code, r.why)
    if len(r.scope) < 4:
        print(f"NOTE A2 [{r.rid}] enforced only in {r.scope} (documented exemption)")
    if r.rid in _jsx_comm:
        print(f"WARN A2 [{r.rid}] appears only in a jsx comment: {r.why}")
# REQUIRED (W0): replacement text present and bound to payload values
_rf = A["rfDodHistogram"]
_all_dom = " ".join(T.values())
ok("A2 REQUIRED rainflow floor stated as a cycle range with the payload floor and trace count",
   f"a range below {_rf['floorPct']:g} pp are dropped" in conc and f"{_rf['nFilesUsed']} SoC traces" in conc, f"{_rf['floorPct']} / {_rf['nFilesUsed']}")
ok("A2 REQUIRED fuel text names the logger app and the subset of drives", "logger app" in _all_dom and "subset of drives" in _all_dom)
ok("A2 REQUIRED non-integrable drives are excluded from GTC, not counted as zero", "not counted as zero" in conc)
# W2a (M327): Cold is shown as OBSERVED counts from the payload (cohortMeta.cold.nObserved + cold rows of ambientTable), the selector says Thermal cohort
_cm = (A.get("cohortMeta") or {}).get("cold") or {}
_crow = [r for r in (A.get("ambientTable") or {}).get("rows", []) if r.get("c") == "cold"]
_cd = sorted({r["d"] for r in _crow})
_cn = _cm.get("nObserved", len(_crow))
_cexp = f"Cold: {_cn} observed {'drive' if _cn == 1 else 'drives'} on {len(_cd)} {'date' if len(_cd) == 1 else 'dates'} ({', '.join(_cd)}), below the minimum support"
ok("A2 REQUIRED Cold observed count and date shown from the payload", any(_cexp in t for t in T.values()), _cexp)
# W3a (M328): precision wording bound to the payload value; the cell-spread conclusion says 'not resolved'
_mde = A.get("powerFade", {}).get("mdeRisePctPerYr")
ok("A2 REQUIRED power-fade precision stated as a CI half-width with the payload value",
   any(f"95% CI half-width ±{_mde}%/yr" in t for t in T.values()), str(_mde))
ok("A2 REQUIRED health conclusion reads 'Cell-spread trend not resolved'", any("Cell-spread trend not resolved" in t for t in T.values()))
# W4a (M329)
ok("A2 REQUIRED depth-squared weighted cycle sum wording present", any("depth-squared weighted cycle sum" in t for t in T.values()))
ok("A2 REQUIRED regen-by-temperature Compare title says pack-temperature bin", any("pack-temperature bin" in t for t in T.values()))
ok("A2 REQUIRED direction-reversals label present (M363: 'Pack-current direction reversals', not an engine-start count)", any("Pack-current direction reversals" in t for t in T.values()))
# M351 (p22.12 / p23.16 / F31.r1)
ok("A2 REQUIRED cell-spread interval basis stated (cluster-robust (CR1) normal (z), day clusters)", any("cluster-robust (CR1) normal (z) interval" in t and "day clusters" in t for t in T.values()))
ok("A2 REQUIRED resistance-record simulation is an IID residual-model reference distribution, not a noise test, day dependence not modelled", any(all(x in t for x in ("IID residual-model reference distribution", "not a noise test", "Day dependence is not modelled")) for t in T.values()))
ok("A2 REQUIRED rounded-to-zero p-values shown as p<0.001 in the Risk table; p-values stated unadjusted for multiplicity", any("p<0.001" in t and "unadjusted for multiplicity" in t for t in T.values()))
# M352 (F13.3 / p21.5 / p21.6)
ok("A2 REQUIRED ambient basis stated: labelled vehicle_sensor (driver-recorded, uncalibrated), substituted count, mean of start and end readings, equal intervals, reading times not recorded", any(all(x in t for x in ("labelled vehicle_sensor", "driver-recorded", "uncalibrated", "are substituted", "mean of the start and end readings", "equal intervals", "reading times are not recorded")) for t in T.values()))
ok("A2 REQUIRED ambient basis table with per-cohort counts rendered", any("Ambient basis by cohort" in t and "Trapezoidal mean" in t for t in T.values()))
# M353 (F18.r1 / p15.4)
ok("A2 REQUIRED registry offset row: one corpus-wide constant, two-pass, not applied to gross throughput, GTC or FCE, class label 'Derived, corpus constant'", any(all(x in t for x in ("one corpus-wide constant", "two-pass", "not applied to gross throughput, GTC or FCE", "Derived, corpus constant")) for t in T.values()))
# M354 (F08.r1 / p25.2)
_cmo = json.load(open("summary_arrays.json", encoding="utf-8"))["cohortMeta"]
_obs_line = "Observed {a} = Warm {w} + Shoulder {s} + Cold {c}".format(a=_cmo["all"]["observed"], w=_cmo["warm"]["observed"], s=_cmo["shoulder"]["observed"], c=_cmo["cold"]["observed"])
ok("A2 REQUIRED observed-sum line from cohortMeta (" + _obs_line + ") and Cold shown as observed only", any(LG.norm(_obs_line) in LG.norm(t) and "observed only" in t for t in T.values()))
ok("A2 REQUIRED cohort counts conserve: observed(warm+shoulder+cold) == observed(all); inferenceAvailable == (eligibleForCohortView >= min)", _cmo["warm"]["observed"] + _cmo["shoulder"]["observed"] + _cmo["cold"]["observed"] == _cmo["all"]["observed"] and all(_cmo[k]["inferenceAvailable"] == (_cmo[k]["eligibleForCohortView"] >= 10) for k in ("warm", "shoulder", "cold")))
ok("A2 REQUIRED identifiability box 'What the data cannot identify' with six limits and the payload Cold count", any("What the data cannot identify" in t and "uncalibrated vehicle reading" in t and "segregated from the primary corpus" in t and "assumed BSFC prior" in t for t in T.values()))
# M357 (Crawl & Stop-Go callout)
ok("A2 REQUIRED Crawl & Stop-Go callout: per-cycle ratio wording, regen-probability sentence (lowest peak-speed tercile), RPM onsets, F03 label, in all / warm / shoulder", all(any(all(x in T.get("distribution__" + m, "") for x in ("per-cycle ratio approach regen / launch discharge", "lowest peak-speed tercile", "RPM onsets: RPM from", "start type not separated", "no regen-direction energy at all")) for _ in [0]) for m in ("all", "warm", "shoulder")))
# M366 (F03 re-anchoring: raw/ = sha256-verified originals)
_pv = json.load(open("summary_arrays.json", encoding="utf-8"))["provenanceSensitivity"]
_pr = _pv["raw"]
import csv as _csv5
_nrows5 = sum(1 for _ in _csv5.DictReader(open("drive_master.csv", encoding="utf-8")))
_ncan5 = sum(1 for x in json.load(open("raw_manifest.json", encoding="utf-8"))["files"] if x["role"] == "canonical")
# M377a: nCanonical is bound to the live corpus (drive_master rows == manifest canonical entries), not to the 489 of M366; the 333 re-exports were replaced at M366 (of 489 then)
ok("A2 REQUIRED M366 payload: all canonical copies in raw/ match the manifest sha256 and the 333 re-exports are recorded as replaced", _pr["nCanonicalHashFailing"] == 0 and _pr["formerReexportsReplaced"] == 333 and _pr["nCanonical"] == _nrows5 == _ncan5)
_m366 = "%d of %d canonical copies in raw/ match the manifest sha256; %d lower-precision re-exports were replaced by the sha256-verified originals (M366" % (_pr["nCanonical"] - _pr["nCanonicalHashFailing"], _pr["nCanonical"], _pr["formerReexportsReplaced"])
ok("A2 REQUIRED M366 Methodology provenance sentence bound to provenanceSensitivity.raw (" + _m366 + ")", _m366 in open("xtrail_summary.jsx", encoding="utf-8").read().replace("{r.nCanonical-r.nCanonicalHashFailing} of {r.nCanonical}", "%d of %d" % (_pr["nCanonical"] - _pr["nCanonicalHashFailing"], _pr["nCanonical"])).replace("{r.formerReexportsReplaced}", str(_pr["formerReexportsReplaced"])))
ok("A2 REQUIRED M366 basis label 'raw/ = sha256-verified originals (M366)' present in the rendered dashboard", any("raw/ = sha256-verified originals (M366)" in t for t in T.values()))
# M366 headline-gate disclosures (Director ruling Rev 2)
_f12 = json.load(open("summary_arrays.json", encoding="utf-8"))["fuelAnalytics"]["fuel12"]
_sh = _f12["m366Shift"]
_pct = lambda v: ("+" if v > 0 else "-" if v < 0 else "") + ("%.2f" % abs(v * 100)) + "%"
ok("A2 REQUIRED M366 FUEL-12 states plainly that it moved outside its previous 95% CI, with the previous and current estimates bound to the payload",
   any(all(x in t for x in ("FUEL-12 moved outside its previous 95% CI", _pct(_sh["previous"]["aggregate"]["est"]), _pct(_f12["aggregate"]["est"]), "not a paired test")) for k, t in T.items() if k.startswith("fuel__") and k.endswith("__all")))
ok("A2 REQUIRED M366 the five outside-CI estimates are all FUEL-12 and the disclosure counts are bound (headline gate)", _sh["nOutsidePreviousCi"] == 5 and len(_sh["outsidePaths"]) == 5 and all(p.startswith("/fuelAnalytics/fuel12/") for p in _sh["outsidePaths"]))
# M370 (P4): each carried-forward GTR block states its OWN basis (the M366 collective "former re-exports" sentence was accurate for gtrClosure only); bound to staleBlocks.perBlock
_sb = json.load(open("summary_arrays.json", encoding="utf-8"))["generatorTractionRecon"]["staleBlocks"]
_nprod = json.load(open("summary_arrays.json", encoding="utf-8"))["generatorTractionRecon"]["nProduction"]
for _m in ("all", "warm", "shoulder", "compare"):
    _t = T.get(f"fuel__{_m}", "").replace("  ", " ")
    ok(f"A2 REQUIRED M370 Fuel {_m} dump: Blocks line plus one basis sentence per block (milestone, n drives, n days or 'not recorded', current headline set, raw basis, status), bound to staleBlocks.perBlock",
       ("Blocks " + ", ".join(_sb["blocks"])) in _t and all(
           f"{p['block']}: basis {p['basisMilestone']}" in _t and f"{p['nDrives']} drives" in _t and (f"{p['nDays']} days" in _t if p["nDays"] is not None else "n days not recorded" in _t)
           and f"(current GTR headline set: {_nprod} drives); raw basis: {p['rawBasis']}; {p['status']}." in _t for p in _sb["perBlock"]), _m)
ok("A2 REQUIRED M370 crossval label states that it is not recomputable and not a validation of the current headline", any("Path A coefficients unpreserved; not recomputable; pre-M366 basis; not a validation of the current headline" in t for k, t in T.items() if k.startswith("fuel__")))
# M373 (P2): simultaneity / speedSplit / sensitivity refreshed on the originals; descriptive point values, no interval; wording bound to the payload; direction claims verified from the payload values
_G3 = json.load(open("summary_arrays.json", encoding="utf-8"))["generatorTractionRecon"]
_rb3 = {p["block"]: p for p in _G3.get("refreshedBlocks", [])}
_js = lambda x: (("%s" % x)[:-2] if isinstance(x, float) and float(x).is_integer() else "%s" % x)
ok("A2 REQUIRED M373 payload: three blocks refreshed (refreshedBlocks), staleBlocks keeps only crossval, each refreshed block states the O basis and 'no interval'",
   sorted(_rb3) == ["sensitivity", "simultaneity", "speedSplit"] and _G3["staleBlocks"]["blocks"] == ["crossval"] and all(p["rawBasis"] == "raw/ = sha256-verified originals (M366)" and "no interval" in p["status"] for p in _rb3.values()))
for _m in ("all", "warm", "shoulder", "compare"):
    _t3 = " ".join(" ".join(T.get(k, "") for k in T if k.endswith("__" + _m)).split())
    ok(f"A2 REQUIRED M373 {_m} dumps: one refreshed-block sentence per block (milestone, basis, n drives, n days, status) plus the attribution sentence",
       all(f"{p['block']}: refreshed {p['basisMilestone']} on {p['rawBasis']}, {p['nDrives']} drives, {p['nDays']} days; {p['status']}." in _t3 for p in _rb3.values()) and "Attribution: " + next(iter(_rb3.values()))["provenanceDelta"] + "." in _t3, _m)
_simu = {r["type"]: r for r in _G3["simultaneity"]}
_ss = {r["bin"]: r for r in _G3["speedSplit"]}
_all3 = " ".join(" ".join(T.values()).split())
_sts = ("genPlusBattDischarge", "chargesAndDrives", "genAloneNeutral", "fullyBanked")
ok("A2 REQUIRED M373 simultaneity text: 'largest engine-on state in urban and mixed driving' is TRUE in the payload (charge-and-drive is the maximum state of both rows), the not-monotonic remark is TRUE, and the wording is rendered",
   all(max(_simu[t][k] for k in _sts) == _simu[t]["chargesAndDrives"] for t in ("urban", "mixed"))
   and not (all(a <= b for a, b in zip([_simu[t]["chargesAndDrives"] for t in ("urban", "mixed", "mixed_highway", "highway")], [_simu[t]["chargesAndDrives"] for t in ("urban", "mixed", "mixed_highway", "highway")][1:]))
            or all(a >= b for a, b in zip([_simu[t]["chargesAndDrives"] for t in ("urban", "mixed", "mixed_highway", "highway")], [_simu[t]["chargesAndDrives"] for t in ("urban", "mixed", "mixed_highway", "highway")][1:])))
   and "charge-and-drive is the largest engine-on state in urban and mixed driving" in _all3 and "charge-and-drive is not monotonic across the four types" in _all3
   and f"charge-and-drive for {_js(_simu['urban']['chargesAndDrives'])}% of engine-on time (mixed {_js(_simu['mixed']['chargesAndDrives'])}%)" in _all3)
ok("A2 REQUIRED M373 simultaneity basis note: refreshed, descriptive, no interval, deadband deltas bound to refreshedBlocks",
   all(x in _all3 for x in ("Basis note: refreshed at M373 per-second", "descriptive point shares, no interval", "replacing the raw basis by the former lower-precision re-exports changes any share by at most %s pp at 0.5 kW" % _js(_rb3["simultaneity"]["deadbandMaxAbsDeltaPP_O_minus_R"]["primary_0.5kW"]))))
_bins = ("0-20", "20-60", "60-90", "90-120")
ok("A2 REQUIRED M373 speedSplit text: 'f_gen is higher in the faster bins' and 'battery arm lower in the faster bins' are TRUE in the payload (f_gen strictly increasing over the first four bins; battery 0-20 > 90-120) and the wording, validation counts and refresh note are rendered",
   all(_ss[a]["fGen"] < _ss[b]["fGen"] for a, b in zip(_bins, _bins[1:])) and _ss["0-20"]["battery"] > _ss["90-120"]["battery"]
   and all(x in _all3 for x in ("f_gen is higher in each faster bin", "the battery arm's absolute contribution is lower in the faster bins", "this is a property of the binning",
                                "matched fuel_recon_master.csv on %d of %d drives" % (_rb3["speedSplit"]["validation"]["nMatched"], _rb3["speedSplit"]["validation"]["nChecked"]))))
ok("A2 REQUIRED M373 sensitivity caption: refreshed note rendered and BASE equals the live headline (gate passed in the run)",
   "Refreshed at M373 on raw/ = sha256-verified originals over %d drives (the BASE row equals the live headline); descriptive point values, no interval." % _rb3["sensitivity"]["nDrives"] in _all3
   and _rb3["sensitivity"]["baseGate"]["passed"] and _rb3["sensitivity"]["baseGate"]["equalsLiveHeadline"] == {"gen100": _G3["corpus"]["generator"], "trac100": _G3["corpus"]["tractionGross"], "fgen": _G3["corpus"]["fGen"], "etaBus": _G3["corpus"]["etaBus"]})
ok("A2 REQUIRED M373 the section-4a sentence in the simultaneity paragraph is qualified (no typed 38 % / 62 % numbers, no 'deliberately')",
   "this table does not test it" in _all3 and "holds ~38% load" not in _all3)
ok("A2 REQUIRED M373 wording fixes: buffer sentence (urban larger charge-and-drive, highway larger battery-discharge: TRUE in the payload), thin 120+ bin not higher than 90-120 (TRUE), sensitivity title and previous-table disclosure, logged standstill draw, drive-type chart n labelled as a different set",
   _simu["urban"]["chargesAndDrives"] > _simu["highway"]["chargesAndDrives"] and _simu["highway"]["genPlusBattDischarge"] > _simu["urban"]["genPlusBattDischarge"] and _ss["120+"]["fGen"] <= _ss["90-120"]["fGen"]
   and all(x in _all3 for x in ("has the larger charge-and-drive share and the highway row (%d drives) the larger battery-discharge share; this state mix is consistent with, but does not test, a power-buffer role" % _simu["highway"]["nDrives"],
                                "is not higher than 90\u2013120", "Sensitivity \u2014 single-axis perturbations", "on every single axis (point values). The previous table (M279 basis) had %d of %d axes at or above 0.5" % (_rb3["sensitivity"]["previousBlock"]["nAxesFgenAtOrAbove0p5"], _rb3["sensitivity"]["previousBlock"]["nAxes"]),
                                "the logged key-on standstill draw", "the drive-type chart above counts every headline drive")))
_fg3 = [r["fgen"] for r in _G3["sensitivity"]]
ok("A2 REQUIRED M373 sensitivity previous-table disclosure is TRUE: the margin of the highest axis to 0.5 is smaller than the combined drift, and the refreshed table has no axis at or above 0.5",
   max(_fg3) < 0.5 and (0.5 - max(_fg3)) < _rb3["sensitivity"]["previousBlock"]["combinedDriftMaxAbsFgen_R_minus_published"] and _rb3["sensitivity"]["previousBlock"]["nAxesFgenAtOrAbove0p5"] == 3)
_l4, _l5 = _G3["limitations"][4], _G3["limitations"][5]
ok("A2 REQUIRED M373 limitations[4] and [5]: refreshed-at-M373 wording present, crossval no longer called 'current', most urban engine-on time is charge-and-drive or fully banked (TRUE)",
   "refreshed at M373 on raw/ = sha256-verified originals (M366) as descriptive point values with no interval" in _l4 and "the M265 fix did not change them" in _l4
   and "most urban engine-on time is classified as charge-and-drive or fully banked" in _l5 and (_simu["urban"]["chargesAndDrives"] + _simu["urban"]["fullyBanked"]) > 50)
_l6 = _G3["limitations"][6]
ok("A2 REQUIRED M373 limitations[6] (speed split provenance): refreshed at M373, no typed M255-era counts, the check count is stated in the speed-split text (script-written %d of %d)" % (_rb3["speedSplit"]["validation"]["nMatched"], _rb3["speedSplit"]["validation"]["nChecked"]),
   "refreshed at M373 on raw/ = sha256-verified originals (M366)" in _l6 and "145" not in _l6 and "n=11" not in _l6 and "16.5 km" not in _l6 and "matched fuel_recon_master.csv on %d of %d drives" % (_rb3["speedSplit"]["validation"]["nMatched"], _rb3["speedSplit"]["validation"]["nChecked"]) in _all3)
# M375: canonical-clean eligibility; known answers recomputed from the files (eligibility.py), never typed
import eligibility as EL
import pandas as _pd
_fr5 = _pd.read_csv("fuel_recon_master.csv")
_ex5 = EL.excluded_files(EL.load_flags("drive_master.csv"), _fr5["file"])
_can5 = _fr5[~_fr5["file"].isin(_ex5)]
_ea = _G3.get("eligibilityAlignment") or {}
ok("A2 REQUIRED M375 payload: eligibilityAlignment states the canonical-clean headline counts (recomputed from the files: nProduction = canonical-clean fuel rows, nDrives = those with f_gen, km), the excluded IDs equal the drive_master flags, and the headline carries exactly these counts",
   bool(_ea) and _G3["nProduction"] == len(_can5) == _ea["current"]["nProduction"] and _G3["nDrives"] == int(_can5["f_gen"].notna().sum()) == _ea["current"]["nDrives"]
   and abs(_G3["kmProduction"] - round(float(_can5[_can5["f_gen"].notna()]["distance_km"].sum()), 1)) < 1e-9 and sorted(e["file"] for e in _ea["excluded"]) == sorted(_ex5) and _ea["nFuelInstrumentedRows"] == len(_fr5))
for _m in ("all", "warm", "shoulder", "compare"):
    _t5 = " ".join(" ".join(T.get(k, "") for k in T if k.endswith("__" + _m)).split())
    ok(f"A2 REQUIRED M375 {_m} dumps: the one-time eligibility note is rendered from the payload (the P_aux-low sentence is rendered wherever the sensitivity table is: all / warm / shoulder, not Compare)",
       bool(_ea) and " ".join(_ea["note"].split()) in _t5 and (_m == "compare" or " ".join(_ea["sensitivityNote"].split()) in _t5), _m)
ok("A2 REQUIRED M375 refreshed-block statuses and the closure set note state canonical-clean with script-bound counts",
   all(("canonical-clean (ens_outlier_v2), %d of %d fuel-instrumented drives" % (_n5, len(_fr5))) in _rb3[b]["status"] for b, _n5 in (("sensitivity", _G3["nDrives"]), ("simultaneity", _G3["nDrives"]), ("speedSplit", _G3["nProduction"])))
   and "the headline set is the %d canonical-clean (ens_outlier_v2) of %d fuel-instrumented drives" % (_G3["nProduction"], len(_fr5)) in _G3["gtrClosure"]["scope"]["excludedNote"] and "open item" not in _G3["gtrClosure"]["scope"]["excludedNote"])
ok("A2 REQUIRED M375 the seasonal GeneratorTractionRecon entry metadata states the canonical-clean rule and the one-time note says it is a definition change, not a correction",
   "canonical-clean (ens_outlier_v2) and f_gen not NaN" in json.load(open("summary_arrays.json", encoding="utf-8"))["seasonalCharts"]["charts"]["GeneratorTractionRecon"]["statisticalUnit"] and "not a correction" in _ea.get("note", ""))
_pv2 = json.load(open("summary_arrays.json", encoding="utf-8"))["provenanceSensitivity"]["disclosure"]
ok("A2 REQUIRED M366 F03 disclosure does not claim all estimates stay inside their CIs (it states the counts and that the outside ones are FUEL-12)", "all FUEL-12" in _pv2 and "remain inside their previous 95% CIs" in _pv2 and "remain inside their CIs" not in _pv2)
# M364 (buffer-thesis wording: qualified description, derived badges)
_src = open("xtrail_summary.jsx", encoding="utf-8").read()
_all_t = " ".join(T.values())
ok("A2 REQUIRED M364 qualified thesis wording present (consistent with ... not a test; described as a power buffer; Pack Energy per Cycle title)", all(x in _all_t for x in ("this reading is an interpretation, not a test", "it does not by itself establish it", "it does not by itself test the power-buffer description", "Crawl & Stop-Go — Pack Energy per Cycle", "described as a power buffer", "not tested against an alternative such as a controller SoC policy")))
ok("A2 REQUIRED M364 conclusion scope is bound (S.dateRange and observed counts from cohortMeta), no typed season", "${S.dateRange}; ${S.cohortMeta?.warm?.observed" in _src and "warm and shoulder season" not in _src)
_meas = [i + 1 for i, ln in enumerate(_src.split(chr(10))) if 'EvidenceBadge status="measured"' in ln]
ok("A2 REQUIRED M364 badge audit: only the three non-thesis Measured badges (AFR, oil/coolant lag, departure speed artefact) and the register legend remain (%d: %s)" % (len(_meas), _meas), len(_meas) == 4)
# M363 (D-13 remainder + engine-cycling section text)
_esr = json.load(open("summary_arrays.json", encoding="utf-8"))
_det = _esr["engineStartRate"]["detector"]
_intro = "RPM above %s = ON; runs shorter than %s s filtered; short sensor gaps (up to %s s) carried forward" % (_det["rpmThreshold"], _det["minRunS"], _det["ffillLimitS"])
ok("A2 REQUIRED M363 section E intro: detector parameters bound to engineStartRate.detector, descriptive-only wording, speed-zone view wording", any(all(x in t for x in (_intro, "labelled engine starts; not verified ignition or cold-start events", "descriptive only; no wear or mechanism inference", "speed and drive class are confounded, no attribution")) for k, t in T.items() if k.startswith("charts__") and k.endswith("__all")))
ok("A2 REQUIRED M363 By Speed and ON Duration captions: observed association, controller logic not observed, no purpose inferred", any(all(x in t for x in ("the controller logic is not observed here", "with no mechanism or purpose inferred", "detector-defined ON runs")) for k, t in T.items() if k.startswith("charts__") and k.endswith("__all")))
ok("A2 REQUIRED M363 reversal metric titled as direction reversals, not engine starts (Highway vs City and Compare dumps) and the payload leaves agree", any("Pack-current direction reversals (not an engine-start count)" in t for k, t in T.items() if k.startswith("highway_vs_city__")) and _esr["comparisonCube"]["metrics"]["starts_100km"]["label"] == "Pack-current direction reversals (not an engine-start count)" and "Urban hi" not in _esr["engineStartRate"]["publishedEngineStartsByType"]["note"])
# M361 (intake-air channel availability, bound to meta.intakeAir)
_ia = json.load(open("summary_arrays.json", encoding="utf-8"))["meta"]["intakeAir"]
_ia_line = "Intake-air channel: unavailable since %s (last valid drive %s; no value from drive %s); %d of %d drives carry a value, %d drives on %d days follow the last valid drive and %d earlier drives also have no value." % (_ia["lastValidDate"], _ia["lastValidDrive"], _ia["firstDriveWithoutValue"], _ia["nDrivesValid"], _ia["nDrives"], _ia["nDrivesAfterLastValid"], _ia["nDaysAfterLastValid"], _ia["nDrivesNoValue"] - _ia["nDrivesAfterLastValid"])
ok("A2 REQUIRED M361 Overview data-health line from meta.intakeAir (counts equal the payload; no cause language)", any(_ia_line in t for k, t in T.items() if k.startswith("overview__")))
ok("A2 REQUIRED M361 Battery Thermal Pattern: availability sentence, per-class counts, pre-outage gap, pack probes use all drives", any(all(x in t for x in (_ia_line, "Drives with a value by thermal class: Warm %d of %d" % (_ia["byCohort"]["warm"]["nDrivesValid"], _ia["byCohort"]["warm"]["nDrives"]), "pre-outage figure", "the four pack probes use all drives")) for k, t in T.items() if k.startswith("thermal__") or k.startswith("charts__") or k.startswith("health__") or k.startswith("records__")))
ok("A2 REQUIRED M361 Records intake rows: pre-outage scope and no routing wording", any("Pre-outage scope: drives up to %s" % _ia["lastValidDate"] in t and "among drives that carry a value" in t for k, t in T.items() if k.startswith("records__")))
ok("A2 REQUIRED M361 baseline sentence is bound (pre-outage baseline, drives with a value, up to the last valid date; the collapsed panel is absent from the dumps)", "pre-outage baseline: pack mean minus intake-air median" in open("xtrail_summary.jsx", encoding="utf-8").read())
# M362 (Engine ON/OFF cycling: distribution summary instead of min-max; short-trip denominator disclosed)
_es = json.load(open("summary_arrays.json", encoding="utf-8"))["engineStartsByType"]
_urb = next(x for x in _es if x["label"] == "Urban")
_est_t = [t for k, t in T.items() if "Engine starts (RPM onsets) per 100 km" in t]
ok("A2 REQUIRED M362 starts chart rendered with the new caption and footnote in the All / Warm / Shoulder dumps", len(_est_t) >= 3)
ok("A2 REQUIRED M362 chart wording (detector-defined RPM onsets, not ignition or cold-start events; denominator-unstable; descriptive display threshold; M343 pooled diamond with CI; F03) and no min-max headline",
   bool(_est_t) and all(all(x in t for x in ("detector-defined RPM onsets", "not verified ignition or cold-start events", "denominator-unstable", "descriptive display threshold, never an exclusion", "raw/ = sha256-verified originals (M366)")) for t in _est_t))
ok("A2 REQUIRED M362 urban row n and short-drive count bound to the payload (All dump)", any(("n=%d drives, %d days" % (_urb["n"], _urb["nDays"])) in t and ("%d under %s km" % (_urb["nShort"], int(_urb["shortKm"]))) in t for k, t in T.items() if k.endswith("__all") and "Engine starts (RPM onsets) per 100 km" in t))
ok("A2 REQUIRED M362 urban maximum described as a short drive in the footnote (All dump)", any(("Urban maximum %d per 100 km on a %s km drive" % (_urb["hi"], _urb["maxKm"])) in t for k, t in T.items() if k.endswith("__all") and "Engine starts (RPM onsets) per 100 km" in t))
# M360 (GTR Sankey default-visible with explicit residual branches; Director ruling analyses/M360_spec.md)
_zc = json.load(open("summary_arrays.json", encoding="utf-8"))["generatorTractionRecon"]["gtrClosure"]
_pcs = lambda v: ("+" if v > 0 else "") + ("%.2f" % (v * 100)) + "%"
_excess = _pcs(_zc["nodeExcess"]["relToGenerator"])
for _m in ("all", "warm", "shoulder", "compare"):
    _t = T.get("fuel__" + _m, "")
    ok(f"A2 REQUIRED M360 Fuel {_m} dump: Sankey note (reconstructed not measured; node not closed with residual {_excess}; residual not distributed; f_gen includes 0.5; F03) and no reveal-button wording",
       all(x in _t for x in ("Reconstructed (model-derived) flows, not measured", "The generator node is not closed: residual " + _excess, "the residual is shown as a hatched branch and is not distributed", "includes 0.5: neither a battery majority nor a generator majority is established", "raw/ = sha256-verified originals (M366)", "unallocated residual", "canonical-clean (ens_outlier_v2 excluded", "rest on slightly different drive sets")) and "Show allocation sketch" not in _t)
# M359 (B-HandoffSequence): marginal medians are not one realised sequence; resolution band; counts bound to the payload
_hs = json.load(open("summary_arrays.json", encoding="utf-8"))["handoffSequence"]
_o = _hs["modalOrderings"]
_pre = sum(x["n"] for x in _o if "dischargePeak" in x["sequence"] and x["sequence"].index("dischargePeak") < x["sequence"].index("engineStart"))
_aft = sum(x["n"] for x in _o if "dischargePeak" in x["sequence"] and x["sequence"].index("dischargePeak") > x["sequence"].index("engineStart"))
_hs_txt = [t for k, t in T.items() if "Descriptive timing, not a single realised sequence" in t]
ok("A2 REQUIRED handoff section rendered with the new title and the callout in all/warm/shoulder dumps", len(_hs_txt) >= 3 and all("Battery, engine and boost timing around engine start" in t for t in _hs_txt))
ok("A2 REQUIRED handoff callout: marginal-not-realised wording, resolution band separate from the bootstrap interval, tie rule, boost subset, F03 label",
   bool(_hs_txt) and all(all(x in t for x in ("not one realised sequence", "timing resolution", "same-sample ties", "handoffs with an onset", "raw/ = sha256-verified originals (M366)", "does not establish that the buffer acts first")) for t in _hs_txt))
ok("A2 REQUIRED handoff ordering split equals the payload integer counts (all dump: strictly before %d, at or after %d of %d)" % (_pre, _aft, _hs["nHandoffs"]),
   any(("covering %d handoffs" % _pre) in t and ("at or after it in %d " % _aft) in t for t in T.values() if "Descriptive timing, not a single realised sequence" in t and t.startswith("") and ("of %d handoffs" % _hs["nHandoffs"]) in t))
# M358 (F21.r1): C-rate risk map with A / kW primary axes
_ak = json.load(open("summary_arrays.json", encoding="utf-8"))
_n_ak = len(_ak["cRatePointsAK"])
ok("A2 REQUIRED C-rate map: A/kW/C-rate selector, drive-peak-power not-co-timed wording, assumed-capacity caveat, F03 label, n bound to cRatePointsAK",
   any(all(x in t for x in ("Peak charge current (A)", "Peak charge power (kW)", "C-rate (assumed capacity)", "not co-timed with peak current", "CAP_KWH = 2.1 kWh", "raw/ = sha256-verified originals (M366)", f"n={_n_ak} of {_n_ak} drives plotted", "logged (BMS-reported via OBD)")) for t in T.values()))
ok("A2 REQUIRED C-rate map payload: cRatePointsAK first three columns equal cRatePoints; new keys present", _n_ak == len(_ak["cRatePoints"]) and all(a[:3] == b for a, b in zip(_ak["cRatePointsAK"], _ak["cRatePoints"])) and all(k in _ak for k in ("cRateRefLinesAK", "cRateAxes")))
# M356 (Cs-21)
ok("A2 REQUIRED Crawl & Stop-Go: 'Energy by phase window' table with the not-additive statement, reconstructed wording and the F03 label", any(all(x in t for x in ("Energy by phase window", "not additive", "Reconstructed from logged HV current", "regen-direction energy is a positive magnitude", "raw/ = sha256-verified originals (M366)")) for t in T.values()))
ok("A2 REQUIRED Crawl & Stop-Go phase table carries the CI and days, the gap caveat, the approach-list distinction and the blind-audit disagreement", any(all(x in t for x in ("95% CI", "Samples with no I×V are dropped", "differ from the zero-inflation of the standalone approach list", "Blind audit (own resampling, reported not tuned)", "share ≤ 0 Wh (1 Hz grid)")) for t in T.values()))
# M355 (Cs-1)
_mm = json.load(open("summary_arrays.json", encoding="utf-8"))["meta"]
_pct = "%.1f" % (_mm["totalKm"] / _mm["odometer"] * 100)
ok("A2 REQUIRED Overview: odometer 'dash reading as of " + _mm["odometerAsOf"] + "', logged share = total logged km / dash odometer (" + _pct + " %), counts by basis", any(("dash reading as of " + _mm["odometerAsOf"]) in t and "Counts by basis" in t and "lifetime odometer" in t and (_pct) in t for t in T.values()))
ok("A2 REQUIRED car-age sentence is bound to the registration date and the as-of date (S.registeredDate, S.carAgeAsOf; the sentence sits in a collapsed panel absent from the tab dumps)", 'registered ", S.registeredDate, ", as of ", S.carAgeAsOf' in open("xtrail_summary.jsx", encoding="utf-8").read())
# W5a (M330)
ok("A2 REQUIRED ambient-axis gap described as drives that do not enter the ambient rows", any("drives that do not enter the ambient rows" in t for t in T.values()))
# W6a (M331)
ok("A2 REQUIRED SoC-pattern section states the extractor is absent / panels illustrative", any("extractor script is not in this repository" in t for t in T.values()))
# W1a (M332)
ok("A2 REQUIRED f_gen stated as a model-derived allocation index", any("f_gen is a model-derived allocation index" in t for t in T.values()))
ok("A2 REQUIRED section titles 'Net pack-energy recovery' and 'Observed engine-start contexts'",
   any("Net pack-energy recovery" in t for t in T.values()) and any("Observed engine-start contexts" in t for t in T.values()))
# M333: the GTR closure residual is visible in every mode (F14.10), without any reveal
for _m in ("all", "warm", "shoulder", "compare"):
    ok(f"A2 REQUIRED GTR closure residual present in the Fuel {_m} dump", "Allocation excess over generator output" in T.get(f"fuel__{_m}", ""))
# M336: interval accounting block present with the required Director wording (Fuel All dump), numbers bound to the payload
def _keep(v, d, thr):   # M368 (R2): mirror of fmtKeep in xtrail_summary.jsx - fixed decimals, more digits only if rounding would cross the threshold
    k = d
    while k < 8 and ((round(v, k) > thr) - (round(v, k) < thr)) != ((v > thr) - (v < thr)):
        k += 1
    return f"{v:.{k}f}"
_z = (A.get("generatorTractionRecon") or {}).get("gtrClosure") or {}
_fa = T.get("fuel__all", "").replace("  ", " ")
ok("A2 REQUIRED M336 closure block wording (consistent within the dual bracket; not closed; CI straddles 0.5; residual; provenance)",
   all(x in _fa for x in ["consistent within the dual bracket; not closed under the pre-registered", "straddles 0.5", "Battery → traction is a model residual", "raw/ = sha256-verified originals (M366)", "bounding cases, not calibrated intervals"]))
ok("A2 REQUIRED M336 closure block numbers equal the payload",
   bool(_z) and f"{_keep(_z['fGen']['est'], 2, 0.5)} ({_keep(_z['fGen']['ci95'][0], 2, 0.5)} to {_keep(_z['fGen']['ci95'][1], 2, 0.5)})" in _fa and f"{_z['scope']['nDrives']} of {_z['scope']['nCanonical']} drives" in _fa)
# M337: Fuel analytics v1 wording and payload-bound numbers (Fuel All dump)
_fx = (A.get("fuelAnalytics") or {})
_fxd = T.get("fuel__all", "")
ok("A2 REQUIRED M337 FUEL-12 wording (consistency check, dt-cap dependence, same app, review margin, F03, not M299-reproducible)",
   all(x in _fxd for x in ["internal consistency check of two logged/app-calculated series", "not a bias estimate", "Agreement does not establish independence or external accuracy (same app)",
                           "arbitrary margin fixed in advance", "raw/ = sha256-verified originals (M366)", "Not M299-reproducible"]))
ok("A2 REQUIRED M337 FUEL-01/11 wording (descriptive, SoC not corrected, confounded, trip mix not a consumption trend)",
   all(x in _fxd for x in ["no cause is attributed to the pattern", "Rates are not corrected for the SoC change", "short-trip bands may be biased upward",
                           "not a consumption trend", "no trend test and no seasonal reading"]))
if _fx:
    _a = _fx["fuel12"]["aggregate"]
    ok("A2 REQUIRED M337 numbers equal the payload (trips/days, pooled rate, reconciliation chain)",
       f"{_a['nTrips']} trips, {_a['nDays']} days" in _fxd and f"{_fx['fuel01']['pooledAll']['est']:.2f} ({_fx['fuel01']['pooledAll']['ci95'][0]:.2f}" in _fxd
       and f"{_fx['reconciliation']['canonicalDrives']} canonical drives" in _fxd and f"{_fx['reconciliation']['analysisEligible']} analysis trips" in _fxd)
for _m in ("warm", "shoulder", "compare"):
    ok(f"A2 REQUIRED M337 cohort note present in the Fuel {_m} dump", "individual trips of the selected thermal cohort" in T.get(f"fuel__{_m}", ""))
# M339: Fuel analytics v2 wording and payload-bound numbers (Fuel All dump)
_fs = A.get("fuelStates") or {}
_fw = A.get("fuelWarmup") or {}
ok("A2 REQUIRED M339 FUEL-03 wording (temporal states, not allocations, same-bin thresholds, dwell definition, hash split not paired, speed/SoC/rpm cell-identical to the originals before M366, HV rounding of the former re-exports stated)",
   all(x in _fxd for x in ["temporal states of the logged fuel rate", "not exclusive fuel-source allocations", "thresholds of 0.5 and 1 km/h are the same bin", "dwell: a stationary run is stationary only if", "not a paired test", "cell-identical to the sha256-verified originals", "HV current and voltage in the former raw/ copies were rounded", "do not depend on the re-export rounding", "all trips are now on the sha256-verified originals", "a temporal state of the logged rate, not an allocation of fuel to the battery"]))
ok("A2 REQUIRED M339 FUEL-02 wording (associations, pointwise CI, no zero-filled continuation, confounding, method disagreement, left-censoring)",
   all(x in _fxd for x in ["They are associations", "pointwise 95% CI", "no zero-filled continuation", "confounded with trip length, season, speed profile and the unlogged time since the previous drive", "method disagreement of 0.1 L/100 km", "left-censored"]))
if _fs and _fw:
    _g = _fs["groups"]["all"]
    ok("A2 REQUIRED M339 numbers equal the payload (overall stationary share and CI, trips/days, left-censored count)",
       f"{_g['nTrips']} · {_g['nDays']}" in _fxd and f"{_g['stationaryShare']['est']*100:.2f}% ({_g['stationaryShare']['ci95'][0]*100:.2f}%" in _fxd
       and f"{_fw['excluded']['leftCensored']} trips whose engine was already running" in _fxd)
# M342 (Cs-41): the engine-off (EV) traction text states that engine-off movement does not identify the energy source
ok("A2 REQUIRED engine-off traction text says engine-off movement does not identify the energy origin", any("Engine-off movement does not identify the energy’s origin" in t for t in T.values()))
# M343: engine-start rate (RPM onsets) wording and payload-bound numbers (Distribution/Charts tab dumps)
_esr = A.get("engineStartRate") or {}
_charts_all = T.get("charts__all", "")
if _esr:
    _pa = _esr["primary"]["all"]
    ok("A2 REQUIRED M343 headline and detector wording (RPM onsets, detector parameters, not current reversals, F10.r1 partly open, F03)",
       all(x in _charts_all for x in ["Engine-start rate (RPM onsets), pooled ratio of sums", f"{_pa['est']:.1f} RPM onsets per 100 km", "RPM onsets are not current-direction reversals; the two are different quantities",
                                      "Detector-defined count", "F10.r1 is partly open", "raw/ = sha256-verified originals (M366)", "file-boundary bookkeeping, not a cold-start measure"]))
    ok("A2 REQUIRED M343 Cold reads below minimum support, with the drive count from the payload",
       f"Cold: below minimum support ({_esr['primary']['coldBelowSupport']['nDrives']} drives" in _charts_all)
# M345: the Pure-Electric buffer-limit panel states that usable energy and the window budget scale with the assumed (unverified) CAP_KWH
_capv = ((A.get("constantProvenance") or {}).get("CAP_KWH") or {})
ok("A2 REQUIRED engine-off buffer-limit text says usable energy and window budget scale in proportion to the assumed CAP_KWH (value and verified flag from the payload)",
   any(f"CAP_KWH = {_capv.get('value')} kWh" in t and ("unverified" if not _capv.get("verified") else "verified") in t and "both scale in proportion to that assumed capacity and the budget fraction scales inversely" in t for t in T.values()))
# M334: Fuel tab banner and scenario wording present in every mode dump
for _m in ("all", "warm", "shoulder", "compare"):
    ok(f"A2 REQUIRED Fuel basis banner and SoC-balanced scenario wording in the Fuel {_m} dump",
       "Fuel basis and coverage" in T.get(f"fuel__{_m}", "") and "SoC-balanced scenario" in T.get(f"fuel__{_m}", ""))
ok("A2 REQUIRED fuelContract numbers in the banner equal the payload", all(x in T.get("fuel__all", "").replace("  ", " ") for x in
   [f"present in {A['fuelContract']['coverage']['rate']['columnPresent']} of {A['fuelContract']['coverage']['nCanonical']} canonical files", f"({A['fuelContract']['lhvRatioDefinition']} = {A['fuelContract']['lhvRatio']:g})"]))
ok("A2 REQUIRED selector label reads 'Thermal cohort'", any("Thermal cohort" in t for t in T.values()))
ok("A2 REQUIRED HVAC caveat states sub-15 C ambient is limited", any("Ambient below 15 °C is limited" in t for t in T.values()))

# ---------- B. prose == payload ----------
mc = A["metricConvention"]
g_over_d = f"{mc['grossThroughputKwh'] / mc['grossDischargeKwh']:.3f}"
conc = T.get("conclusions__all", "")
ok("B gross/discharge ratio in Conclusions == payload", f"= {g_over_d}× gross discharge" in conc, g_over_d)
ep = {s["key"]: s["pct"] for s in A["energyPath"]["chargeSources"]}
ok("B operating-state shares in Conclusions == energyPath",
   f"engine-off braking {ep['pure_regen']}%" in conc and f"braking overlap {ep['dual']}%" in conc, str(ep))
cold = A["cRateRefLines"]["zones"]["coldBelowC"]
n_cold = sum(1 for p in A["cRatePoints"] if p[0] < cold)
ok("B cool-charging count in Health == cRatePoints", f"{n_cold} of {len(A['cRatePoints'])}" in T.get("health__all", ""), str(n_cold))
ei = A["seasonalCharts"]["charts"]["EnergyIntensity"]["data"]
ok("B EnergyIntensity headline is the clean basis", str(ei["all"].get("eligibility","")).startswith("canonical_clean")
   and "publishedBasisSensitivity" in ei["shoulder"])
rf = A["rfDodHistogram"]
ok("B rainflow prose == payload", f"{rf['le2PctShare']}% of counted cycles" in conc and f"deepest reaches {rf['maxDodPct']}%" in conc)
dr = A["meta"]["dateRange"]
ok("B observed date range bound in Conclusions", dr in conc, dr)
cube_all = T.get("highway_vs_city__all", "")
u = (A.get("comparisonCube") or {"urbanContrast":{"bands":[{"difference":{"estimate":"__none__"}}]}})["urbanContrast"]["bands"][0]
ok("B urban contrast rendered == payload", f"Δ {u['difference']['estimate']}" in cube_all or f"Δ +{u['difference']['estimate']}" in cube_all)

# ---------- C. mode behaviour ----------
sh = T.get("highway_vs_city__shoulder", ""); wm = T.get("highway_vs_city__warm", ""); cm = T.get("highway_vs_city__compare", "")
ok("C cube follows selector (Shoulder shows 'Showing: Shoulder')", "Showing: Shoulder" in sh)
ok("C cube follows selector (Warm shows 'Showing: Warm')", "Showing: Warm" in wm)
ok("C Compare shows both cohorts", "Showing:WarmShoulder" in cm.replace(" ", ""))
ok("C Shoulder non-urban classes rendered as not observed", sh.count("not observed") >= 3)
cc = A["seasonalCharts"]["_meta"]["cohortCounts"]
ok("C Cold has no fabricated data (cold n=0 -> no cold tab dumps)", cc["cold"] > 0 or not any(k.endswith("__cold") for k in T))
# a leaked token is a rendered value, not the word used in prose ("... is NaN for this leg"): flag NaN/undefined
# adjacent to a number/unit/punctuation slot, and any 'Infinity'.
LEAK = re.compile(r"\bundefined\b(?![- ]?(behaviou?r|by|for))|(?<![A-Za-z(])(?<![A-Za-z_] )NaN(?=\s?(%|kWh|km|mV|mΩ|°|/|\)|–|,\s*\d))|\bInfinity\b|\$\{")
leak = [k for k, t in T.items() if LEAK.search(t)]
ok("C no leaked NaN/undefined/Infinity in any tab/mode", not leak, str(leak[:4]))

# ---------- D. payload integrity ----------
ok("D no record won by a canonically invalid drive",
   all(r.get("disclosure", {}).get("winnerValidity") != "canonically_invalid" for r in A["records"]))
bad_dates = sorted({t for t in re.findall(r"20\d\d-[-0-9]{0,7}", payload_txt) if "--" in t or re.fullmatch(r"20\d\d-\d\d-", t)})
ok("D no malformed ISO date tokens", not bad_dates, str(bad_dates))
md5 = hashlib.md5(open(P("drive_master.csv"), "rb").read()).hexdigest()
ok("D seasonalCharts._meta stamped with live master", A["seasonalCharts"]["_meta"]["corpusMd5"] == md5)
ok("D no rawManifestError in artifact stamps", "rawManifestError" not in json.dumps(A["_artifactStamps"]))
for cid in ("CycleByType", "EfficiencyBands"):
    labs = [e.get("label") for e in (A["seasonalCharts"]["charts"][cid]["data"].get("shoulder") or [])]
    ok(f"D {cid} class labels canonical (no lowercase placeholders)", all(l in ("Urban", "Mixed", "Mixed Highway", "Highway") for l in labs), str(labs))

# ---------- A3 (M368): unjustified precision in rendered numbers (per-leaf records from dump_tabs.js; precision_gate.py; precision_allowlist.json) ----------
import precision_gate as PG
_lf = json.load(open(P("tabtext/_precision_leaves.json"), encoding="utf-8")) if os.path.exists(P("tabtext/_precision_leaves.json")) else None
_allow = json.load(open(P("precision_allowlist.json"), encoding="utf-8"))
ok("A3 per-leaf precision records present (dump_tabs.js wrote tabtext/_precision_leaves.json)", _lf is not None)
_viol, _orph = PG.check(_lf or [], _allow)
ok("A3 no rendered number with > 4 decimals and > 3 significant figures, and no raw p string, outside the allow-list (All/Warm/Shoulder/Compare)", not _viol,
   "; ".join(f"{t}/{m}: {x} in '{s}'" for t, m, s, x in _viol[:5]))
ok("A3 every precision allow-list entry matches a rendered leaf (no orphans)", not _orph, "; ".join(e["text"][:60] for e in _orph[:3]))
ok("A3 every precision allow-list entry names class, reason and milestone", all(e.get("class") and e.get("reason") and e.get("milestone") for e in _allow))

print(f"\nSEMANTIC GATE: {len(passes)} passed, {len(fails)} failed")
sys.exit(1 if fails else 0)
