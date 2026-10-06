# Migration: Claude Project "Nissan E-Power Analysis" -> Claude Code repo

Built 2026-09-25 from the Project (89 docs, 470 files) plus two files you uploaded. Read this first.

## 1. What this bundle contains
| Item | Status |
|---|---|
| `CLAUDE.md`, `.claude/agents/` (3), `.claude/skills/` (3), `.claude/settings.json` (path-guard hook) | ready |
| `tools/` state, verify_import, run_ingest (+ stage list), data_health, delta_report, changelog_draft, script_index, guard_paths | tested on the real data |
| `docs/` findings-and-methods, workflow-and-tools, overview (from Claude memory), script_index | ready |
| Byte-exact copies of: `CHANGELOG.md`, `xtrail_summary.jsx` (your upload), `drive_master.csv`, `compute_summary_arrays.py`, `summary_config.json`, `summary_arrays.json` | included, verified |
| `tools/ingest_core.py` | STUB (fails loudly, exit 3): fill in the first Code session (section 5) |
| Remaining ~80 scripts/JSON/CSV and the 470 raw CSVs | NOT included: see section 3 |

## 2. Findings while exporting (act on these)
- `CHANGELOG.md` and `xtrail_summary.jsx` were missing from Project Knowledge (you supplied them). `xtrail_dashboard.html` is also absent (rebuilt by `node build_html.js`).
- Memory notes were stale versus disk: memory says 410 drives / M285c; disk is 446 drives, CHANGELOG head M294-M299, master MD5 `0bcfc400...` (matches CHANGELOG). The M247 note "run_pipeline does not forward raw_dir" is fixed in code (P0-2). The docs here mark such items.
- Two `determinism_check.json` versions exist in the Project (2026-09-05 and 2026-09-25); use the newest.
- Reading small text files through chat returns them inline (token-expensive, not verified byte-for-byte), so they were not transcribed. Only files that landed on disk byte-exact are included.
- `raw_manifest.json` lists a sha256 for every raw file, so `tools/verify_import.py` can prove the raw data arrived intact.

## 3. Bringing over the rest (recommended: from your own computer, not through chat)
You already download every session's output, so the newest copy of each script is on your computer. Copy them into the repo root (flat layout; do not reorganise yet). Files still needed are listed by `python tools/verify_import.py` under `missing_required`.
Raw CSVs (about 470 files; several MB each, on the order of a GB in total: measure with `du -sh`) go in `raw/`; keep names as they are (Project Knowledge stores `YYYYMMDD HHMMSS.csv`, the manifest uses underscores; verify_import accepts both).
`export XT_RAW_DIR=$PWD/raw` (see `project_paths.py`).
Alternative: if you can attach files in a session, I can place them in the repo byte-exact and verify against the manifest.

## 4. Where it runs (several machines, phone)
- Recommended: a PRIVATE GitHub repository. Claude Code on the web (claude.ai/code) runs sessions in a cloud container attached to that repo and is reachable from any browser and the Claude mobile app, so Android works for starting, steering and reviewing sessions; git is the sync. Local Claude Code CLI on any machine works with the same repo (push/pull).
- Keep the repo Linux-first (Windows: use WSL). Pin versions from `requirements.pinned.txt`; `npm ci` from `package-lock.json`.
- Raw data size: choose one (check current GitHub limits before deciding): (a) commit `raw/*.csv` with Git LFS (uncomment the line in `.gitattributes`; watch storage/bandwidth quotas), (b) commit normally if the total and each file are within repository limits, (c) keep raw CSVs in cloud storage and download in the session using `raw_manifest.json` to verify. Derived data (`drive_master.csv`, JSONs) is small and belongs in git.
- Never commit secrets; the repo contains no credentials.

## 5. First Code session checklist (in order)
1. `pip install -r requirements.pinned.txt`, `npm ci`.
2. `python tools/verify_import.py --expect-master-md5 0bcfc400d8ce2a0b15cdc7f3ddd8efff` -> must report OK (raw sha256 included).
3. Reproduction: `python determinism_check.py` and `python ml16_determinism_check.py` (0/16 ML diffs), `python release_check.py` (clean-environment gate). Nothing else proceeds until these pass or differences are explained.
4. `python tools/script_index.py`, `python tools/state.py`, commit ("import from Claude Project, M299").
5. Implement `tools/ingest_core.py` (Sonnet) from protocol steps 1-5 in `docs/workflow-and-tools.md`, reading real signatures with grep. Reconcile the order of `apply_m284_post.sh` / `cohort_arrays.py` in `tools/ingest_stages.json`.
6. Extend `tools/kpi_paths.json` with the headline KPIs (degradation slopes, cell-spread trend, cycle projections). Run `python tools/delta_report.py --commit` to create the baseline.
7. Dry-run the ingest skill on the newest batch; measure tokens per stage; move judgement-free steps into scripts.
8. Add known-answer tests (`tests/synthetic/`) and a clean-rebuild step before submission (see the process design doc, section 11).

## 6. Design reference
Process design (tiers, flows A/B/C, reliability hardening): the "e-POWER Study: Agent and Script Process Design" doc created in chat.


_M301: `claim-check` skill, `tools/claim_check.py` and `docs/claim_register.csv` were retired by Andrii's decision._
