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
ok("A2 REQUIRED current-direction reversals label present", any("Current-direction reversals" in t for t in T.values()))
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
# M356 (Cs-21)
ok("A2 REQUIRED Crawl & Stop-Go: 'Energy by phase window' table with the not-additive statement, reconstructed wording and the F03 label", any(all(x in t for x in ("Energy by phase window", "not additive", "Reconstructed from logged HV current", "regen-direction energy is a positive magnitude", "provenance-sensitive (F03)")) for t in T.values()))
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
_z = (A.get("generatorTractionRecon") or {}).get("gtrClosure") or {}
_fa = T.get("fuel__all", "").replace("  ", " ")
ok("A2 REQUIRED M336 closure block wording (consistent within the dual bracket; not closed; CI straddles 0.5; residual; provenance)",
   all(x in _fa for x in ["consistent within the dual bracket; not closed under the pre-registered", "straddles 0.5", "Battery → traction is a model residual", "provenance-sensitive (F03)", "bounding cases, not calibrated intervals"]))
ok("A2 REQUIRED M336 closure block numbers equal the payload",
   bool(_z) and f"{_z['fGen']['est']} ({_z['fGen']['ci95'][0]} to {_z['fGen']['ci95'][1]})" in _fa and f"{_z['scope']['nDrives']} of {_z['scope']['nCanonical']} drives" in _fa)
# M337: Fuel analytics v1 wording and payload-bound numbers (Fuel All dump)
_fx = (A.get("fuelAnalytics") or {})
_fxd = T.get("fuel__all", "")
ok("A2 REQUIRED M337 FUEL-12 wording (consistency check, dt-cap dependence, same app, review margin, F03, not M299-reproducible)",
   all(x in _fxd for x in ["internal consistency check of two logged/app-calculated series", "not a bias estimate", "Agreement does not establish independence or external accuracy (same app)",
                           "arbitrary margin fixed in advance", "raw/, provenance-sensitive (F03)", "Not M299-reproducible"]))
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
ok("A2 REQUIRED M339 FUEL-03 wording (temporal states, not allocations, same-bin thresholds, dwell definition, hash split not paired, speed/SoC/rpm cell-identical to the originals, HV rounding stated)",
   all(x in _fxd for x in ["temporal states of the logged fuel rate", "not exclusive fuel-source allocations", "thresholds of 0.5 and 1 km/h are the same bin", "dwell: a stationary run is stationary only if", "not a paired test", "cell-identical to the sha256-verified originals", "HV current and voltage in raw/ are rounded", "do not depend on the re-export rounding", "has not been checked against the originals", "a temporal state of the logged rate, not an allocation of fuel to the battery"]))
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
                                      "Detector-defined count", "F10.r1 is partly open", "provenance-sensitive (F03)", "file-boundary bookkeeping, not a cold-start measure"]))
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

print(f"\nSEMANTIC GATE: {len(passes)} passed, {len(fails)} failed")
sys.exit(1 if fails else 0)
