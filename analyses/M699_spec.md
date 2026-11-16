# M699 spec (Rev 0, pre-registered): rest-anchored capacity indicators (backlog N-08)

Status: DRAFT for Director review. No result exists. Written 2026-11-16 before any estimator is implemented.
Owner mandate: self-audit backlog item N-08 (`analyses/self_audit_2026-11-11/backlog.json`). Road-load / CoC / mass items stay closed.

## 1. Question
Is there an independent, rest-anchored check of the apparent capacity of the logged BMS SoC scale (M403 `capacityBasis.ahPer100`, 4.90 Ah per 100 points, CI 4.81-4.99), and does a quarterly apparent-capacity series show a step under a pre-set rule? This is NOT state of health and NOT usable capacity; the 2.1 kWh `CAP_KWH` stays `verified:false`.

## 2. Estimands (all estimated / model-derived, never "measured")
- E1 (rest-OCV map): median relaxed pack voltage per SoC bin at rest anchors, with SoC hysteresis between approach-from-above and approach-from-below. Output: V_rest(SoC) curve, per-bin n (drives, days).
- E2 (anchor-pair Ah per SoC): for a wide swing between two relaxed anchors, Ah(current integral) / (SoC_after - SoC_before) * 100. Compared with `capacityBasis.ahPer100` as an independent check, not a replacement.
- E3 (quarterly tracking): `ahPer100` per calendar quarter (all canonical-clean drives; E2 where anchors exist), with a pre-set step rule (section 6).

## 3. Eligibility (fixed before any result)
- Canonical clean: `ens_outlier_v2 == False`, usable current and SoC series (as M403).
- Relaxed anchor: a drive boundary whose adjacent parked gap is >= R hours. Primary R = 2 h; sensitivities R = 6 h and 12 h. Gap from clock times plus file-name date (as `parked_time_budget`; gaps spanning missing drives are not anchors).
- Wide swing: SoC_max - SoC_min >= 20 points within the drive between two anchors (sensitivity 10 and 30).
- Feasibility counts taken from `drive_master.csv` BEFORE this spec (eligibility only, no estimate): R=2 h, swing>=20: 48 drives / 41 days; R=6 h: 18 / 17; R=12 h: 6 / 6; swing>=10 at R=2 h: 67 / 51. Counts are a design fact, not a result.

## 4. Methods
- E1: first and last relaxed samples of the voltage channel at anchors, temperature-stratified (cold/shoulder/warm classes as in the seasonal block) because OCV depends on temperature; no pooled curve across classes unless a class has < 10 drives (then not shown).
- E2: Ah from the logged current integrated by the M403 primary rule (B_primary, trapezoid, gap rules unchanged) between anchor samples; SoC from the logged BMS SoC at the anchors.
- E3: per quarter, the M403 B_primary estimator restricted to the quarter. Quarters with < 10 drives or < 5 days are not shown.
- Uncertainty: day-clustered percentile bootstrap, seed 42, 4000 draws; every estimate carries n (drives, days). Method disagreement (B_primary vs E2 vs M403 method range 4.67-5.35) is reported, never tuned to agree.

## 5. Primary vs sensitivity
Primary: R = 2 h, swing >= 20, B_primary. Sensitivities: R in {6, 12}, swing in {10, 30}, current-sign (reverse) variant as in M403, lag +-2 s, per-class temperature stratification, cadence stratum (fast / slow polled).

## 6. Pre-set step rule for E3 (frozen now)
A step is declared for quarter q only if (a) the day-clustered 95% interval of q lies entirely outside the pooled interval of all prior quarters AND (b) the same sign persists in the next quarter when it exists. Otherwise: "no step established". The study window (about 6 months at the time of writing) is too short for a degradation claim; TOST "not established" is not "no degradation".

## 7. Accept / reject / falsify
- Support: E2 is "consistent with" M403 if its interval overlaps the M403 interval; "disagrees" if disjoint at R=2 h and swing>=20, in which case the disagreement is reported as a finding about SoC semantics or current calibration, not resolved.
- E1 hysteresis: shown only where both approach directions have >= 10 drives and >= 5 days per bin.
- Falsifiers: anchors are not relaxed (V still drifting > 0.5 V over the last 60 s of the rest-adjacent samples); SoC is quantised so coarsely (0.25 steps, logged resolution) that the swing denominator error exceeds 5%; temperature stratification leaves < 10 drives in every class.
- Relaxation is checked, not assumed: per anchor the V drift rate over the last 60 s is stored and anchors above the threshold are excluded (threshold is frozen here: 0.5 V per minute is NOT used; the rule is |dV/dt| <= 0.05 V/min, flagged as a design choice to review).

