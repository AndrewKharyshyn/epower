# M312 pre-registered spec: M19 exclusion alignment (ens_outlier -> canonical ens_outlier_v2)

Status: written BEFORE any M312 result exists (2026-09-30, frozen master: 489 drives, MD5 5197ab6dc2a44b99ccb246af03f8f6b0, commit 95ec357, tag M311). Revision 2 incorporates the Director's review of revision 1
(8 required edits; decision "revise"), still before any result. Authority: Director decision 2026-09-30 (accept; standalone milestone on a frozen master between ingestions; new-analysis skill).
Wording: "exclusion alignment" only. Never "correction" or "improvement". Adjusted spreads are model-adjusted / estimated, never measured. Non-authoritative; not article-eligible (F03).

## 1. Question and what changes
The M19 robust (Huber) loaded cell-spread adjustment `cell_spread_loaded_p95_adj_hub_mv` fits loaded p95 cell spread on pack temperature and peak discharge current and keeps the rows `~ens_outlier`
(v5 ensemble: IsolationForest/LOF/MAD votes or hard rules). The canonical exclusion is `ens_outlier_v2` (== `ens_invalid` == `f_domain_2p`: hard physical rules only; M23/M88/M112: the ensemble flagged valid long highway drives on absolute magnitude).
Defects of the current keep set: (a) not canonical; (b) in a pipeline run `ens_outlier` is refit inside `_v5_postprocess_master` (before M19) and only afterwards restored from the frozen ML16 values, so the keep set behind the published column is a
non-published refit that cannot be reproduced from the published master. The dashboard prose for the M19 cross-check already says "ens_outlier_v2-clean"; alignment makes it true.
Change: the Huber fit and the M19 trend report move to a post-pass `M19b` (one function, `m19b_huber_adjust(dm)`, in compute_drive_summary_v6.py) that runs after `ens_outlier_v2` is set and keeps `~ens_outlier_v2` rows of the eligible set.
The column is FULLY REWRITTEN: value for every row in E_new, NaN for every row outside it. Unchanged: estimator (HuberRegressor epsilon 1.35, max_iter 500), regressors (T_pack_mean_avg, peak_I_discharge), T_ref = SPREAD_T_REF = 25 C,
I_ref = median peak_I_discharge of the kept rows. Out of scope: the M15 OLS column `cell_spread_loaded_p95_adj_mv`, degradationTrends.cellSpread (authoritative), ML16, every other column.
Ingestion path requirement: `ens_outlier_v2` is in the ingest_core ML16 list (restored after postprocess). To avoid re-creating defect (b), ingest_core calls `m19b_huber_adjust` AGAIN after the ML16 restore, so the published column is always a function of the published v2.

## 2. Population and eligibility
Eligible set `sc`: non-null `cell_spread_loaded_p95_mv`, `T_pack_mean_avg`, `peak_I_discharge`, `date`. Keep sets: E_old = `~ens_outlier` (frozen published values for B1), E_new = `~ens_outlier_v2`. Report n_drives AND n_days for both keep sets (n_days drives CI width).

## 3. Implementation on the frozen master (additive splice, no reprocessing) and integrity
`tools/m312_huber_alignment.py` imports the SAME `m19b_huber_adjust` as compute_drive_summary_v6 (single source), computes only the new column and trend summary, and splices that one column into drive_master.csv at BYTE level
(csv module / raw text lines; no pandas read-write round trip), atomically (temp file + os.replace). Hard aborts: pre-run drive_master MD5 != 5197ab6dc2a44b99ccb246af03f8f6b0; recomputed `ens_outlier_v2` != frozen v2 (must be 0 diffs); any
per-column raw-text hash of a non-target column differs after the splice; ML16 not 0/16. Emits JSON (n_drives, n_days, coefficients, slope, ci95, MD5 before/after, per-column hashes, script sha). Check: the pipeline path
(`postprocess_master` + post-restore M19b) run on the frozen master reproduces the spliced column byte-exact. Because the master MD5 changes, every stamp is re-issued with `tools/restamp_blocks.py` (disclosure: only
`cell_spread_loaded_p95_adj_hub_mv` changed, proven by the isolation diff). drive_master.csv is written by this pipeline script only. Consumers (grep inventory): `compute_summary_arrays.py` `cellHealthTrend` (`huberSlopeMvPerMo`, `nHuber`) and the dashboard prose "M19 secondary robustness cross-check".

