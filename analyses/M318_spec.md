# M318 pre-registered spec (rev 2): M119 / M119-v2 recompute on the 489-drive corpus, with the day-key correction

Status: written BEFORE any M318 result exists on the corrected code (2026-10-01; master 489 drives, MD5 bd9d10726bb064d857cf9ff98d2b7338; branch claude/next-milestone at bcfd353). Revision 2 folds in the Director's review of revision 1 (decision "revise", 8 required edits), still before any result.
Wording: hazard probabilities and model metrics are estimated / model-derived, never measured. Not article-eligible: V2 is fitted on today's `raw/`; per the F03 provenance block 335 of 500 archived files (333 of the 489 canonical drive files) fail their recorded hashes (the owner decision of 2026-09-29 quotes 335/457; the numerator is the same, the denominator follows the current manifest). The V2 block is therefore labelled "not M299-reproducible", and nothing from it enters the article until F03 is resolved or Andrii signs off a disclosed dual report. Fresh-vs-published differences are "provenance sensitivity", never "corrections".

## Why this spec exists (history, disclosed)
A first M318 attempt (owner request: recompute M119 and M119-v2 on all 489 drives) ran the unmodified `m119v2_model.py` and was REJECTED by the blind audit (FAIL): `_corpus_tables` keys the day as `fn[:8]`, correct for the 367 `YYYYMMDD_HHMMSS` names but the literal `2026-09-` for the 122 `YYYY-MM-DD_HH-MM-SS` names, merging 20 calendar days into one pseudo-day (85 distinct keys, true 104). The M286 CHANGELOG entry records this defect as fixed in `m119v2_model.py` (`_day_key`, nDays 85 -> 90) and the HEAD block records nDays = 90 on 410 drives, but the repository copy of the module has no such fix (its only commit is the initial import): the HEAD block cannot be reproduced from repo code, so it is an UNVERIFIED comparison baseline. The first-attempt result is discarded (kept in scratch, never committed). The audit also found that the first attempt's event counts (5450/5431) are 0.55-0.59% above an independent count (5420/5399) with the gap unexplained; this spec requires it to be closed.

## Population (stated, not implied)
"Canonical" in this project = `ens_outlier_v2`-clean (475 of 489 master rows are False, 2 True, 12 unset; 100 clean calendar days of 104). M119-v2 has NEVER applied that exclusion (it is an energy-integration flag; V2 reads 1 Hz engine/SoC channels) and fits on every master drive with a usable raw file, as in M147/M264/M286. Primary = all 489 drives (same population as HEAD). Sensitivity S3 = the 475 `ens_outlier_v2`-clean drives (unset treated as not excluded), reporting drives and days excluded per side.

## Part A. M119 (`socHysteresis`)
Recomputed by `_soc_hysteresis_summary` on 489 drives; byte-identical to the stored block in the first attempt (it uses master `date`, not the filename); re-verified in the final run. No splice if identical; otherwise deep-diff listed.

## Part B. M119-v2 (`socHysteresisV2`) corrected refit
Estimand, ladder, folds and CV unit unchanged from M147/M264/M286: cloglog GLM hazard of engine start / stop versus SoC and covariates; five-variable duration-aware headline spec on CORE5 = [soc, speed, tpack, demand, durationS], complete case; calendar day = CV and resampling cluster; grouped contiguous day-block 5-fold CV (trains on all other blocks, including later ones). Frozen event rule (the single canonical detector, written here before the run): engine OFF = RPM <= 100, ON = RPM > 800; a start needs >= 3 s sustained OFF before and >= 2 s sustained ON after; a stop needs >= 3 s sustained OFF; carry-forward ages SoC 5 s, speed 2 s, temperature 15 s, current/voltage 5 s, torque 3 s, coolant 15 s, >= 3 temperature sensors; 1 Hz bin-mean grid.
Changes (two, stated in advance):
1. Day key: `_corpus_tables` passes `_day_key(fn)` (regex `(\d{4})\D?(\d{2})\D?(\d{2})` -> `YYYY-MM-DD`; the key is the file-name start time, which equals the master `date` for 489/489 rows, so a drive that crosses midnight is keyed by its start day like every other day-clustered block). Acceptance: the key equals the master `date` for every drive, and the number of distinct day keys among the INCLUDED drives (all drives with a usable raw frame; and separately after the CORE5 complete-case filter on each side) is reported next to the master's 104.
2. Bootstrap standard: `day_bootstrap` default `b=4000, seed=42` (project standard; legacy b=300, seed=0). Percentile 95% CI, day-clustered.

