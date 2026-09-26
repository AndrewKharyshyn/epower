---
name: ingest-drive
description: Routine ingestion of new drive CSVs into the corpus with the full validation chain. Use when new raw drive files are added to raw/.
---

Preconditions: new CSVs are in `raw/` (do not modify existing files). `export XT_RAW_DIR=$PWD/raw`.

1. Dispatch `data-worker`: `python tools/state.py` then `python tools/run_ingest.py --dry-run`; confirm the list of new
   files vs `raw_manifest.json` (typed roles; comparison/e4ORCE files are never canonical).
2. Dispatch `data-worker`: `python tools/run_ingest.py` (stages in `tools/ingest_stages.json`). It stops on the first
   failed gate and writes `runs/<ts>/failure.json`. Do not retry with changed parameters.
3. If a stage is `not_implemented` (first use): implement `tools/ingest_core.py` from `docs/workflow-and-tools.md`
   protocol steps 1-5 by reading the real function signatures with grep (Sonnet task). Then rerun.
4. `python tools/data_health.py` and `python tools/delta_report.py` (Haiku). Read `delta_report.json`.
5. If `delta_report.json` has flags (KPI outside previous CI, effect-size or cumulative drift, changed method, new gate
   failure): dispatch `analytical-auditor` (blind) then `research-director` with the JSON briefs. Otherwise no audit.
6. `python tools/changelog_draft.py --id M### --title "..." --rationale "..."` (prepends by concatenation). Then
   `python tools/state.py`, `python release_check.py`, commit and tag `M###`.
7. Report to Andrii: what changed (files), gate results, flags. No number is quoted unless taken from a script output.
