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
