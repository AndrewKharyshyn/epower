import json
b = {
 "claim": "M444 STUDY block (cohort all): demand ladder, holdout, strict-only and fast-polled sensitivities",
 "reproduced": {"n_drives": 565, "n_days": 113, "n_kept_intervals": 115695},
 "items": {
  "1_decelCuts": {"agree": True, "mine": [0.46487, 0.72855], "maxAbsDiff": 0.0001, "note": "population = strict-drop, start>=10 km/h, NO temp/SOC requirement; adding temp+SOC validity gives 0.4647/0.7299 (would fail 1e-3 on the 2nd cut)"},
  "2_ladder": {"agree": True, "L1": {"nStrata": 81, "available": False, "coverage": 0.6461}, "L2": {"nStrata": 27, "available": True, "coverage": 0.8736},
               "L3": {"nStrata": 27, "available": True, "coverage": 0.8095}, "firstAvailable": "L2 (partial)", "socOnlyCoverage": 0.999,
               "maxBarDiff_pp": 0.01, "maxCiDiff_pp": 0.01, "note": "SOC-only 4 bars and L2 3 bars incl. day intervals match; L1 coverage is of the 2-group set after drops (10-20, 40-50 dropped)"},
  "3_holdout": {"agree": True, "days": [29, 28, 28, 28], "groups_bands_exact": True, "maxCovDiff": 0.0, "maxBarDiff_pp": 0.005,
                "pairs": "7 adjacent, 5 same sign (also reproduced; per block 2/2/0/1 of 2/2/1/2)"},
  "4_sensitivities": {"agree": True, "strictDropOnly_maxBarDiff_pp": 0.003, "strictDropOnly_maxCiDiff_pp": 0.003, "strict_obsCommon_maxDiff_pp": 0.003,
                      "fastPolled_maxBarDiff_pp": 0.003, "fastPolled_maxCiDiff_pp": 0.005, "availability": "both 7 bands, cov 0.9986; fast drops nothing (40-50 unsupported as candidate)"}
 },
 "agrees": True, "abs_diff": 0.01,
 "ambiguities_resolved": [
  "cut-point population excludes temp/SOC validity (matches claim only this way)",
  "fast-polled bootstrap resamples the 34 days WITH data in the subset (not all 113); all-113 variant moves the 10-20 lower limit 53.35 -> 53.07, i.e. 0.28 pp, so the interval depends on this unstated convention",
  "master ev_rpm_dt_med_s is NaN for 1 drive: treated as not fast",
  "L3 weights: below-40 KE is ~0.1% of start>=10 KE so normalising over 27 strata or all KE is indistinguishable"],
 "method_concerns": ["fast-polled 10-20 bar has 1 failed draw of 4000 (within 2.5%)", "fast-polled day set / strict-only support convention not stated in spec Rev 2.2 sec 7; add it",
                     "block holdout w and S* include the block (stability check only, as stated)", "my T_k in blocks 1-2 initially holds 10-20 and drops it via the coverage rule; result identical"],
 "language_concerns": ["none beyond spec: keep 'stability check', 'cadence-mixed', 'unadjusted for multiplicity'"],
 "verdict": "accept",
 "audit_files": ["analyses/M444_audit/common2.py", "analyses/M444_audit/lib2.py", "analyses/M444_audit/cuts.py", "analyses/M444_audit/demand.py", "analyses/M444_audit/holdout.py",
                 "analyses/M444_audit/sens.py", "analyses/M444_audit/out_demand.json", "analyses/M444_audit/out_holdout.json", "analyses/M444_audit/out_sens.json", "analyses/M444_audit2.json"],
 "independence": "did not read tools/, tests/, M444_result.json; reused my own M441_audit extractor cache (cache_C) and aggregate.py; author code not read at all"
}
s = json.dumps(b, ensure_ascii=False, indent=1)
open('analyses/M444_audit2.json', 'w', encoding='utf-8').write(s)
print(len(s.encode()))
