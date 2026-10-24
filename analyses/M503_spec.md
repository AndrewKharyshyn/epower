# M503 spec (Rev 2): retroactive signal-resolution record of HV current and pack voltage over the whole canonical corpus (audit CD-07)

Status: Rev 2, written 2026-10-24 BEFORE any M503 computation. Rev 1 was reviewed by the research-director (ruling "revise", eight required revisions R1-R8, all folded in below). Origin: independent audit 2026-10-23, finding CD-07: a window of 2026-08-29 to 2026-09-30 in which HV current is logged on a coarse grid (1 A or 0.1 A steps) and pack voltage on a 0.1 V grid is recorded nowhere in the repository (`signal_representation.json` covers only the 117 files ingested after M324, none in that window). This is the "separate read-only task" that `analyses/M324_gatea2_spec.md` reserved for the existing corpus. Descriptive data-quality inventory: no estimator, no eligibility rule, no published figure changes. Basis: raw/ = sha256-verified originals (M366).

## Question
On which drives, and over which dates, are the logged HV battery current and HV battery voltage on a grid coarser than the fine grid that the corpus otherwise uses, and how many of the drives that enter two named analyses are in that window?

## Quantity (frozen)
Per canonical drive, for `[BMS] HV Battery Current (A)` and `[BMS] HV Battery voltage (V)` as logged in the raw text (columns read as strings, so decimals are those of the CSV copy):
- `grid_step` = minimum positive difference between the sorted distinct non-null values rounded to 6 decimals; `n_distinct`; `max_decimals` (largest number of decimal digits in the text); `share_on_1_grid` and `share_on_0p1_grid` (share of non-null values that are multiples of 1 and of 0.1 within 1e-9) (M324 record fields).
- Class (current): `undefined` when `n_nonnull` < 5 or `n_distinct` < 5; `undefined_sparse` when `n_distinct` is 5-19 (too few values for a grid statement); otherwise by `grid_step`: `fine` (<= 0.06 A), `0.1 A` (> 0.06 and <= 0.15), `1 A` (> 0.15 and <= 1.5), `coarser` (> 1.5). A file whose `grid_step` class and grid-share evidence disagree (a coarse class with `share_on_1_grid` (for 1 A) or `share_on_0p1_grid` (for 0.1 A) below 0.99, or a `fine` class with `max_decimals` <= 1 and `share_on_0p1_grid` >= 0.99) is class `mixed`. Voltage: the same rules with classes `fine` (<= 0.06 V), `0.1 V` (> 0.06 and <= 0.15), `coarser`.
- A drive is `coarse` if its current class or its voltage class is `0.1 A`, `1 A`, `0.1 V` or `coarser`. `mixed`, `undefined` and `undefined_sparse` drives are never coarse and are listed separately.
Known limitation (M324 residual, stated): a partly coarse channel can still read `fine`/`mixed`; this inventory makes no claim for such files beyond its class.
Wording: "grid of this CSV copy", logged / app-calculated; never "sensor resolution", "rounding rule", "measured", "affected", "bias", "corrected" or "invalid".

## Population and identity (frozen, R2)
The canonical files of `raw_manifest.json` (role `canonical`, expected 606), read from `raw/`. The mapping between manifest canonical files and `drive_master.csv` rows (by the 14 timestamp digits of the file name, since the master `file` key has two naming forms, audit RC-05) must be 1:1 in both directions; a duplicate 14-digit key, a manifest file without a master row or a master row without a manifest file is a STOP. The count 606 is taken from the manifest role, not from the master alone. Comparison-only, e-4ORCE, auxiliary and derived files are excluded by role. Drives without a current or voltage series get class `undefined` for that channel, never zero-filled.

## Method (frozen)
1. Per-file statistics and classes as above. Time order = start timestamp (`date`, `time_start` of the master).
2. Runs (R3): a run is a maximal sequence of consecutive drives in time order that are all `coarse`; drives of class `undefined` / `undefined_sparse` for both channels neither break nor extend a run (they are skipped and listed). Runs are reported when they have at least 5 drives, per channel (current-coarse, voltage-coarse) and for the `coarse` flag, with first date, last date, span in days and drive count. The window shown on the dashboard is the longest `coarse` run.
3. Summary (script-written): counts per class and channel; number of coarse drives; coarse drives per calendar month; coarse drives inside and outside the longest run; list of `mixed`, `undefined` and `undefined_sparse` drives.
4. Overlap report, counts only (R4): the number of coarse drives among (a) the eligible drives of powerFade S1 (`powerfade_equivalence.s1_rows`, expected `powerFade.nClean`) and (b) the eligible drives of the cell-spread slope (drives with a non-null `cell_spread_loaded_p95_mv` that are not flagged by `ens_outlier_v2`, expected `degradationTrends.cellSpread.clusterRobustOLS.nObs`); if either count differs from the named payload key the difference is reported in the result and the overlap is marked unverified (not tuned). No comparison of estimates between classes is made.
5. Transitions (flag only): between consecutive defined drives whose (current class, voltage class) pair changes, judged against the previous defined drive.
6. Known-answer mismatch against the audit inventory is reported in the result, not tuned (R7).

## No-consumer guard (R6)
The result is not a column of `drive_master.csv`, is not read by `eligibility.py`, `ens_outlier_v2`, `degradation_trends.py`, `compute_drive_summary_v6.py`, `compute_summary_arrays.py` or any estimator; a test greps those consumers for the block name and the tool name. Any use of the classes as a filter or weight is a new analysis with its own spec.

## Decision rules and wording (frozen)
- Dashboard (bound to `S.signalResolution`): "quantities that use HV current in this window were logged on a coarser grid; no effect is estimated" with the window, the counts and the basis; no effect size, no correction. If no drive is coarse, no sentence is shown.
- The block is a dated SNAPSHOT of the corpus at its drive count (no ingestion stage in M503): at a later ingestion it is re-stamped as carried forward with its basis count named; new drives are covered by `signal_representation.json` (M324). A stage that extends the inventory is a follow-up.

## Known answer (audit, not used as a target in the code)
The audit's independent inventory found 199 drives in 2026-08-29..2026-09-30 with HV current at 1 A (185) or 0.1 A (14) steps and pack voltage at 0.1 V, and a fine grid elsewhere. Any difference is explained in the result, not tuned away.

## Outputs
`analyses/M503_result.json` (class counts, runs, month table, overlap report, per-drive table, provenance: master MD5, raw manifest sha256, script and spec sha256). Script `tools/signal_resolution.py`; tests `tests/synthetic/test_signal_resolution.py` (grid steps, classes incl. mixed and sparse, run rules with undefined drives, identity STOP on a duplicate key, no-consumer grep). Payload: additive block `signalResolution` (compact: counts, runs, window, coarse-drive list) + stamp. Dashboard: one sentence in the logger-cadence paragraph; no chart.

## Out of scope
Any correction or re-estimation for the coarse window; cell-voltage grids; changing `signal_representation.json`; the plausibility gate; an ingestion stage.
