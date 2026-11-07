# M603 spec (Rev 1 after Director review; Rev 0 pre-registered before any result): steady-load cell-spread drift (independent audit, section 05 and the pack-health row of the roadmap)

Status: Rev 1, 2026-11-07, written before any code or result; Rev 1 applies the Director's nine required changes (section 0, which supersedes any conflicting clause below). Owner request: Andrii, chat 2026-11-07 ("continue" after "go as you suggest").
Source: `xtrail_epower_independent_audit.pdf` (sections 05 and 06, roadmap row "Pack health monitoring": "Freeze a supported steady-load comparison,
publish within-regime and matched-context drift"). Audit figures (steady-load slope +0.33 mV/month, 95% interval -0.43 to +1.01; matched contexts
11 of 12) are known-answer targets for a sanity check, never gates and never typed into the repo.

## 0. Rev 1 (Director REVISE, frozen; supersedes conflicting clauses below)
1. Slew definition. The pair timestamp is the midpoint of the min-cell and max-cell timestamps. "Either side" = the last native current sample at or before
   that time and the first one after it (duplicate timestamps dropped); slew = |dI| / dt of that bracket; undefined if either sample is missing or dt > 2 s.
   Because a 2 s gap allows a longer baseline in the slow regime, (a) the qualifying share of loaded pairs is reported per cadence regime and per
   calendar month, and (b) a fixed-window slew (max |dI| over t +/- 1 s <= 3 A) is a sensitivity.
2. E5 current bands: signed bands of 20 A inside 30-100 A for each sign, edges [30,50), [50,70), [70,90), [90,100] and the mirror for negative current.
   The context statistic is the p95 of a drive's qualifying pairs that fall INSIDE the context, with its own floor of 10 pairs per drive-context
   (a drive contributes to every context in which it reaches the floor). Common-context rule as in section 2 (>= 5 drives on >= 3 days each side).
3. Same-model comparison. Loaded S_d (the pipeline selection |I| > 50 A) is computed by the same tool with the same estimators. New E2b = the released
   model (y ~ months + T_pack_mean + peak I, day-clustered CR2, t(G-1)) on steady S_d, and the same model on loaded S_d, so steady versus loaded
   differ ONLY in selection. E1 (Theil-Sen, no covariates) stays as the unadjusted robust estimate and is compared with a Theil-Sen of loaded S_d.
   Optional sensitivities: add SoC (`rf_socmean_wtd_pct`) and a speed or highway-share covariate to E2b.
4. Decision statistic. The paired difference D = slope(steady) - slope(loaded), same drives (those with both S_d defined), same estimator (E2b),
   day-clustered pairs bootstrap of D (seed 42, 4000 draws). Reference pinned now: released `degradationTrends.cellSpread.clusterRobustOLS` slope
   0.7396 mV/month, 95% interval [0.4128, 1.0665], 600 drives, 122 days, on `drive_master.csv` MD5 1574a8156a36c6ea4ea1dfdaafc7cc72 (632 rows).
   The released numbers are the reference; the tool's own loaded slope on the paired drive set is the comparator for D.
5. Outcome grades (replace the old falsification clause): report the interval half-width of D and of the steady slope, and the minimum detectable
   effect at 80 % power from the half-width. Grade, in order: UNINFORMATIVE if the half-width of the steady slope exceeds |loaded slope| (nothing is
   said about drift); otherwise CONSISTENT if the interval of D includes 0 and the steady slope interval overlaps the loaded interval; ATTENUATED if
   D < 0 with an interval excluding 0 but the steady slope interval still excludes 0; ARTEFACT-SUPPORTED only if D < 0 with an interval excluding 0
   and the steady slope interval includes 0. Never "refuted" or "confirmed". An UNINFORMATIVE steady interval is not worded "not established".
6. Floors. A stratum (E4 cadence regime or date split; E5 context) is reported only with >= 20 drives on >= 8 days (E4) or the E5 common-context
   rule; below that the cell reads "not reported (support)". Overall support floor: >= 40 drives on >= 15 days (unchanged).
