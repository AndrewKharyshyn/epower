# M497 spec (Rev 2): day-clustered, SoC-standardised start-hazard ratio, high speed versus stationary (replaces the max-over-bins headline)

Status: Rev 2, written 2026-10-24 BEFORE any M497 computation. Rev 1 was reviewed by the research-director (ruling "revise", nine required revisions, all folded in below). Origin: independent audit 2026-10-23, findings PB-01 (headline = the largest of five per-bin ratios, 262.9 at SoC 60) and ST-08 (Wilson intervals on per-second at-risk counts treat consecutive seconds as independent). Files: `audit_package_2026-10-23/pub/findings.csv`, `stats/findings.csv`.

## Question
How much higher is the per-second probability that the engine starts while the vehicle is at high speed than while it is stationary, at the same battery SoC, and how well is that ratio determined when calendar day (not the second) is the unit of independence?

## Estimand (frozen)
Per-second start hazard h(s, b) = P(engine on at t | engine off at t-1, speed band s at second t, SoC bin b at second t), as tabulated by the existing `socHysteresis` block (`_soc_hysteresis_transitions`: 1 Hz grid, engine on = rpm > 500, `_apply_speed_priority`, SoC bins `soc // 5 * 5` clipped to [35, 90], speed bands stationary < 5 km/h, high >= 60 km/h; the speed and SoC used are those of the second t on which the start is evaluated, not t-1). Starts are detector-derived (rpm > 500), never "measured".
Primary estimand R: the Mantel-Haenszel common rate ratio of high versus stationary across SoC bins,
R = sum_b [k_hi(b) n_st(b) / N(b)] / sum_b [k_st(b) n_hi(b) / N(b)], N(b) = n_hi(b) + n_st(b).
It is a SoC-standardised ratio of hazards, not an effect of speed. Temperature, HVAC and key-on warm-up starts are confounded with the stationary band and are not adjusted (see S7). It replaces the headline `stationaryVsHighwayContrast[0]`; no bin is selected on its ratio. The old headline (a single-bin ratio) and R are different estimands; their comparison is a wording check, not a test.

## Eligible bins (frozen once, before any resampling)
Bins with n >= 30 at-risk seconds in BOTH strata in the pooled corpus counts. The set is computed once, recorded in the result, and used unchanged in every bootstrap draw, every leave-one-out and every sensitivity (S5, S7 recompute it from their own pooled counts and say so).

## Population and eligibility (frozen)
Every drive covered by the existing `socHysteresis` pass (`nDrivesCovered`; the pass has no `ens_outlier_v2` filter and M497 adds none, so the counts reproduce the published cells). Day = the calendar date of the drive (`drive_master.date`), as in M428/M495. Drives without current/voltage are not excluded (rpm, SoC and speed only).

## Method (frozen)
1. Rebuild the per-second at-risk start table per drive with the unchanged `_soc_hysteresis_transitions` and count k and n per (day, SoC bin, speed band).
2. Hard fidelity stop: pooled k and n per (SoC bin, band) equal the published `socHysteresis.startProbBySocSpeed` k and n exactly for every published cell, otherwise STOP.
3. Point estimate R from the pooled counts of the frozen bins.
4. Co-primary intervals (resampling unit: calendar day; all with seed 42 where random):
   (a) day-clustered percentile bootstrap, 4000 draws, R recomputed per draw on the frozen bins;
   (b) ISO-week-cluster percentile bootstrap, 4000 draws. It is co-primary only if there are >= 20 weeks and >= 8 weeks with at least one stationary start in the frozen bins; otherwise it is reported as a labelled sensitivity;
   (c) a sparse-data interval: Poisson regression on the (day, bin, band) cells, log rate = SoC-bin fixed effects + beta * high, offset log(n), cluster-robust (CR1) covariance by calendar day (an independence GEE), Wald interval for beta, reported as exp(beta) with its interval.
   Handling of degenerate bootstrap draws: a draw with k_st = 0 and k_hi > 0 over the frozen bins has R = +infinity and STAYS in the percentiles; only draws with k_st = 0 and k_hi = 0 are undefined (counted, reported, excluded). If more than 2.5 % of draws are +infinity the upper bound is reported as "unbounded". Percentiles are never taken over finite draws only.
5. Count disclosure: k_st, k_hi (frozen bins), days with at least one stationary start, weeks with at least one, and the share of k_st on the top three days.
6. Per-bin display: the stratum ratio per eligible bin with its own day-clustered interval (same infinity rule). A bin with k_st = 0 is shown as "lower bound only", not given a ratio. The displayed bin range covers bins with k_st > 0 and states how many eligible bins are excluded; the maximum is never headlined.
7. Sensitivities (reported, none selected): S1 crude pooled ratio ignoring SoC; S2 drive-level bootstrap (anti-conservative reference); S3 leave-one-day-out range of R and the day with the most stationary starts; S4 leave-one-SoC-bin-out; S5 stationary threshold < 2 km/h instead of < 5 km/h; S6 the iid Katz interval of the old headline cell (SoC 60), labelled "iid, anti-conservative, comparison only"; S7 each drive's first engine start (key-on warm-up) removed from both bands.

## Decision rules and wording ladder (frozen, planning thresholds)
Define the reporting lower bound L = the minimum lower bound over the co-primary intervals (a), (c) and (b) when (b) qualifies. "Wider" = the larger log(UB/LB), an unbounded interval counting as widest; the headline shows the widest interval's bounds beside R.
- L >= 50: "roughly two orders of magnitude higher".
- 10 <= L < 50: "at least an order of magnitude higher".
- L < 10: "higher; the ratio is poorly determined" (no order-of-magnitude phrase).
- k_st < 20 or fewer than 10 days with a stationary start in the frozen bins: the dashboard adds "stationary-start support is thin" (expected to apply, the published stationary k at SoC 60 is 14).
- If the fidelity stop fails or no co-primary interval can be formed: no dashboard change is made and the failure is reported.
The change of headline from 262.9 is reported as a change of estimand and of uncertainty statement; never as a "correction" or "error".

## Outputs
`analyses/M497_result.json` (n drives, n days, weeks, frozen bins, cell counts by day, R, intervals, infinity/undefined shares, sensitivities, provenance: master MD5, script sha256, spec sha256, seed). Script `tools/m497_start_ratio.py`; known-answer test `tests/synthetic/test_m497_start_ratio.py` (MH on a hand-computed table; Poisson-cluster estimate on a synthetic corpus with a known common ratio and day effects; infinity-draw rule; fidelity stop on an altered cell). The spec sha256 is recorded in the CHANGELOG before the script runs.
Dashboard (only after the Director's decision): additive leaf `socHysteresis.startRatioClustered`; chart/KPI text binds to it; the iid bars are labelled anti-conservative; `contrast[0]` is no longer read as the headline. The "7 events" figure in `CLAUDE.md`/`docs` is replaced by the computed k_st only through an edit the owner approves; this milestone does not edit `CLAUDE.md`.

## Out of scope
The M119-v2 model-based contrast; the stop side; temperature and demand adjustment.
