# M746 spec: optional, non-blocking ingestion stage for the MyNISSAN cloud auxiliary tools (tooling only, report-only)

Rev 1. Committed BEFORE any code. Author: main session (Sonnet). Number taken after checking the CHANGELOG head (M745, parallel session), open PRs and the remote branch list. Next step: Director review of this spec, then wrapper + tests, then audit of the stage contract, Director decision. No analysis, estimator or figure is added; nothing published changes.

## 0. Why
Owner (2026-11-21): the cloud export is auxiliary; exports arrive "ideally with each ingestion, but NOT guaranteed"; the importer must be an optional, non-blocking, idempotent stage; coverage is reported per drive as "no cloud data yet", never as a gap in the OBD study. Since then six cloud tools exist and are run by hand (M729 coverage, M730 clock offset, M733 tyre, M734 thermal, M737 grade G0, M739 unlogged exposure; plus the importer M729). `docs/open_items.md` tells the operator to rerun M737 and M739 "at each ingestion". Hand reruns are the failure mode this repo's rules warn about (an ingestion is not complete until every refresh that is owed has run). The stage list has no optional stage (`tools/ingest_stages.json`: "A stage failing stops the run").

## 1. Constraints
- The stage MUST NOT be able to stop or fail an ingestion: once the wrapper has started, its exit code is 0; every tool failure is recorded, not raised. A missing store, a missing export, an unreadable ZIP, a tool timeout give a recorded `skipped` / `failed` row and exit 0.
- Read-only on `drive_master.csv`, `raw/`, `summary_*.json`, payload keys, dashboard, frozen winter files (M726). The stage writes only the `analyses/M7xx_*` outputs these tools already write plus one new status file `analyses/cloud_stage_status.json`. The wrapper asserts the `drive_master.csv` MD5 before and after each tool; a change aborts the remaining cloud tools and is recorded (should be impossible).
- It runs after the master and arrays are final for the ingestion (the drive windows are the new ones) and before `release_check`; `release_check` does NOT read its outputs and does not fail on them (optional by construction). Placed immediately before `release_identity` unless the Director review finds a reason otherwise.
- Public repository: the tools already write aggregates (and per-drive-day tables already committed); the stage adds no new output class.
- Environment: store from `XT_CLOUD_STORE` (else the tool default); export folder from `XT_CLOUD_EXPORTS` if set (importer `--auto`), else import is skipped. No path is guessed.
- Idempotent and deterministic: a rerun with unchanged inputs gives byte-identical outputs (all tools seed 42, 4000 draws). The status file records input fingerprints (store manifest sha256, master MD5, raw manifest sha256); a tool whose fingerprint is unchanged is `skipped_up_to_date` unless `--force`.

## 2. Design
`tools/cloud_stage.py`: ordered list of (id, command, timeout, outputs): import (only when `XT_CLOUD_EXPORTS` is set and holds ZIPs), coverage, clock_offset, tyre, thermal, grade, unlogged. Each tool runs in a subprocess with a per-tool timeout (default 20 min, `--timeout`). Status record per tool: `status` in {ok, skipped_no_store, skipped_no_new_input, skipped_up_to_date, failed, timeout}, `seconds`, `exit_code`, output sha256 list, first 300 characters of stderr on failure. The status file also carries the importer's coverage counts (drives with cloud data / drives in master), worded "no cloud data yet" for uncovered drives, never "gap".
Ingestion stage entry: id `cloud_auxiliary`, `verified: false` until it has run in a full ingestion, cmd `python3 tools/cloud_stage.py`.

## 3. Tests (known-answer, `tests/synthetic/`, one CI list line)
(a) no store: exit 0, all `skipped_no_store`; (b) a planted failing tool (exit 1) and a planted timeout: recorded, later tools still run, exit 0; (c) unchanged fingerprints: second run skips as up to date, outputs untouched (sha256); (d) a planted change of `drive_master.csv` between tools aborts the rest and records it; (e) the stage entry in `tools/ingest_stages.json` is before `release_identity`, after the last arrays/payload stage, and the existing ingest-order tests stay green; (f) the status text never uses the word "gap" for uncovered drives (language gate). The six tools keep their existing tests.

## 4. Acceptance and falsification
Accepted when the tests pass, CI is green, a dry run on this machine's real store finishes with exit 0 and a status record per tool, and the measured total time is reported (if it exceeds 25 minutes the Director decides whether the slow tools, grade and unlogged, become opt-in via `XT_CLOUD_SLOW=1`). Falsified if any planted failure stops the wrapper or an unchanged rerun alters an output.

## 5. Not in scope
No new analysis. No release_check dependency. No dashboard binding. No change to any tool's estimator. `verified` stays false until a full ingestion has run the stage; the first real ingestion run is the check (recorded in the CHANGELOG then). The ingestion session that is active in parallel is not touched: the stage entry lands by PR like any other change and the ingestion skill stays unchanged.

## 6. Questions for the Director
(a) Is placement before `release_identity` right, or should the stage run last so a cloud tool can never delay a gate? (b) Should the slow tools be opt-in from the start (about 11 minutes of the total)? (c) Is "exit 0 always" acceptable for the wrapper, given the repo rule that a failing stage stops the run, or may a crash of the wrapper itself (not a tool) stop the run? (d) Is the fingerprint-skip safe for tools that read `raw/` (clock offset, thermal) when raw changes but the store and master do not?
