# M532 spec (Rev 1, DRAFT for Director review): sensitivity of the M393 / M529 emulated-sampling result to the slow-pool draw and the emulation seeds (closes a stated limit of M529)

Status: PRE-REGISTERED DRAFT, 2026-10-28, written before any result exists. Owner: Andrii (chat, 2026-10-28: "continue" after M531; the first optional item left open by M529). Origin: M529 limits: "sensitivity to other slow pools and seeds was not assessed" (Director ruling M529, `limits`, follow-up 1). Scope: an analysis result file and the CHANGELOG only; NO payload change, NO displayed change, NO change to the M393 script or to the M393 / M529 outputs.

## 1. Question

The M393 emulation thins each fast-regime clean drive to the slow-regime sampling pattern. The pattern comes from a pool of 40 slow-regime drives drawn with `numpy.random.default_rng(7)` and each emulation uses `default_rng(s * 100003 + n)` for `s` in 0..2 (n = the drive's index among the fast clean drives). M529 reported one realisation. How much do the era-level results (the paired difference emulated minus original by era, and the number of drives that lose the proxy) depend on those random choices?

## 2. Design (pre-registered)

- Same data and rules as M529: `ens_outlier_v2`-clean set with finite `vreg_R_pack_mohm`, `T_pack_mean_avg`, `vreg_I_p95_A` and a date (n = 274; fast1 67, fast2 40), `cadence_regime.csv`, eras fast1 = 2026-08-14..09-06 and fast2 = from 2026-10-01, `raw_only/` staged files, `tools/cadence_emulate.py` (`build_pools`, `emulate`) and `compute_drive_summary_v6.analyze_bytes` used as libraries, unchanged.
- Replicates: pool-draw seeds R in {7 (the M529 value, reproduced as a control), 11, 13, 17, 19, 23}; for each R the emulation seed base uses the same formula `s * 100003 + n + 7919 * k` with the replicate index k = 0 for R = 7 (so R = 7 reproduces M529 exactly) and k = 1..5 for the others; 3 seeds per drive per replicate as in M529. Six replicates in total; the number of replicates is fixed in advance.
- Per replicate (same statistics as M529 Part C): the number of fast clean drives that keep a proxy and that lose it (by era), the mean paired difference emulated minus original by era with the day-clustered percentile bootstrap interval (seed 42, 4000 draws, calendar-day clusters).
- Summary across replicates (descriptive): range and spread (min, max, standard deviation) of the era means, of the interval endpoints and of the loss counts; the replicate-to-replicate spread of the era mean is compared with the within-replicate interval half-width. No hypothesis test. The M529 values are the control: R = 7 must reproduce them exactly (STOP if not: the replicate code would not be the M393 logic).

## 3. Acceptance, falsification, escalation

- A1 control reproduction: replicate R = 7 equals the M529 result exactly (kept, lose-proxy counts, era n, means, intervals).
- A2 all six replicates complete with the same fast clean set (107 drives); a replicate that errors is reported, not dropped.
- A3 blind `analytical-auditor` re-executes ONE non-control replicate with its own driver (the pool seed and seed formula given; the library functions used as black boxes) and reproduces its era means and loss counts.
- A4 escalate to the Director if any replicate gives an era mean outside the M529 interval of that era, if the paired difference interval of an era includes zero in any replicate, if the number of drives losing the proxy differs by more than 5 from the M529 value (29), or if the spread of the era mean across replicates exceeds half of the M529 interval half-width. Tripwires, not tests.
- Stop: control mismatch; any change to a payload value (none expected).

## 4. Outputs and language

`analyses/M532_emulation_seed_sensitivity.json` (script-written, first output kept) and the CHANGELOG entry with the spread table. Language: "emulated sampling sensitivity, not a causal cadence effect"; "spread across slow-pool draws and seeds"; never "robust", "confirmed", "no cadence effect"; the paired differences stay conditional on the proxy surviving emulation. If the spread is small relative to the interval, the M529 limit is recorded as "assessed: spread X"; if not, the Director decides whether the displayed statement needs a clause (a later wording milestone).

## 5. Gates and process

py_compile, the script run once in the background (log kept; about 25 minutes), A1-A4, CHANGELOG M532 (spec SHA-256 before the run, result hash, audit, decision), PR. The new script is `analyses/M532_emulation_seed_sensitivity.py`; no CI step (it needs the staged raw copies; release_check does not run it). Merge ONLY when the PR run reads completed + success on the current head (checked in the same command). No article figure; any article use needs the Opus audit and Andrii's sign-off.

## 6. Questions for the Director

Q1 Are six replicates (control + five) enough, or should the count be larger? Q2 Is varying the pool draw and the emulation seeds together adequate, or should the two sources of randomness be varied separately (pool only; seeds only)? Q3 Are the A4 tripwires right? Q4 Should the result be stored in the payload (e.g. `powerFade.cadenceSensitivity.emulation.sensitivity`) after the decision, or stay a result file and CHANGELOG entry?

## 7. Rev 2 (2026-10-28): Director review (verdict "revise, minor"); incorporated. Rev 1 SHA-256 recorded before the run: 96f7316b0af69c88d6ce52f1ab54454977262e58495c3012e299f683fad3edf5.

- **Rulings.** Q1: six replicates are too few to rely on a spread (df = 5): the count is FIXED at 1 control + 10 (k = 0 control with pool seed 7; k = 1..10 with pool seeds 11, 13, 17, 19, 23, 29, 31, 37, 41, 43 and the emulation seed offset 7919*k); about 45-55 minutes in the background. Q2: varying the pool draw and the emulation seeds jointly is adequate for the M529 limit (total sensitivity to the random choices); the spread is NOT attributed to either source; separate pool-only / seed-only runs and a pool-size variation are follow-ups only if a tripwire fires. Q3: tripwires revised (below). Q4: NO payload entry: a result file plus the CHANGELOG entry; if a tripwire fires the Director decides on a later wording milestone.
- **R1 (A1).** Control = exact equality of the era n, the means, the interval endpoints, the kept / lose counts and the era loss counts with the stored M529 result JSON at the precision stored there (the means and endpoints are stored rounded to 3 decimals; the lose SET is not stored in M529, so the lose set of the control is the reference for the Jaccard overlaps below); the master MD5 and the staged raw copies are checked before and after the run; the numpy version is recorded. STOP on any mismatch.
- **R2 (A4 definitions).** Spread = the RANGE (max - min) across all eleven replicates (control included); half-width = (hi - lo) / 2 of the M529 interval of that era (fast1 about 0.67, fast2 about 1.27); the standard deviation is descriptive only. The cross-replicate range is not a confidence interval and is never pooled with the bootstrap intervals.
- **R3 (A4 tripwires).** Escalate if: any replicate's era mean lies outside the M529 interval of that era; any replicate's era interval includes zero; any replicate's era mean changes sign; the total number of lost proxies differs from 29 by more than 5, or the number lost in either era differs from the M529 era value (fast1 14, fast2 15) by more than 3; the range of an era mean exceeds half of the M529 half-width.
- **R4 (composition).** The kept set changes between replicates: also reported are the common-support mean (the drives that keep the proxy in EVERY replicate, per replicate and per era) and the Jaccard overlap of each replicate's lose set with the control's.
- **R5 (A3).** The audited replicate is fixed BEFORE the run: k = 4 (pool seed 19, seed offset 4 * 7919). The auditor rebuilds the seed formula from this spec text (not from the M532 script) and reproduces the era means, the interval endpoints, the loss counts and the lose set. Scope limit stated: `build_pools`, `emulate` and `analyze_bytes` are treated as black boxes and are not re-verified.
- **Limits and language.** The pool size (40) and the 3 seeds per drive are not varied; the paired differences stay conditional on the proxy surviving emulation; the resistance proxy is model-derived; the variation is Monte Carlo variation of the emulation with the data held fixed, not sampling uncertainty and not a causal cadence effect. Language: "emulated sampling sensitivity, not a causal cadence effect"; "spread across slow-pool draws and seeds"; never robust / confirmed / no cadence effect / validated; never call the range an interval or CI. No Andrii sign-off.
