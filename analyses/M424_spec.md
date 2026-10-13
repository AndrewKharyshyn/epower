# M424 spec (Rev 0): process pool for the seasonal regeneration (speed-up 1 of the M422 profile)

Status: tooling milestone; no figure changes. Origin: M422 profile (`analyses/M422_ingestion_rehearsal_2026-10-12.md`): `refresh_raw_seasonal` (`tools/regen_seasonal_raw.py --splice`) is 25 % of an ingestion (1,020 s) and consists of 60 independent computations (4 cohort subsets x category_B and 14 chart builders), run one after another. Owner order: exposureBasis, then speed-ups.

## Change
The 60 (cohort, chart) tasks are pure functions of their cohort subset and the loaders; they now run in a `ProcessPoolExecutor` (`--workers N`, `XT_WORKERS`, default min(6, cpus/2); N = 1 is the former serial path inside the parent process). Longest tasks first (prior timings from `analyses/M341_check.json`, default 60 s). The parent only collects results, applies the M384 cache rules, writes the cache and assembles `res` (timings, `filesLoaded`, `builderLoads` summed from the per-task load counts); workers never write. The parity guard, conservation, cutpoint scan and splice are untouched.

## Evidence (analyses/M424_pool_parity.json)
574-drive rehearsal state, `--splice --no-cache`, same starting payload: 6 workers 305 s, 1 worker 999 s (3.3x); all leaves of the two payloads compared: identical except the two `generatedAt` stamps. The floor of the makespan is the longest task (125 s).

## Tests
`tests/synthetic/test_regen_seasonal_pool.py` (worker-count rule; cohorts partition the master; three tasks of the below-support cohort give identical canonical JSON and load counts in the parent process and in pool workers; source dispatch; CI list; the recorded parity evidence).

## Limits
Speed-up measured on one machine (12 logical CPUs, 31 GB); memory per worker was not a constraint (each worker streams frames per drive); on a machine with fewer CPUs the default shrinks (cpus/2). Python 3.12.10, not the pinned 3.11.