Runs (decomposing every delta, as the owner decision on ingestion requires a no-new-drive control):
- R0 (reference, not run): HEAD block = 410 drives, nDays 90, b=300 seed 0, raw as of its fit, unverified code.
- R1 (control): corrected code on the 410 HEAD drives (the first 410 master rows), today's raw, b=300 seed 0 AND b=4000 seed 42. R1(b=300) vs R0 isolates provenance drift + code difference; R1(b=4000) vs R1(b=300) isolates the bootstrap standard.
- R2 (primary): corrected code on all 489 drives, b=4000 seed 42. R2 vs R1 isolates new data (+79 drives).
- S1: R2 with legacy b=300 seed 0, same inputs.
- S3: R2 restricted to the ens_outlier_v2-clean drives.
Rolling-origin CV recomputed on the corrected day key for R2; the number of origins per side is reported.

Primary outputs per side (start, stop): logLoss, PR-AUC, Brier, calibration for the four ladder rungs with day-clustered CIs; n events, n at-risk seconds, n drives, n days; rolling-origin pooled metrics and origin counts; median-profile / partial-dependence surfaces; sensitivity block.
Headline ordering: primary metric = pooled out-of-fold logLoss of the five-variable duration-aware spec versus the SoC-only spec, per side; "reversal" = the point-estimate order flips relative to R0; a CI-separated reversal (day-clustered bootstrap difference excludes 0 in the opposite direction) is reported separately.

## Accept / reject
Validity checks (failure = block NOT written to `summary_arrays.json`; HEAD block stays): (a) every drive's day key equals master `date` and n_days among included drives is consistent with the master (<= 104, with every dropped day named); (b) event counts: the detector is deterministic and unaffected by the day key, so the blind auditor must reproduce the per-drive start/stop counts exactly under the frozen rule above, with a per-drive reconciliation of any residual (the first-attempt 0.55-0.59% gap must be explained, not waved through); (c) no same-day train/test leakage (audit); (d) `release_check.py` green, master MD5 unchanged, isolation diff shows only `socHysteresisV2` and its stamp changed, arrays LF line endings.
Scientific outcomes (NOT validity failures; never resolved by keeping the old block by default): an ordering reversal, a headline metric outside its R0 CI, a CI excluding the R0 point estimate, or a TOST/decision flip are reported with the R0->R1->R2 decomposition and escalated to the Director, who decides publication; nothing is tuned to agree. If R1(b=300) differs materially from R0, that is reported as provenance sensitivity (F03) and the Director decides which baseline is used.
Method disagreement between the primary and S1 / S3 intervals is reported as is.

## Provenance and labelling
Fit on today's `raw/` via `raw_only/` (tools/stage_raw.py). Block carries `recomputeMode:'fresh'`, `corpusSizeAtRecompute:489`, `frozenBasis:false`; stamp note names M318, the day-key correction, F03 and "not M299-reproducible". Standing owner rules on ingestion (ML16, pre-existing-row diffs) are n/a: no drive_master change. CHANGELOG M318 states the M286 repo gap (fix recorded but absent from the repo copy) and the restored day key.
Out of scope: the Ukrainian companion article; dashboard figures bound to V2 (no new figure is introduced; a rebuild is only for a payload change).
