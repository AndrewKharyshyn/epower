# M639 pre-registered spec (Rev 0): mix-standardised f_gen as a labelled sensitivity (self-audit W1-14, finding A-5)

Status: Rev 0, written BEFORE any M639 result exists (2026-11-13; master 665 drives, MD5 77bbe275f8c22eaf62d8636867764af3). Gate NA: spec, blind audit (`analytical-auditor`), Director (`research-director`) before any payload or dashboard change. No owner decision is required; the headline `gtrClosure.fGen` (0.5093, ratio of sums, 435 canonical-clean fuel-instrumented drives) stays byte-unchanged.
Wording: f_gen is a model-derived (Path B) generator-coincident share of gross traction demand, never "measured".

## 0. Rev 1 (Director review 2026-11-13, research-director; supersedes any conflicting clause below)
Verdict: revise. Answers: (a) E1 primary, E2 secondary and labelled as the audit's arithmetic; E1 assumes within-stratum exchangeability (fuel-PID availability does not depend on season, SoC or period given drive_type), stated in the block; (b) the 4-stratum E1 is payload-only and labelled extrapolative while highway (5 drives / 3 days) is unsupported; mixed_highway (10 / 6) is labelled "at floor"; (c) the {urban, non-urban} collapse is the DISPLAYED primary whenever a stratum with w_s above 5 % is unsupported, with the residual imbalance within non-urban reported; (d) wording "drive-type-mix-standardised (corpus km mix) f_gen, model-derived (Path B), sensitivity"; forbidden: corpus f_gen, corrected, true, adjusted headline, representative, unbiased, measured, "headline is biased"; (e) fixed weights understate uncertainty: the primary CI is a joint day-clustered bootstrap over corpus calendar days (w_s and the strata recomputed in the same replicate), the fixed-w CI is reported beside it.
Required changes (all adopted):
- R1 Estimand set: the headline `gtrClosure.fGen` is the closure set (433 drives, 76 days, not the 435 of `wire_gtr_seasonal`), source `analyses/M377c_closure_perdrive.csv`, f_gen = sum(g2t) / sum(trac) (ratio of energy sums). E0 is reproduced from that file byte-exact (0.5093) before anything else; the block attaches to the closure set only. E1 = sum_s w_s (G_s) / sum_s w_s (T_s) with G_s = sum g2t / sum km and T_s = sum trac / sum km in stratum s.
- R2 One drive_type source: `drive_master.csv` for both w_s and the strata, with an assert that it equals the closure file's drive_type for every shared file.
- R3 Reference set and weights are script-derived (canonical-clean drives of `drive_master.csv`, distance_km > 0), no typed counts; the w_s table and the overlap (fuel-closure drives within the reference set) are stated.
- R4 Decision rule: the headline is never replaced. If the E1 interval excludes the E0 value 0.5093, the wording is "the headline is mix-sensitive"; otherwise "not distinguished from the headline at this support".
- R5 Dropped replicates: a replicate with an empty stratum is dropped and counted for EVERY version; P(no highway day in a replicate) is near 5 % for the 4-stratum version, so the collapsed version carries the interval and the drop rate is reported for all versions.
- R6 Isolation: sibling key `generatorTractionRecon.gtrClosure.fGenMixStandardised` (not a child of `fGen`); stage after the gtrClosure refresh; a deep diff after a refresh dry run must show the leaf survives and nothing else moves.
- R7 Article restriction restated (Opus audit and Andrii's sign-off before any article use); blind audit before display; language-gate rules with the M639 id.
Disclosure: after the Director ruling and before the code, the per-stratum ratios of the closure file were read once to confirm that the reproduction of E0 works (0.5093 from sum g2t / sum trac); no rule above was changed after that look.

## 1. Problem
The fuel-instrumented subset is not the corpus: by km it is 52.8 % urban against 32.1 % urban in the canonical-clean corpus (self-audit S; drive_type column of `drive_master.csv`). f_gen differs strongly by drive type (`driveTypeSplit`), so the headline km-weighted ratio of sums describes the fuel subset, not the corpus mix. The audit's quick reweighting gave about 0.59 (arithmetic only, never reproduced in the repo). Structural support facts read from disk before writing this spec (no f_gen result read): the fuel subset has urban 402 drives / 75 days, mixed 18 / 15, mixed_highway 10 / 6, highway 5 / 3.

## 2. Estimands (labelled)
- E0 (headline, unchanged): fuel-subset, km-weighted ratio of sums, sum(gen_to_traction x km) / sum(traction_gross x km).
- E1 (new, primary sensitivity): corpus-mix-standardised ratio, F* = sum_s w_s G_s / sum_s w_s T_s, with G_s, T_s the km-weighted per-100 km means of gen_to_traction and traction_gross in drive-type stratum s of the fuel subset, and w_s the km share of stratum s in the canonical-clean CORPUS (all 651 canonical-clean drives of `drive_master.csv`, one fixed reference mix, never per cohort). It answers: what would the ratio of sums be if the fuel subset had the corpus drive-type mix.
- E2 (secondary): the weighted mean of stratum ratios, sum_s w_s f_s, reported beside (this is the audit's arithmetic; it differs from E1 because it does not weight by traction demand).
- Strata: `drive_type` in {urban, mixed, mixed_highway, highway} as stored. Collapsed alternative (pre-registered): {urban, non-urban} to test sensitivity to the thin highway cell.

## 3. Support rules (pre-registered, from the project's floor)
A stratum is SUPPORTED when it has at least 10 drives on at least 5 calendar days in the fuel subset. The highway cell (5 drives / 3 days) is not supported; mixed_highway (10 / 6) is borderline-supported. If any stratum with w_s above 5 % is unsupported, E1 and E2 are labelled "extrapolative: the corpus-mix share of an unsupported stratum is carried by a thin cell" and the collapsed {urban, non-urban} version is reported with the same label rules; no estimate is presented without its n drives and days per stratum. Nothing is tuned to move the estimate.

## 4. Uncertainty
Day-clustered percentile bootstrap (calendar day = cluster; seed 42; 4000 draws) of E1 and E2: resample days with replacement from the fuel subset, recompute strata ratios with the FIXED reference weights w_s; a replicate with an empty stratum is dropped and counted (`nDroppedReplicates`), and if more than 5 % are dropped the interval is withheld with the reason. Report n drives, n days, per-stratum counts, the reference weights and the 95 % CI.

## 5. Known-answer and isolation
- Unit test: synthetic strata with known G_s, T_s, w_s give the exact E1 and E2; a stratum with zero support is flagged; the bootstrap is deterministic with the seed.
- Known-answer targets from the self-audit, never typed into the repo: fuel-subset km mix 52.8 % urban, corpus 32.1 %; per-drive mean f_gen about 0.33 versus the ratio of sums 0.509; the audit's reweighted figure about 0.59 (an arithmetic estimate: it must be compared with E2, not E1, and a gap is explained, not forced).
- Payload: one additive block `generatorTractionRecon.gtrClosure.fGen.mixStandardised` written by a script (`tools/m639_fgen_mix.py`) with the strata table; the deep diff shows only that block; `fGen.est`, `ci95` and every other leaf byte-identical.
- Dashboard: one labelled sentence beside the fGen headline (estimand text: "fuel-subset, km-weighted"), bound to the new keys; language rule for the forbidden readings ("the corpus f_gen", "corrected f_gen", "true f_gen").
- Ingestion: a stage after the gtrClosure refresh so the leaf survives; `verified:false` until its first full run.

## 6. Decisions requested
Director: (a) is E1 the right primary and E2 only a secondary; (b) is the support rule (10 drives, 5 days; extrapolative label) acceptable, or must the unsupported highway cell block the display; (c) is the {urban, non-urban} collapse the right pre-registered alternative; (d) wording ladder; (e) does the bootstrap with fixed reference weights understate uncertainty (the corpus mix itself is estimated)?
