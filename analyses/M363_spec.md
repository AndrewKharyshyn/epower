# M363 spec (Rev 1): engine-start proxy label (D-13 remainder) and the stale Engine Cycling section intro

Status: work in progress, Director string review pending. Wording only; every payload number unchanged (leaf string changes only).

## 1. Findings (disk)
- D-13 remainder: the proxy is still titled with "pack-current sign crossings" in the Compare KPI title (`CMP_KPI.StartsPer100km`, xtrail_summary.jsx) and in `comparisonCube.metrics.starts_100km.label` ("Current-direction reversals (pack-current sign crossings)"), rendered in Highway vs City and Compare. M343/M344 already relabelled the rest ("direction reversals", "not engine starts"). The key names (`n_sign_crossings`, `StartsPer100km`) are identifiers and stay (never rename payload keys).
- Stale/unsupported intro text of section E: "How often and how long the engine fires ... A mechanical-wear signal (starter, mounts, bearings) independent of the battery-cycling metrics above. Third view confirms engine-on is primarily a function of speed, not drive type ... The starts lollipop shows the unweighted mean of per-drive RPM-onset rates (short trips dominate; Urban hi = 500); the pooled ratio of sums is below." After M362 the chart shows the median with spread (not a mean, no min-max), the typed "500" is a hard-coded literal, "mechanical-wear signal" is an unsupported inference (no wear measurement exists), and "confirms ... primarily a function of speed" is an unqualified causal reading.
- `engineStartRate.publishedEngineStartsByType.note` (written by `tools/engine_start_rate.py`) also types "Urban hi = 500"; it documents the published per-drive MEAN and stays true; the typed literal is bound to the payload (`pub[urban].hi`) in the tool and the string refreshed by the existing splice only if its numbers are unchanged (known answer), else left and recorded.

## 2. Proposed strings (old -> new)
- Compare KPI title: "Current-direction reversals per 100 km (pack-current sign crossings; ratio of sums, day-cluster CI)" -> "Pack-current direction reversals per 100 km (a proxy count, not engine starts; ratio of sums, day-cluster CI)". Cube label -> "Pack-current direction reversals (proxy count, not engine starts)" (generator `tools/m297_comparison_cube.py` and the payload leaf, deep-diff allow-list = that leaf).
- Section E intro -> "How often and how long the engine runs, derived from the RPM signal (RPM above 300 = ON; runs shorter than 2 s filtered; sensor gaps forward-filled): detector-defined engine-start and engine-on counts, descriptive only (no wear or mechanism inference is drawn from them). The third view shows the engine-on share by speed band. n={S.engineOnDrives} drives with both speed and RPM PIDs / {S.dateRange} (5 early-May files lack the speed PID and are excluded from this chart only). The starts view shows the median of per-drive RPM-onset rates with spread, and the pooled ratio of sums (M343) with its CI where available; rates on drives of about 1 km are denominator-unstable (see the footnote)."
- Language gate RULES M363: "pack-current sign crossings", "Engine-start proxy", "mechanical-wear signal", "Urban hi = 500", "confirms engine-on is primarily a function of speed".

## 3. Controls
`summary_arrays.json` deep-diff: only the cube label leaf; `cohort_arrays.json` unchanged; semantic gate A2 REQUIRED (new intro and titles present in Distribution, Highway vs City and Compare dumps; "sign crossings" prose absent from the dumps); jsdom 0 errors; release_check.

## 4. Questions for the Director
1. Is "proxy count, not engine starts" sufficient, or should the title avoid "starts" altogether? 2. Any other inference in the section E intro or the third view that needs softening? 3. Leave the payload note's typed literal (record as open) or bind it now?