7. p95 versus n. A seeded fixed-n sensitivity: S_d recomputed on a random subsample of exactly 20 qualifying pairs per drive (seed 42).
8. PID-set change. The decision grade requires the same grade with and without drives from 2026-11-03 onwards; otherwise the outcome is UNDECIDED.
9. Blind-audit tolerances: point estimates within 0.02 mV/month; interval ends within 0.05 mV/month; counts (n drives, days, common contexts, positives) exact.
Optional sensitivity added: pairing-lag cap |t_min - t_max| <= 0.2 s (the mechanism under test). E4 and E5 are labelled "conditional on a post hoc split
date (2026-10-01, M573)". Language: "low-slew selection", "paired by nearest timestamp", "raw/ = sha256-verified originals (M366)"; never "pairing-free",
"true slope", "refuted", "confirmed" or "no degradation". Known risk named: the steady selection correlates with highway driving and season (composition
shift can create or mask a slope), and the seasonal window is short (about 5.7 months), so a wide interval and a false-negative are expected.

## 1. Question
The released loaded cell-spread slope (`degradationTrends.cellSpread`, loaded p95, |I| > 50 A, adjusted for pack temperature and peak current) and the
M573/M577 step analyses all use the "loaded" selection (|I| > 50 A), which mixes steady and rapidly changing current. Rapid current change raises
the paired spread (the min and max cell voltages are never exported at the same instant: median lag tens of ms). Does the cell-spread drift
survive when the sample is restricted to steady current, where pairing lag matters least? This is a measurement-design robustness check of the
released slope. It does not replace the released slope and it makes no capacity or state-of-health claim.

## 2. Estimands (new payload block `steadyLoadSpread`; no existing key is renamed or changed)
Sample selection per drive, on the pipeline's own paired frame (min/max cell voltage nearest-paired within `SPREAD_TOL`, current as-of aligned with
`V_ALIGN_TOL`): a pair qualifies when 30 A <= |I| <= 100 A and the local current slew |dI/dt| <= 3 A/s. Slew is the absolute difference of the two
nearest native current samples on either side of the pair divided by their time gap; a pair with a neighbour gap above 2 s has undefined slew and
does not qualify. Per drive S_d = the 95th percentile of spread (mV) over qualifying pairs, defined only when the drive has >= 20 qualifying pairs.
- E1 (primary): Theil-Sen slope (median of pairwise slopes) of the calendar-day median of S_d against calendar months, in mV/month. Day = cluster.
  Interval: day-clustered percentile bootstrap (seed 42, 4000 draws), the project convention. Unit: mV/month; report n drives, n days.
- E2: the same slope by ordinary least squares on the day medians, day-clustered CR2 interval t(G-1) (the M573/M577 machinery), for method
  disagreement against E1.
- E3 (secondary, calendar-week resampling as in the audit): E1 with calendar weeks as the resampling cluster, reported beside E1, not instead.
- E4 (within-regime drift): E1 computed separately inside the fast-cadence and slow-cadence regimes (`loggerCadence` rule) and before/after the
  2026-10-01 step date used in M573. Intervals only; no pooled contrast across regimes (they are confounded with season).
- E5 (matched contexts): contexts are 5 degC bins of the first pack-temperature sensor T1 x 10-point SoC bins x signed current bands of 20 A x
  cadence stratum. A context is common when it holds >= 5 qualifying drives on >= 3 days both before and from 2026-10-01. For each common context
  the difference (later minus earlier) of the median S_d; report the number of common contexts with a positive difference out of the common
  contexts, the median difference and a day-clustered bootstrap interval of that median. Contexts and days overlap; the count is descriptive.
- E6 (reconciliation estimand): the tool's loaded (|I| > 50 A) p95 recomputed from the raw files must equal the master's
  `cell_spread_loaded_p95_mv` (see section 4).

