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

ok("tab dumps present (9 tabs x modes)", len(T) >= 27, f"{len(T)} files")

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
