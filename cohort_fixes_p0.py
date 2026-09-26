"""
Phase-0 corrected cohort aggregation core (X-Trail seasonal-cohort integration).

Fixes three confirmed defects from the experimental cohort layer:
  #2 energy-intensity double-normalization  -> ratio-of-sums on the RAW numerator
  #3 broken starts/100km resolution         -> correct events/100km + explicit provenance
  #4 histogram truncation (tail discarded)  -> explicit underflow/overflow + conservation

Reuses the already-correct, unit-tested seasonal_core aggregation helpers.
drive_master.csv is read READ-ONLY. `all` cohort spans the COMPLETE canonical FWD
corpus (incl. thermally-unclassified drives); warm/shoulder/cold span the classified
subset only. Unclassified drives are reported, never silently dropped.
"""
import sys, csv, math
sys.path.insert(0, "/mnt/project")
import seasonal_core as sc

DM = "/mnt/project/drive_master.csv"
SM = "/mnt/project/seasonal_drive_master.csv"
COHORTS = ["warm", "shoulder", "cold"]

def _f(x):
    try: return float(x) if x not in (None, "", "None") else None
    except (TypeError, ValueError): return None

def load_corpus():
    """Return (all_drives[374], by_cohort{warm/shoulder/cold}, unclassified[list])."""
    sm = {r["file"]: r for r in csv.DictReader(open(SM))}
    all_drives, by = [], {c: [] for c in COHORTS}
    unclassified = []
    for r in csv.DictReader(open(DM)):
        fn = r["file"]
        d = {"file": fn, "date": r.get("date"),
             "distance_km": _f(r.get("distance_km")),
             "gross_throughput_kwh": _f(r.get("gross_throughput_kwh")),
             "n_sign_crossings": _f(r.get("n_sign_crossings")),
             "ambient_time_mean_c": _f((sm.get(fn) or {}).get("ambient_time_mean_c"))}
        reg = (sm.get(fn) or {}).get("thermal_regime")
        d["thermal_regime"] = reg
        all_drives.append(d)                 # ALL DATA = complete corpus
        if reg in by:
            by[reg].append(d)
        else:
            unclassified.append(d)           # no ambient classification -> reported, not dropped
    return all_drives, by, unclassified

# ---- FIX #2: energy intensity = ratio-of-sums on the RAW numerator (single normalization)
def energy_intensity(pool):
    """Observed cohort headline: 100 * sum(gross_throughput_kwh) / sum(distance_km).
    Also returns the drive-weighted mean of per-drive intensities, SEPARATELY LABELLED,
    never substituted for the headline."""
    ros = sc.cohort_per_100km(pool, "gross_throughput_kwh")          # ONE normalization
    per_drive = [ (100.0*d["gross_throughput_kwh"]/d["distance_km"])
                  for d in pool
                  if d.get("gross_throughput_kwh") and d.get("distance_km") ]
    dwm = (sum(per_drive)/len(per_drive)) if per_drive else None
    return {"value": ros, "unit": "kWh/100km", "estimator": "ratio_of_sums",
            "driveWeightedMeanOfIntensities": dwm, "n": len(per_drive)}

# ---- FIX #3: starts/100km = correct events/100km, with explicit provenance/eligibility
def starts_per_100km(pool, count_key="n_sign_crossings",
                     provenance="proxy:n_sign_crossings (current-sign; authoritative "
                                "engine-start count is raw-derived engineStartsByType, Phase 2)"):
    elig = [d for d in pool if d.get(count_key) is not None and d.get("distance_km")]
    if not elig:
        return {"value": None, "status": "unavailable",
                "reason": "no eligible drives with a populated start count",
                "provenance": provenance}
    rows = [{"e": d[count_key], "distance_km": d["distance_km"]} for d in elig]
    val = sc.cohort_events_per_100km(rows, "e")
    return {"value": val, "unit": "starts/100km", "estimator": "events_ratio_of_sums",
            "nEligible": len(elig), "nPool": len(pool), "provenance": provenance,
            "status": "computed"}

# ---- FIX #4: histogram with explicit underflow/overflow and conservation guarantee
def histogram(vals, edges):
    counts = [0]*(len(edges)-1)
    under = over = 0
    n_total = 0
    for v in vals:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        n_total += 1
        if v < edges[0]:
            under += 1; continue
        if v >= edges[-1]:
            over += 1; continue
        for i in range(len(edges)-1):
            if edges[i] <= v < edges[i+1]:
                counts[i] += 1; break
    n_in = sum(counts)
    conserved = (n_in + under + over == n_total)
    return {"edges": edges, "counts": counts, "underflow": under, "overflow": over,
            "nIn": n_in, "nTotal": n_total, "conserved": conserved}

def cohort_block():
    allv, by, unc = load_corpus()
    block = {"_meta": {"cohortKey": "thermal_regime",
                       "cohortCounts": {"all": len(allv),
                                        **{c: len(by[c]) for c in COHORTS},
                                        "unclassified": len(unc)}},
             "energyIntensity": {}, "startsPer100km": {}, "coverage": {}}
    pools = {"all": allv, **by}
    for name, pool in pools.items():
        block["coverage"][name] = sc.cohort_coverage(pool) if pool else {"n_drives": 0, "status": "no_observations"}
        if name == "cold" and not pool:
            block["energyIntensity"][name] = None      # explicit unavailable, NEVER zero
            block["startsPer100km"][name] = None
            continue
        block["energyIntensity"][name] = energy_intensity(pool)
        block["startsPer100km"][name] = starts_per_100km(pool)
    block["_meta"]["unclassifiedReported"] = len(unc)
    return block

if __name__ == "__main__":
    import json
    print(json.dumps(cohort_block(), indent=1, default=str)[:2000])
