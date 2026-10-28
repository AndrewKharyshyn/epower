# M534 spec (Rev 1, DRAFT for Director review): separating the slow-pool draw from the emulation seeds, and the pool size, in the M393 / M529 / M532 emulated-sampling sensitivity

Status: PRE-REGISTERED DRAFT, 2026-10-28, written before any result exists. Owner: Andrii (chat, 2026-10-28: "pool-only and seed-only runs - OK"). Origin: M532 optional follow-up (allowed, not required): the M532 spread (fast1 era mean 1.1-2.2, fast2 1.2-3.1 mOhm) mixes the pool draw and the seeds; M532 always used 40 slow drives and 3 seeds per drive.

## 1. Question
Which of the three Monte Carlo choices produces the spread of the emulated paired difference (emulated minus original proxy, by era): (a) the draw of the 40-drive slow pool, (b) the emulation seeds, (c) the pool size? Descriptive; no hypothesis test; the paired difference stays conditional on the proxy surviving emulation.

## 2. Design (pre-registered)
Same data, eras, helpers (`tools/cadence_emulate.py` build_pools / emulate, `compute_drive_summary_v6.analyze_bytes`), statistics (day-clustered percentile bootstrap, seed 42, 4000 draws) and the script pattern of `analyses/M532_emulation_seed_sensitivity.py` (library use only; that script and the M393 / M529 / M532 outputs are untouched).
- Arm P (pool-only): pool seeds R in {11, 13, 17, 19, 23, 29, 31, 37, 41, 43} (the M532 set), seed offset fixed at k = 0 (formula s*100003 + n, s in 0..2). 10 replicates + control R = 7 (M529).
- Arm S (seed-only): pool fixed at R = 7, seed offset 7919*k for k = 1..10 (new offsets, not the M532 coupling of pool and offset). 10 replicates + control.
- Arm N (pool size): sizes 20, 40 (control), 80 with pool seeds R in {7, 11, 13, 17, 19} each, offset k = 0. Size 80 is feasible (415 slow-regime drives in `cadence_regime.csv`).
- Outputs per replicate as in M532 (kept / lose counts by era, era mean, median, interval, lose set). Summary: per arm the min / max / SD of the era means and of the number of lost proxies; variance share by arm (descriptive: SD of arm P vs arm S; the M532 coupled SD as reference); common-support drives.
- Run-once lock, first output kept, inputs MD5 before and after.

## 3. Acceptance, falsification, escalation
- A1 control: R = 7, k = 0, size 40 reproduces M529 exactly in every arm.
- A2 no replicate error (an erroring replicate is reported, not dropped).
- A3 blind `analytical-auditor` re-executes ONE replicate of each arm (P, S, N) from the pool seed / offset / size only, exact numbers.
- A4 escalate to the Director if any replicate era mean leaves the M532 range, changes sign, or if the arm SDs say the spread is driven by one choice by a factor above 2 (that decides which the next wording names); stop on control mismatch.
- No payload, config or dashboard change in this milestone; a wording follow-up (the M533 statement names "slow-pool draws and seeds") only if the Director rules the attribution is clear enough to state.

## 4. Language
"spread across slow-pool draws" / "across emulation seeds" / "across pool sizes", "emulated sampling sensitivity, not a causal cadence effect"; never robust / confirmed / no cadence effect; min / max are descriptive, not an interval.

## 5. Gates
py_compile, script run once in the background (about 25 min per 11 replicates at 4 workers; about 1.5 h in total), A1-A4, CHANGELOG M534 (spec SHA-256 before the run, result hash, audit, decision), PR. New script `analyses/M534_pool_seed_size.py`.