## 4. Measures (descriptive; none is a tuning target)
- M1 keep sets: n rows in `sc` with ens_outlier != ens_outlier_v2 by direction (kept by v2 only = "newly populated"; kept by old only); n_keep_old, n_keep_new; n_days each.
- M2 per-row change |adj_hub_new - adj_hub_B| for rows present in both, for each baseline B in {B1, B2}: median, p95, max (mV); also the same limited to rows whose exclusion status is unchanged (S4); count and share of newly populated rows; count of rows now NaN; change in nHuber.
- M3 Huber coefficients (intercept at T_ref/I_ref, bT, bI) and I_ref, baseline vs new.
- M4 trend, two named slopes: (i) `slope_hub_mv_per_month` (pipeline report; Huber-adjusted point estimate) with the existing M19 bootstrap CI of the OLS-adjusted slope (a known estimator mismatch, disclosed, unchanged); (ii) `huberSlopeMvPerMo` (cellHealthTrend;
  Huber slope of adj_hub on months) which has no CI today: a NEW day-clustered bootstrap CI is pre-registered (resample calendar days, refit the second-stage Huber slope on the resampled rows, seed 42, 4000 draws; failed/non-converged draws counted and dropped).
- M5 coefficient CIs: day-clustered Huber refit per draw (seed 42, 4000 draws, calendar day = cluster) for bT and bI of the baseline fit (I_ref does not enter bT/bI; it is recomputed per draw only for the intercept); report the number of failed or non-converged draws.
Baselines: B1 = Huber refit with E_old using the FROZEN published `ens_outlier` (reproducible, isolates the EXCLUSION effect); B2 = the currently published column (what readers saw). Decompose: refit drift = B2 - B1; exclusion effect = new - B1; total published change = new - B2.

## 5. Decision thresholds (fixed now)
"No material change" requires ALL of the following, evaluated separately against B1 (exclusion effect) and against B2 (change to the published values). If B1 vs B2 alone already fails a criterion, "no material change" cannot be claimed against B2 and the refit drift is reported as its own finding.
- median |delta adj_hub| <= 0.5 mV and p95 <= 2.0 mV. Rationale: loaded p95 spread lives on a ~13-35 mV scale and is published to 0.1 mV, so 0.5 mV = five rounding units (~2% of the scale) and 2.0 mV = ~8%; also reported in units of the Huber residual scale (MAD of baseline residuals).
- newly populated rows <= 10% of `sc` and |delta nHuber| / nHuber <= 10% (the v5 ensemble contamination parameter is 6%, so 6-8% is expected; >10% would indicate exclusion of a structured subpopulation, e.g. long highway drives).
- |delta slope_hub| and |delta huberSlopeMvPerMo| <= 0.25 x half-width of the baseline CI (M4 (i) uses its M19 CI, (ii) the new Huber bootstrap CI); the zero-inclusion of each CI must not flip.
- |delta bT| and |delta bI| <= 0.25 x the half-width of the M5 CI; if more than 1% of bootstrap draws fail the criterion is reported INCONCLUSIVE, not passed.
Multiplicity: none applied; the rule is a conjunction (intersection-union), conservative for claiming no change. If all hold: disclose "exclusion alignment, no material change" and proceed. If any fails: still policy-driven (canonical consistency) but labelled material,
needs an explicit Director decision, and is disclosed with the changed values. Falsification: the claim "alignment is immaterial to the published adj_hub values and the M19 trend" is falsified by any failed criterion.

## 6. Sensitivity analyses
S1 Huber with no exclusion (keep all of `sc`). S2 leave-last-8-days-out refit under E_new (stability). S3 epsilon 1.2 and 1.5 under E_new (reported only; Huber tuning is not a degree of freedom used here). S4 row deltas restricted to rows whose exclusion status is unchanged.

## 7. Isolation / validation chain (step 3 of the skill)
py_compile; JSON round-trip; `node build_html.js`; `node validate_jsdom.js`; `python release_check.py`. Isolation diff on the frozen master: every column except `cell_spread_loaded_p95_adj_hub_mv` byte-identical (raw-text hash per column; ML16 0/16);
in summary_arrays.json only `cellHealthTrend` (+ stamps/corpus-hash fields) may change; seasonal_arrays.json, cohort_arrays.json, fuel_recon_master.csv, raw_temperature_triplets.csv byte-identical except embedded corpus hashes. Known-answer test under `tests/synthetic/`
for `m19b_huber_adjust` (synthetic data with planted outliers; exclusion by v2 keeps them, by E_old drops them; NaN outside the keep set).

## 8. Disclosures
The M19 slope CI bootstraps an OLS-adjusted slope while the point estimate is Huber-adjusted (pre-existing; unchanged). The block is non-authoritative (`authoritative:false`); degradationTrends.cellSpread governs headline claims. CHANGELOG records any deviation from this spec.
