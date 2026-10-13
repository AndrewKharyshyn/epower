# M428 spec - out-of-time evaluation of the frozen M119-v2 hazard model (audit F08)

Status: PRE-REGISTERED, written before any result of this analysis exists. Rev 2, 2026-10-14 (Rev 1 reviewed by the research-director: verdict "revise", three blocking items, all adopted below; Rev 2 changes are listed in section 11). Owner: Andrii. Origin: external audit 2026-10-13, finding F08 ("Frozen 489-drive hazard model is displayed alongside a 554-drive corpus; evaluate later drives out of time before relying on the frozen surfaces"), triaged in M427.

## 1. Question and estimand

Do the frozen five-variable duration-aware cloglog hazard models of engine start / stop (M119-v2, `socHysteresisV2`, carried forward at their 489-drive basis, `recompute_m119v2=False`) show material degradation on drives they never saw?

Estimand (per side, START and STOP separately): the out-of-time predictive performance of the model trained once on the basis drives and applied unchanged to the later drives:
- log-loss skill against a constant-rate baseline at the BASIS event rate, `SKILL = 1 - LL_model / LL_const`;
- calibration in the large, `O/E = observed events / sum of predicted probabilities` over the later at-risk seconds, and O/E by pack-temperature band;
- discrimination, PR-AUC with the event prevalence and the lift `PR-AUC / prevalence`;
- extrapolation, the excess of the later out-of-support share over the basis's own out-of-support share.

Events are detector-derived (M231 canonical detector); hazards are model-derived. All intervals are conditional on the fitted basis model (training uncertainty is not propagated). Not an estimand: any refit, model comparison, statement about the vehicle's controller, or new surface.

## 2. Population and data

