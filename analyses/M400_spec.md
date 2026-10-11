# M400 spec (Rev 1): dissipation-event detectors on the full time grid (audit N01-N03)

Status: Rev 1, written before any edit. Origin: deep audit 2026-10-11 (N01, N02, N03), feasibility register `analyses/audit_feasibility_2026-10-11/FEASIBILITY.md`, Director triage 6b ("N01-N03 NOW as a tooling fix with known-answer tests and an output diff; not MC, not article-bound").
Branch `claude/next-milestone` restarted from `main` (f9808cc, M399). Report-only monitor: never stops an ingestion, never touches the master or the payload. `drive_master.csv` MD5 `64dfd0cbff3db404d9b83e180f777525` unchanged; `summary_arrays.json` unchanged.

## Facts read from disk (2026-10-11)
- `tools/dissipation_events.py::detect` drops rows with a missing needed channel (`g.dropna(subset=...)`) BEFORE run detection: two runs separated by missing seconds become one run (N01); `dur_s` counts rows, not seconds; the slope uses `np.arange(n)` as x.
- `t0_s` is measured from `d.index[0]`, the first row that survives that detector's own dropna: PUB (rpm, boost, soc) and FUEL (rpm, fuel, thr, soc) get different time origins, so `overlaps()` compares unequal clocks (N02).
- PUB uses `d['load'].fillna(0) < LOAD_PUB` although `load` is a required channel: an unknown calculated load is classified as low load (N03).
- The 1 s grid is built by `grid_from_csv_bytes` (mean per wall-clock second, forward fill of at most 3 s) and already carries NaN rows for longer gaps.
- Audit note: contiguous, fully observed masks reproduce the stored event totals, so these are edge-case defects; the size of the change on the real corpus is measured (below), not assumed.

## Changes
1. `detect()` works on the full grid: `observed` = all needed channels notna in that second; the event mask is `observed & condition`; a run is a run of consecutive grid seconds, so an unobserved second ends it. `dur_s` = grid seconds (= timestamp difference on a 1 s grid). The rpm slope regresses on elapsed seconds from the event start (timestamps), not on row numbers.
2. One drive clock: `t0_s` = seconds from the first row of the grid `g` (the same origin for PUB and FUEL); events also store `end_s` (= `t0_s + dur_s`, exclusive). `overlaps()` therefore compares equal clocks.
3. PUB requires an observed calculated load; unknown load never classifies as low load. `unknown_coverage(g, kind)` returns the grid seconds, observed seconds and unknown seconds per detector; the monitor record stores it (`grid_s`, `unknown_s`) and the summary totals it ("unknown-state coverage").
4. `DETECTOR_VERSION = 2`. Monitor records and the state carry `detector_version`. A state without version 2 is a legacy state: the monitor rebuilds the baseline from the whole corpus (bootstrap path, no flags) and stores `detector_change` = per-detector event/sustained counts and drives changed, legacy vs new (script-written from the two states). The monitor stays report-only; thresholds unchanged and not tuned.
5. Known-answer tests (`tests/synthetic/test_dissipation_events_m400.py`, in CI, each fails on the pre-fix code): N01 two 6 s runs separated by 20 missing seconds give no sustained event (old: one sustained 12 s event) and an irregular-timestamp slope is computed per second; N02 PUB with its first 10 s of `boost` missing and FUEL report the same `t0_s` and overlap; N03 nine unknown load seconds inside a 10 s motored segment give no PUB event and are reported as unknown coverage; legacy-state rebuild; existing M394 tests unchanged and green.

## Acceptance
- `drive_master.csv` MD5 and `summary_arrays.json` unchanged (the monitor writes only `analyses/dissipation_monitor.json`).
- New tests fail on the pre-fix `dissipation_events.py` and pass after; `test_dissipation_monitor.py` green; `python release_check.py` green; all CI unit tests green (Windows-only `test_plausibility_gate` excepted).
- CHANGELOG `M400` entry via `tools/changelog_draft.py` lists the affected-output differences (counts) and states that the monitor remains report-only; no dashboard change (no render).

## Out of scope
N04-N08 (next milestone), F06, capacity (M399a / capacity v4).
