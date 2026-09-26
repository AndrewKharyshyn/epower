"""Phase-0 native-equivalence, dimensional, partition, histogram, and honesty tests."""
import sys, csv, json, math
sys.path.insert(0, "/home/claude/work")
import cohort_fixes_p0 as cf

DM="/mnt/project/drive_master.csv"
def _f(x):
    try: return float(x) if x not in (None,"","None") else None
    except: return None

allv, by, unc = cf.load_corpus()
block = cf.cohort_block()
results=[]
def check(name, cond, detail=""):
    results.append((name, bool(cond), detail)); 
    return cond

# 1) FIX #2 dimensional regression: ratio-of-sums, NOT double-normalized
# Pipeline convention (matches meta.grossThroughputKwh/meta.totalKm): numerator over
# drives with throughput, denominator over TOTAL corpus distance. Cohorts MUST match this
# convention for native-equivalence; a matched-population variant is a labelled secondary.
gt=[d["gross_throughput_kwh"] for d in allv if d.get("gross_throughput_kwh") is not None]
dist_all=[d["distance_km"] for d in allv if d.get("distance_km") is not None]
ros = 100.0*sum(gt)/sum(dist_all)
gt_m=[d["gross_throughput_kwh"] for d in allv if d.get("gross_throughput_kwh") and d.get("distance_km")]
dist_m=[d["distance_km"] for d in allv if d.get("gross_throughput_kwh") and d.get("distance_km")]
double = 100.0*sum(100.0*g/x for g,x in zip(gt_m,dist_m))/sum(dist_m)
v = block["energyIntensity"]["all"]["value"]
check("F2 energy intensity == independent ratio-of-sums", abs(v-ros)<1e-9, f"{v:.6f} vs {ros:.6f}")
check("F2 energy intensity != double-normalized", abs(v-double)>1.0, f"correct {v:.2f} vs double {double:.2f}")
check("F2 unit is kWh/100km", block["energyIntensity"]["all"]["unit"]=="kWh/100km")

# 2) native-equivalence: all-cohort intensity == authoritative meta throughput/100km
meta=json.load(open('/mnt/project/summary_arrays.json'))['meta']
tp=meta.get("grossThroughputKwh"); tkm=meta.get("totalKm") or meta.get("totalDistanceKm")
if tp and tkm:
    native=100.0*tp/tkm
    check("NE all-intensity == pipeline meta throughput/100km (<=0.5%)",
          abs(v-native)/native<=0.005, f"cohort {v:.3f} vs meta {native:.3f}")
else:
    check("NE meta anchor present", False, f"meta lacks grossThroughputKwh/totalKm: {tp},{tkm}")

# 3) FIX #3 starts non-null for non-empty supported cohorts
for c in ("warm","shoulder"):
    s=block["startsPer100km"][c]
    check(f"F3 starts non-null [{c}]", s and s.get("value") is not None and s["value"]>0,
          f"{s.get('value') if s else None}")
check("F3 starts carries proxy provenance", "proxy:n_sign_crossings" in block["startsPer100km"]["warm"]["provenance"])

# 4) FIX #4 histogram conservation incl. overflow
edges=list(range(0,55,5))               # 0..50 -> long drives (>50km) must overflow, not vanish
h=cf.histogram([d["distance_km"] for d in allv], edges)
check("F4 histogram conserved (nIn+under+over==nTotal)", h["conserved"], json.dumps({k:h[k] for k in('nIn','underflow','overflow','nTotal')}))
check("F4 overflow captured (long drives not discarded)", h["overflow"]>0, f"overflow={h['overflow']}")
n_nonnull=sum(1 for d in allv if d.get("distance_km") is not None)
check("F4 nTotal == non-null distance count", h["nTotal"]==n_nonnull, f"{h['nTotal']} vs {n_nonnull}")

# 5) partition: all == warm+shoulder+cold+unclassified ; regime single-valued (mutually exclusive)
cc=block["_meta"]["cohortCounts"]
check("P all == warm+shoulder+cold+unclassified",
      cc["all"]==cc["warm"]+cc["shoulder"]+cc["cold"]+cc["unclassified"],
      json.dumps(cc))
# mutual exclusivity: each classified drive appears in exactly one cohort
seen={}
for c in cf.COHORTS:
    for d in by[c]: seen.setdefault(d["file"],[]).append(c)
check("P cohorts mutually exclusive", all(len(v)==1 for v in seen.values()))

# 6) empty-cohort honesty: cold null (not zero), coverage no_observations
check("H cold energyIntensity is null (not 0)", block["energyIntensity"]["cold"] is None)
check("H cold starts is null (not 0)", block["startsPer100km"]["cold"] is None)
check("H cold coverage status no_observations", block["coverage"]["cold"].get("status")=="no_observations")

# ---- report
passed=sum(1 for _,ok,_ in results if ok)
print(f"\n{'='*72}\nPhase-0 cohort tests: {passed}/{len(results)} passed\n{'='*72}")
for name,ok,detail in results:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}"+(f"  — {detail}" if detail else ""))
sys.exit(0 if passed==len(results) else 1)