## 3. Population
Canonical-clean drives (`ens_outlier_v2` excluded) with S_d defined (>= 20 qualifying pairs). Report the count of canonical-clean drives lost to
the 20-pair floor, per cadence regime. Drives from 2026-11-03 onwards (PID-set change, M577) are included in E1-E3 and excluded in a sensitivity.

## 4. Data path (no hand edit of the master)
`tools/steady_load_spread.py` (new) rebuilds the paired frame from `raw/` with the pipeline's own helpers (as `tools/highway_share.py` does) and writes
a sidecar `steady_load_spread.csv` (file, date, n_pairs_loaded, p95_loaded_mv, n_pairs_steady, p95_steady_mv, raw_sha256, method_version).
`drive_master.csv` is NOT written. Reconciliation gate (zero tolerance after `round(., 1)`): the sidecar `p95_loaded_mv` and `n_pairs_loaded` equal the
master's `cell_spread_loaded_p95_mv` and `n_loaded_spread_samples` for every drive that has them; any mismatch fails the tool. The tool joins the
ingestion stages. All payload numbers are script-written from the sidecar.

## 5. Sensitivities (not gates; report and do not tune)
Current band 20-100 A and 40-100 A; slew limit 2 A/s and 5 A/s; floor 10 and 40 pairs; interpolated (bracketed) min/max pairing instead of nearest;
per-drive median instead of p95; E1 without the post-2026-11-03 drives; leave-one-calendar-week-out range of E1.

## 6. Known-answer tests (`tests/synthetic/test_steady_load_spread.py`, written before the tool)
1. Fixture: spread series with a known per-sample level; current ramp samples (slew > 3 A/s) are excluded; edges 30 and 100 A are included, 29.9 and 100.1 A
   excluded; a neighbour gap above 2 s makes the pair non-qualifying.
2. 19 qualifying pairs -> S_d undefined; 20 -> defined (floor inclusive).
3. Theil-Sen on exactly linear day medians recovers the slope; a single outlier day does not move it beyond the median breakdown.
4. Day-clustered bootstrap: constant data -> degenerate interval at the estimate; interval covers the truth in a synthetic coverage run near 95%.
5. Matched-context counting on a hand-built table (positive, negative and non-common contexts).
6. Reconciliation: the loaded p95 from the raw frame equals the master on a sample of drives (full set in the tool run).

## 7. Accept / reject and decision rules
- Accept to display only if: fixture tests pass; reconciliation has 0 mismatches over all drives; a blind audit (Sonnet, claim + data path only)
  reproduces E1, E3 and the E5 counts within 0.02 mV/month and exactly respectively; Director go.
- Display shape (if accepted): a labelled "steady-load check" line beside the released loaded slope in the Cell Health section, with n drives and days,
  both interval types, and the sign of the interval. It never replaces the released slope. Wording by sign: if an interval includes 0, the line says
  the drift is not established under steady load (never "no degradation"); if it excludes 0 it is described by its sign.
- Method disagreement (E1 vs E2, day vs week clustering, nearest vs interpolated pairing) is reported, never tuned to agree. If E1 and the released
  slope disagree on whether zero is covered, that is reported as a finding and escalated to the Director; it is not resolved by choosing a design.
- Reject / not displayed if: reconciliation fails, the blind audit does not reproduce, or fewer than 40 drives on 15 days qualify (support floor).
- Falsification: the claim "the loaded slope is a pairing artefact of rapid current" is supported only if E1's interval excludes the released slope
  point value AND includes 0 while the released interval excludes 0; any other outcome is reported as undecided.

## 8. Language and scope
Cell spread is a logged-signal quantity, "paired by nearest timestamp" (never "simultaneous" or "measured at the same instant"). No capacity,
state-of-health or ageing claim; a drift in spread is a conditional association in one vehicle over a seasonal window. The terminal-response look
(M580) is untouched. Not article-bound: no article figure without the Opus audit and Andrii's sign-off.

## 9. Out of scope
The same-response logging change (needs a new logger setup), the coolant gap, any change to `degradationTrends.cellSpread` or to `drive_master.csv`.