- Master: `drive_master.csv` (578 rows, MD5 `a641f34d7528d004b900c151cbde3d6d`, verified before and after). Basis = first 489 master rows (the carried block's `corpusSizeAtRecompute`; master is append-only and date-monotonic; 104 calendar days; last basis day 2026-09-30). Later = rows 490-578 (89 drives, 14 calendar days, 2026-09-30 to 2026-10-13). 2026-09-30 holds both basis and later drives; the split is by drive (row order), the day stays the resampling cluster, and S3 drops that day.
- At-risk tables: unchanged `m119v2_model._corpus_tables` via `tools/m318_run.py tables --n-first 578` on staged `raw_only/` (raw = sha256-verified originals, M366). All 578 raw files are checked against `raw_manifest.json` with the M427 `replay_master.verify_raw_identity` contract before the pass (done: 578/578). `_corpus_tables` silently skips files that fail to load: the split is by file name and the number of master files absent from each side's table is reported for basis and later.
- Eligibility: complete-case on `CORE5` exactly as `_final_fit`; M231 detector and boundary rules unchanged.

## 3. Method (no refit on later data)

1. Split the tables by file name into basis and later.
2. Frozen-model reproduction: the declared `fiveVarDur` design (terms soc, speed, tpack, demand, logdur; interactions soc x demand, tpack x demand, soc x logdur; knots and scale learned on basis rows only) fit with `fit_glm` (cloglog, `groups=day`) as `_final_fit` does, on basis rows. The block stores surfaces but no coefficients, so this reproduction is the frozen model. No later row enters knots, scale, coefficients or selection.
3. Fidelity (declared tolerances, planning choices): (a) basis at-risk seconds and events against the carried block counts (`nStartAtRisk` 381713 / `nStartEvents` 5450 / `nStopAtRisk` 301247 / `nStopEvents` 5431), tolerance 1 % relative; (b) the same k=5 blocked-day CV the block used (`blocked_day_folds`, `oos_predict`) rerun on the basis tables, its log-loss against the block's `ladder.<side>.ladder.fiveVarDur.logLoss`, tolerance 2 % relative; (c) the reproduced surfaces (`_surfaces` with the stored `tempLevels`) against the stored `grids` leaf by leaf on the stored grid: max and median absolute hazard difference, tolerances max <= 0.005 and median <= 0.0005. If any tolerance fails, every outcome sentence names "the reproduced frozen design" (not the displayed surfaces) and carries the failed check.
4. Predict every later at-risk second with `_predict` using the basis-fitted model and basis-learned spline knots (restricted cubic splines, linear beyond the boundary knots).
5. Baselines fitted on basis rows only: B0 constant (basis event rate); B1 `socOnly`. Descriptive extra: constant at the LATER-period rate (separates discrimination from a prevalence shift; no decision role).
6. Metrics on later rows, per side: events, at-risk seconds, prevalence, log-loss, Brier, PR-AUC and lift, O/E, calibration slope and intercept (`m119v2_model.calibration`), SKILL vs B0, SKILL vs B1, paired log-loss difference B1 - model.

## 4. Uncertainty

Calendar day is the cluster. Primary interval: day-clustered percentile bootstrap over the later calendar days, seed 42, 4000 draws, every statistic recomputed per draw. With 14 later days it is discrete and indicative, so it is accompanied by: the effective number of day clusters (`essDays`, Kish, at-risk seconds as weights); the leave-one-day-out range; and a leave-one-day-out jackknife t-interval (G - 1 = 13 df) for the statistics that feed the decision. If D1 or D2 differs between the percentile and the jackknife result, the outcome is "partial" (method disagreement is reported, never tuned). Every estimate carries n (drives, days, events).

## 5. Support and drift (descriptive, plus D3)

- Per predictor and side: share of at-risk seconds outside the basis [P1, P99], for the BASIS rows (its own outside share, about 2 % by construction) and for the LATER rows; excess = later minus basis, in percentage points, weighted by at-risk seconds, point estimate. The union over predictors is reported separately and has no decision role. Also outside [min, max].
- Pack temperature is a known, non-blind case (the M321 monitor already flags W2/W3: later days reach below the fit-basis range). D3 for tpack is declared not blind.
- Metrics of 3.6 on in-support seconds (all five predictors inside the basis [P1, P99]) and on the remainder; O/E by pack-temperature band (fixed bands < 10, 10-20, 20-30, 30-40, >= 40 C; n, events, expected, O/E, so offsetting miscalibration is visible).
- In-time reference: the published blocked-day CV and rolling-origin `fiveVarDur` values shown beside the out-of-time values (different protocol, descriptive); a descriptive flag when the out-of-time log-loss exceeds the upper bound of the block's published blocked-CV log-loss CI.

## 6. Pre-registered decision rule (planning thresholds, declared, not validated)

Per side:
- D1 skill: PASS if the lower bound of the 95 % interval of SKILL vs B0 is > 0; else FAIL.
- D2 calibration, three states on the 95 % interval of O/E: "within" if the interval lies wholly inside [0.80, 1.25]; "MATERIAL" if wholly outside it (above 1.25 or below 0.80); "indeterminate" otherwise (an uninformative wide interval is never "within").
- D3 extrapolation: MATERIAL if, for any single predictor, the later out-of-support excess over the basis's own out-of-support share exceeds 10 percentage points; else "not material".
Outcome (exactly one sentence per side, primary data, percentile interval):
- "refit criterion met (planning threshold)": D1 FAIL, or D2 MATERIAL, or D3 MATERIAL;
- "no material out-of-time degradation detected (planning thresholds; not equivalence)": D1 PASS, D2 within, D3 not material, AND the jackknife and S3 give the same D1/D2/D3 states as the primary;
- "partial: not established (few day clusters): ..." otherwise, naming the D-rule that is indeterminate or that changes under the jackknife or S3.
The thresholds 0.80 / 1.25, 10 pp and the tolerances of 3.3 are declared planning choices (a locked margin prevents post-hoc tuning; it does not make the margin physically meaningful) and are labelled so wherever shown.

## 7. Sensitivities (reported, none selected)

- S1 per-drive: median per-drive log-loss skill over drives with at least 3 events, and the share of such drives with skill > 0; day bootstrap over the drives' days.
- S2 chronological halves of the later period (first 7 / last 7 calendar days): descriptive only, no D-rule.
- S3 drop 2026-09-30 (the day shared with the basis): D1-D3 recomputed; a changed state makes the outcome "partial".
- S4 SKILL vs B1 (`socOnly`) and vs the later-period constant.
- S5 START and STOP each reported alone; no pooled inference.

## 8. What would falsify "no material out-of-time degradation"

D1 FAIL, D2 MATERIAL, D3 MATERIAL, or disagreement of the jackknife / S3 with the primary on any D-state. The positive outcome is non-detection under declared planning thresholds and a 14-day window, never a validation of the surfaces.

## 9. Outputs, provenance, wording

- `analyses/M428_result.json` with n drives / days / events, estimates, CI95, jackknife intervals, method flags, fidelity checks, provenance (master MD5, script sha256, module sha256, tables pickle sha256, raw verification, bootstrap settings) and per-drive event counts for the blind audit.
- Additive payload key `socHysteresisV2.outOfTimeEvaluation` (isolation-checked leaf splice; the carried block and every other leaf unchanged) and one short dashboard paragraph in the M119-v2 section bound to `S.socHysteresisV2.outOfTimeEvaluation.*`, beside the stale-basis disclosure. No figure of the carried block moves.
- Wording: events "detector-derived (M231)", hazards "model-derived", "out-of-time evaluation of the frozen (reproduced) design", "no material out-of-time degradation detected (planning thresholds; not equivalence)", "refit criterion met (planning threshold)"; never "validated", "proves", "adequate", "reconstructs the controller", "measured". The article restriction stands.
- The outcome informs the owner; it does not trigger a refit. A refit (about 11 minutes, memory-bound) is an explicit owner demand and a separate milestone.

## 10. Process

Spec Rev 2 -> `research-director` confirmation of the three blocking items -> script `tools/m428_oot.py` + known-answer test with planted shifts -> run -> validation chain (py_compile, JSON round-trip, `node build_html.js`, `node validate_jsdom.js`, isolation diff, `release_check.py`) -> blind `analytical-auditor` (claim + data path only) -> `research-director` ruling (spec + result + audit) -> CHANGELOG M428, dashboard rule, commit, PR.

## 11. Rev 2 changes (from the Director's review of Rev 1)

Blocking: (1) D2 is now three-state; "within" requires the interval inside the band. (2) D3 is per predictor and per side, excess over the basis's own outside share, point estimate, > 10 pp; union reported separately; tpack declared not blind. (3) Fidelity compares the k=5 blocked-day CV rerun (not an in-sample value) and the reproduced surfaces against the stored grids, with declared tolerances; failure renames the evaluated object "the reproduced frozen design". Recommended, adopted: jackknife t-interval with "partial" on disagreement; later-period constant (descriptive); O/E by pack-temperature band; S1 minimum events per drive; S2 descriptive only; CIs conditional on the fitted model; descriptive flag against the in-time blocked-CV log-loss CI; skipped-file counts per side; S3 can force "partial"; wording ("adequate" removed).

Rev 2.1 (Director confirmation of Rev 2: approve, no remaining blocking item; comments adopted, no threshold changed): any nonzero difference in the 3.3(a) counts is reported as it is, even inside 1 % (M366 found no drift in raw-derived columns, so an exact match is expected); the relative median surface difference (against the stored median hazard) is reported as a descriptive value beside 3.3(c); the number of bootstrap draws with an undefined PR-AUC or O/E (no event in the resample) is recorded; the 2 % blocked-CV log-loss tolerance is labelled a planning choice.

## 12. Deviations and findings recorded after the run (Director ruling 2026-10-14; the spec text above is unchanged)

- Spec 5 says the basis out-of-support share is "about 2 % by construction". It is about 1.0 % for speed, demand and duration (mass at zero); no effect on D3, which uses the measured excess.
- B0 (constant baseline) used the complete-case basis event rate (0.01452 for START), not the raw-table rate (0.01428); the D1 margin is large, the alternative was not run.
- The STOP table lacks 20 basis and 12 later drives. Confirmed from the master: the number of drives with `engine_on_pct = 0` equals those counts in each split, so they have no engine-on second (not load failures).
- STOP PR-AUC is below the lower bound of the in-time blocked-CV interval; the pre-registered descriptive flag covered log-loss only, this PR-AUC flag was added after the run and is descriptive.
- The blind audit (analyses/M428_audit.json; scripts in analyses/M428_audit/) reproduced every claimed number, found no leakage, and reused the project module's DesignSpec / fit_glm / _predict / pr_auc / calibration and the tables pickle (independence partial). Its STOP jackknife O/E differs from the result by about 0.01 with identical states.
- Audit method findings carried into the CHANGELOG and the panel: D2 "within" is unreachable for START with this window (interval width 0.39), so "partial" is the expected default; the pooled STOP O/E hides a 10-20 C band at 0.47 and an out-of-support O/E of 0.48; 2026-10-10 holds 34 % of the later events (essDays 10.3 START, 5.7 STOP).
- Director refit guidance: no refit is triggered; evidence that would change that is D1 FAIL, an O/E interval wholly outside [0.80, 1.25], a tpack excess above 10 pp (STOP is at 8.9), or a STOP cold-band O/E interval below 0.80 over at least two more weeks under a pre-registered rule. The evaluation stays on demand (re-run on +14 calendar days or a new M321 tpack flag); each ingestion carries only the staleness label in the panel.

