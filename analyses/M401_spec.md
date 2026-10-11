# M401 spec (Rev 1): engineering hygiene from the 2026-10-11 audits (N04, N06 wording, N07, D4, D7, D11; D10 verified, no change)

Status: Rev 1, written before any edit. Origin: `analyses/audit_feasibility_2026-10-11/FEASIBILITY.md` (phase P1 remainder). Branch `claude/next-milestone` restarted from `main` (1433772, M400).
No figure, estimator, CI, master column or payload value changes: `drive_master.csv` MD5 `64dfd0cbff3db404d9b83e180f777525` and `summary_arrays.json` unchanged; no dashboard change.

## Facts read from disk (2026-10-11)
- N04: `tools/day_bootstrap.py::ratio_boot_ci` uses `np.bincount(weights=...)`; a NaN in the numerator or denominator propagates to the whole day and the draw (pandas `sum` used to skip NaN per column); a zero total denominator in a draw gives inf/NaN silently; an empty frame is not handled. Callers: `tools/gtr_closure_diag.py`, `tools/perf_baseline.py`; both pass finite data today.
- N06: `tools/recal_gate.py:30` (`_EFF`) says "the effective hard level about 1/(n_eff+1)" and `tests/synthetic/test_recal_gate.py:74` asserts "effective hard level"; the text is not in the payload, dashboard or config. Overlapping windows give a rank resolution, not a calibrated false-alarm rate.
- N07: `tests/synthetic/test_ambient_provenance.py:24` asserts the cohort sum equals 489 (corpus is 554) and fails; `tests/synthetic/test_eligibility.py:42` fails on stale M375-era counts; neither is in the CI test list.
- D4: odometer anomalies on the 554-drive master (script-found, fixed rules in `tools/odometer_check.py`): rows `20260813_144601` (odo_start repeats an earlier value), `20260816_124817` and `20260816_144003` (odometer 0 -> 63.8 -> 172.2 while neighbours sit near 6,736), `20260816_165356` (forward jump after the reset), `20260906_122920` (odo_end below odo_start; already `distance_source = trip_meter`). Master `distance_km` equals `odo_end - odo_start` by construction. Positive gaps between drives of up to 39 km are unlogged driving, not anomalies. The Overview KPI (total logged km / dash ODO) is the owner's 2026-10-03 rule and does not change.
- D10: `eligibility.py::_true` maps NaN to False and STOPs on a flag disagreement, so the naive `==` scenario of the audit does not occur in the pipeline; no code change.
- D7: 195 text-mode `open`/`read_text`/`write_text` calls without `encoding=` in 74 files (AST count); `tools/run_ingest.py` already sets `PYTHONUTF8=1` for stages.
- D11: `.gitignore` has only `*.pkl`; 68 untracked `*.log` files at the root.

## Changes
1. N04: `ratio_boot_ci(..., nan="raise")`: non-finite numerator/denominator values raise `ValueError` naming the column and count (`nan="skipna"` reproduces the former per-column pandas semantics, explicit opt-in); an empty frame raises; draws with a zero total denominator are excluded and counted (`ratio_boot_ci` still returns the 2-element CI; `ratio_boot_ci_detail` returns CI + `n_draws_used`); all draws invalid returns `[nan, nan]`. Same rng stream, estimator, seed and draw count: outputs on finite data are bit-identical (existing `test_day_bootstrap` stays green).
2. N06: wording "rank resolution ..., not a calibrated false-alarm rate" in `recal_gate._EFF` and its test; language-gate rule `M401-N06-hardlevel` for the old phrase.
3. N07: both tests use dynamic support assertions (counts read from the payload / master) and are added to the CI list if they run in under a few seconds, else documented as local-only.
4. D4: `tools/odometer_check.py` (fixed rules R1 within-drive decrease, R2 backward step > 0.5 km, R3 start < 0.5 x running maximum, R4 forward jump > 500 km), ledger `odometer_anomalies.json` (file, rules fired, reason, distance treatment), `release_check.py` step: every detected anomaly must be recorded with the same rules, stale entries are reported. Known-answer test `tests/synthetic/test_odometer_check.py`. No master edit; `distance_source` mislabelling is recorded in the ledger, not fixed in the master (the master is written by pipeline scripts only).
5. D7: `tests/synthetic/test_encoding_guard.py` + `tools/encoding_baseline.json`: per-file counts of un-encoded text-mode I/O may not increase (ratchet); the existing 195 are not rewritten in this milestone.
6. D11: `.gitignore` gets `*.log`.

## Acceptance
- MD5 and payload unchanged; new tests fail on the pre-fix code where applicable (N04 NaN/zero/empty, N06 wording, odometer ledger missing an anomaly) and pass after; CI unit list green (Windows-only `test_plausibility_gate` excepted); `python release_check.py` green; CHANGELOG `M401`.

## Out of scope
N05 fingerprint, F20 atomic release, F11 replay (reliability milestone); F06; capacity (M399a / v4); D5/D6/D12 (deferred); rewriting the 195 un-encoded calls.
