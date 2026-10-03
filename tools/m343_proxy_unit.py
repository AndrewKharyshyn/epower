#!/usr/bin/env python3
"""M343 (spec rev 2 follow-up): exact-string leaf edit of seasonalCharts.charts.StartsPer100km: the unit becomes 'reversals/100 km' and the provenance texts stop calling the
n_sign_crossings proxy a start count (it counts pack-current direction reversals). Idempotent; asserts old/new text; touches no other leaf. The writer (cohort_fixes_p0.py) is edited to match.
Usage: python tools/m343_proxy_unit.py [--dry-run]"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ARR = os.path.join(ROOT, "summary_arrays.json")
A = json.load(open(ARR, encoding="utf-8"))
c = A["seasonalCharts"]["charts"]["StartsPer100km"]
changed = []
def swap(d, k, old, new, label):
    if d.get(k) == old:
        d[k] = new; changed.append(label)
    else:
        assert d.get(k) == new, (label, d.get(k))
OLD_P = "proxy:n_sign_crossings (current-sign; authoritative engine-start count is raw-derived engineStartsByType, Phase 2)"
NEW_P = "proxy:n_sign_crossings (pack-current direction reversals, not engine starts; the RPM-onset engine-start rate is S.engineStartRate)"
for coh in ("all", "warm", "shoulder"):
    d = c["data"][coh]
    swap(d, "unit", "starts/100km", "reversals/100 km", f"data.{coh}.unit")
    swap(d, "provenance", OLD_P, NEW_P, f"data.{coh}.provenance")
swap(c, "statisticalUnit", "events_ratio_of_sums (paired-eligible): 100*sum(starts)/sum(km) over drives with n_sign_crossings present and km>0",
     "events_ratio_of_sums (paired-eligible): 100*sum(current-direction reversals)/sum(km) over drives with n_sign_crossings present and km>0", "statisticalUnit")
swap(c, "provenance", "proxy:n_sign_crossings (authoritative debounced count is raw-derived engineStartsByType, Phase 2)",
     "proxy:n_sign_crossings (pack-current direction reversals, not engine starts; the RPM-onset engine-start rate is S.engineStartRate)", "provenance")
swap(c, "supersededBy", "EngineStartsByType (native per-type engine-start distribution, now cohort-wired in EngineCyclingChart)",
     "EngineStartRate (pooled RPM-onset engine-start rate, M343) and EngineStartsByType (unweighted mean of per-drive RPM-onset rates)", "supersededBy")
swap(c, "provenanceNote", "Retained as a coarse scalar; the authoritative cohort engine-start signal is the native EngineStartsByType chart. n_sign_crossings proxy not promoted.",
     "Retained as a coarse scalar of pack-current direction reversals; it is a different quantity from engine starts (RPM onsets, S.engineStartRate) and is not compared with them. The proxy is not promoted.", "provenanceNote")
if "--dry-run" not in sys.argv and changed:
    with open(ARR, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A, f, ensure_ascii=False, indent=1)
print(json.dumps({"changed": changed, "n": len(changed)}))