## 8. Outputs
Additive payload block `capacityAnchors` (stamped, isolation-guarded splice, leaf-level), no change to any other leaf or to `drive_master.csv`. Block carries: eligibility counts, E1 table, E2 estimate and sensitivities, E3 quarterly table with step rule status, flags, conventions, provenance (master MD5, script sha). Stage `capacity_anchors` (verified:false until a full ingestion run). Known-answer test `tests/synthetic/test_m699_capacity_anchors.py` (synthetic cell with known Ah per SoC, relaxed and unrelaxed anchors, hysteresis offset) in the CI python list.

## 9. Language
"apparent capacity of the logged SoC scale (estimated)"; never "capacity fade", "state of health", "measured capacity", "degradation detected". A language rule `M699-capacity-anchor-wording` enters `language_gate.py` with the implementation. No dashboard display in this milestone (block only); a display needs a separate spec step and Director check of rendered text.

## 10. Open design choices for the Director
1. Relaxation threshold 0.05 V/min and the 60 s window.
2. Whether quarterly tracking should be monthly given 6 months of data (current rule would show at most two quarters).
3. Whether E2 anchors at R = 2 h are adequate for relaxation at cold temperature.

## 11. Rev 1 (2026-11-16, after Director review "revise"; supersedes any conflicting text in sections 3-10)
Director required changes applied (verdict JSON recorded in the CHANGELOG entry; subagent output is not owner approval).
1. Anchor geometry: a drive end is under load and is NOT an anchor. An E2 pair is key-on of drive k to key-on of drive k+1, both after a parked gap >= R; Ah is integrated over drive k only. The SoC change across the parked gap (soc_start(k+1) - soc_end(k)) is reported as a BMS rest re-estimate; zero parked current is an explicit assumption (no logger while parked).
2. Anchor sample: the first key-on samples with |I| <= a threshold frozen at implementation from `signal_representation.json` (current grid step), before any traction. Relaxation check: regression slope of pack voltage over >= 120-300 s of such low-current samples against a resolution-derived threshold (the 0.05 V/min rule is withdrawn: the voltage grid step is 0.16 V); R is the main relaxation control. The contradictory 0.5 V/min text in section 7 is void.
3. Swing denominator = |SoC_anchor(k+1) - SoC_anchor(k)|, not within-drive max-min.
4. Feasibility recounted under that definition BEFORE any estimate (eligibility counts only, canonical-clean both drives): R=2 h: delta SoC >= 10: 18 pairs / 16 days; >= 20: 2 / 2; >= 30: 0. R=6 h: >= 10: 6 / 6; >= 20: 1 / 1. R=12 h: >= 10: 1 / 1. Consequence, frozen now: the E2 floor (10 drives, 5 days) is met only at R=2 h and delta SoC >= 10, so primary E2 = R 2 h, delta SoC >= 10, labelled exploratory-limited; the 20-point rule, R=6 h and R=12 h E2 are shown as "not estimable" with their counts. Cold E2 at R=2 h is exploratory without a verdict (Director: needs R >= 6 h).
5. Gap integrity guard: logged km is below ODO, so a gap may hide an unlogged drive; the guard (ODO/logged-km based where available, otherwise date-gap) and the exclusion count are reported.
6. Consistency rule: joint day-clustered bootstrap difference (E2 minus B_primary on the same drives; M403 recomputed on the current corpus, not the carried 4.90), pre-set margin chosen at implementation from the logged SoC resolution and recorded before the run; verdicts consistent / disagrees / not established. Interval overlap is not used. With n this small "not established" is the expected verdict; MDE is reported.
7. E3: no step is decidable with fewer than 3 quarters (rule (b) needs a following quarter); stated in the block. Quarterly is the decision unit; monthly is description only with no step rule. E3 is stratified by temperature class and cadence stratum before rule (a) (B6 check failed and stays shown), rule based on the difference interval, MDE reported.
8. E2 is not independent of M403 (same current and SoC channels): worded "alternative anchoring of the same channels". E1 is a map of the BMS-reported SoC and may be circular with the BMS OCV lookup; SoC resolution is read from `signal_representation.json`, not asserted.
9. Section 4 pooling clause: no pooled E1 curve across temperature classes; a class with < 10 drives or < 5 days is not shown.
Risks recorded: small n gives wide intervals so "consistent" can be a false negative; period, season, cadence and SoC window are confounded in E3; BMS SoC may be rescaled at key-on; wording must not drift to state of health or a link to CAP_KWH.
Open for the owner (information only, no sign-off needed): E2 will most likely end "not established"; E1 and E3 are the substantive outputs.
