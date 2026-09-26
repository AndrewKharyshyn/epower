#!/usr/bin/env python3
"""m295_payload.py (M295) — stable drive-class keys + explicit not-observed strata in the categorical
seasonal charts (audit 2026-09-24 P0 'Compare category-join bug'). Idempotent. Corpus-invariant."""
import json, os
W = os.path.dirname(os.path.abspath(__file__)); p = os.path.join(W, "summary_arrays.json")
A = json.load(open(p, encoding="utf-8"))
CANON = {"urban": "Urban", "city": "Urban", "mixed": "Mixed", "mixed_highway": "Mixed Highway", "highway": "Highway"}
def key_of(label): return str(label).strip().lower().replace(" ", "_").replace("-", "_")
n_fixed = 0
for cid in ("CycleByType", "EfficiencyBands", "EngineStartsByType", "RegenByType"):
    ch = A["seasonalCharts"]["charts"].get(cid)
    if not ch: continue
    for coh, v in (ch.get("data") or {}).items():
        if not isinstance(v, list): continue
        for e in v:
            if not isinstance(e, dict) or "label" not in e: continue
            k = key_of(e["label"]); k = "urban" if k == "city" else k
            if k in CANON:
                if e["label"] != CANON[k]: n_fixed += 1
                e["label"] = CANON[k]; e["classKey"] = k
                has_val = any(isinstance(e.get(f), (int, float)) for f in ("avg", "med", "value", "lo", "hi"))
                if not has_val:
                    e["n"] = 0; e["status"] = "not_observed"
                    e["reason"] = e.get("reason") or "no drive of this class was logged in this cohort (null, not zero)"
    ch["classKeyPolicy"] = ("M295: every class entry carries a stable classKey (urban/mixed/mixed_highway/highway) and a "
                            "title-case display label; Compare joins on classKey. Classes without support in a cohort are "
                            "explicit {n:0,status:'not_observed'} entries rendered as hatched 'not observed' cells, never as zero.")
# DriveTypeChart / DriveDurationDist: zero-drive classes are 'not observed', never zero-as-real (M296 refresh)
for cid, ncol, numf in (("DriveTypeChart", "drives", ("km", "hours", "avgKm", "avgMin", "avgSpeedKmh")),
                        ("DriveDurationDist", "n", ("min", "q1", "med", "q3", "max"))):
    ch = A["seasonalCharts"]["charts"].get(cid)
    if not ch: continue
    for coh, v in (ch.get("data") or {}).items():
        if not isinstance(v, list): continue
        for e in v:
            if isinstance(e, dict) and (e.get(ncol) in (0, None)):
                for f in numf: e[f] = None
                e["status"] = "not_observed"; e["classKey"] = e.get("key")
                e["reason"] = "no drive of this class was logged in this cohort (null, not zero)"
    ch["classKeyPolicy"] = "M296: zero-drive classes carry status 'not_observed' with null numerics (never zero-as-real)."
eb = A["seasonalCharts"]["charts"]["EfficiencyBands"]
eb["displayTitle"] = "Gross pack discharge per 100 km by drive class (kWh/100km) — not vehicle energy efficiency"
json.dump(A, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("class labels normalised:", n_fixed)

# ---- nativeEquivalence was frozen at the 410-drive basis (17.10218, n=395); re-derive on the live payload ----
A = json.load(open(p, encoding="utf-8"))
ei = A["seasonalCharts"]["charts"]["EnergyIntensity"]["data"]["all"]
pub = ei["publishedBasisSensitivity"]
anchor = 100.0 * float(A["meta"]["grossThroughputKwh"]) / float(pub["pairedKm"])
A["seasonalCharts"]["_meta"]["nativeEquivalence"] = {
    "metric": "energyIntensity.all",
    "cohort": round(ei["value"], 6), "cohortN": ei["n"], "cohortBasis": "canonical_clean paired-eligible (M295)",
    "publishedBasis": round(pub["value"], 6), "publishedN": pub["n"],
    "metaAnchor": round(anchor, 6), "deltaPctPublishedVsAnchor": round(100 * (pub["value"] - anchor) / anchor, 4),
    "note": ("M295: re-derived on the live 446-drive payload (was frozen at the 410 basis: 17.10218, n=395). metaAnchor = "
             "meta.grossThroughputKwh / the published-basis paired km; the residual is the gross throughput of rows with "
             "distance_km<=0 or missing, which meta includes. The headline cohort value is the canonical-clean basis.")}
json.dump(A, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("nativeEquivalence:", A["seasonalCharts"]["_meta"]["nativeEquivalence"]["cohort"], A["seasonalCharts"]["_meta"]["nativeEquivalence"]["deltaPctPublishedVsAnchor"])

# ---- ThermalFuelPenalty methodology date formatting (source + payload) ----
import re as _re
src_p = os.path.join(W, "compute_summary_arrays.py"); src = open(src_p, encoding="utf-8").read()
old = ("            f'Fuel-accumulator subset ({days[0][:4]}-{days[0][4:6]}-{days[0][6:8]} to '\n"
       "            f'{days[-1][:4]}-{days[-1][4:6]}-{days[-1][6:8]}, {len(days)} days, '\n")
new = ("            # M295: days are ISO keys since the _day_key fix; slicing them as compact YYYYMMDD produced\n"
       "            # '2026--0-8-'. Normalise either form.\n"
       "            f'Fuel-accumulator subset ({_iso_day(days[0])} to {_iso_day(days[-1])}, {len(days)} days, '\n")
if old in src:
    src = src.replace(old, new)
    helper = ("def _iso_day(k):\n    k = str(k)\n    return f'{k[:4]}-{k[4:6]}-{k[6:8]}' if _re_daykey.fullmatch(r'\\d{8}', k) else k\n\n\n")
    anchor = "import re as _re_daykey\n"
    assert src.count(anchor) == 1
    src = src.replace(anchor, anchor + helper)
    open(src_p, "w", encoding="utf-8").write(src)
A = json.load(open(p, encoding="utf-8"))
def _fix_meth(block):
    ds = block.get("dateSpan")
    if isinstance(block.get("methodology"), str) and isinstance(ds, list):
        block["methodology"] = _re.sub(r"Fuel-accumulator subset \([^,]*?, ", f"Fuel-accumulator subset ({ds[0]} to {ds[1]}, ",
                                       block["methodology"], count=1)
_fix_meth(A["thermalFuelPenalty"])
for k, v in A["seasonalCharts"]["charts"]["ThermalFuelPenalty"]["data"].items():
    if isinstance(v, dict):
        _fix_meth(v)
        if "dateSpanNote" in v:
            v["dateSpanNote"] = v["dateSpanNote"].replace("collapsed into one '2026-09-' key", "collapsed into one truncated month-only key")
json.dump(A, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("TFP methodology spans:", A["thermalFuelPenalty"]["methodology"][:70])
