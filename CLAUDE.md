# X-Trail T33 e-POWER study — standing rules for Claude Code

Longitudinal OBD-II telemetry study of a Nissan X-Trail T33 e-POWER (FWD). Thesis: the HV battery is a power
buffer, not an energy reservoir. Target venues: Applied Energy / IEEE TVT. Language: technical/scientific, precise.
Owner: Andrii. Detail lives in `docs/` (load on demand, do not read everything at session start).

## First actions each session
1. `python tools/state.py` and read `STATE.md` (CHANGELOG head, drive_master rows/MD5, key counts). Disk is ground
   truth; memory, chat history and earlier summaries are frequently stale.
2. Do NOT read `CHANGELOG.md` (1+ MB), `xtrail_summary.jsx` (~11.5k lines), `compute_summary_arrays.py` (~17.8k lines)
   or any raw CSV in full. Use `grep -n`, `head`, `sed -n 'a,bp'`, or `docs/script_index.md`.
3. Deterministic work is done by scripts. Never re-type a number that a script can write; never quote a figure from
   memory. Every reported figure comes from a JSON/CSV written by a script this session, with its provenance.

## Layout
Flat working tree (scripts assume it): scripts, `drive_master.csv`, `summary_*.json`, `xtrail_summary.jsx`,
`build_html.js` at repo root. Raw drive CSVs in `raw/` (set `export XT_RAW_DIR=$PWD/raw`; see `project_paths.py`).
New tooling only under `tools/`. Do not reorganise the tree before the reproduction test in `MIGRATION.md` passes.

## Integrity rules (do not violate)
- Raw CSVs are read-only. `drive_master.csv` is written only by pipeline scripts, never by hand or by an LLM edit.
  Its MD5 is the corpus anchor: verify before and after every milestone. A hook blocks Edit/Write on these files.
- ML16 freeze/restore is mandatory on every ingestion (16 ML/domain columns restored byte-exact, 0/16 diffs).
- Never call `run_pipeline()` / `compute_drive_summary_v6.py` CLI for routine ingestion or arrays-only updates: it
  reprocesses every raw file (~440 s) and refits ML columns (drifts vs the published master; see
  `masterRefitAudit.json`). Use it only for the clean-room audit (`master_refit_audit.py`).
  Arrays-only updates use the additive-splice pattern: compute only the changed key, deep-diff, leaf-level splice.
- `recompute_m119v2=False` by default (~11 min); `recompute_energy_mc=True` every ingestion.
- Seasonal data (`compute_seasonal.py`, `cohort_arrays.py`, `refresh_seasonal_kpis.py`, `speed_split.py`,
  `battery_temp_extremes.py`, `refresh_gtr_headline.py`) is recomputed on every ingestion.
- All displayed dashboard figures bind to pipeline-computed `S.*` keys; hardcoded literals are an anti-pattern.
- Canonical exclusion is `ens_outlier_v2` (== `ens_invalid`). Energy rates use canonical-clean eligibility.
- Statistics: calendar day is the resampling cluster; day-clustered percentile bootstrap (seed 42, 4000 draws),
  TOST/MDE, day-blocked cross-validation. Every reported estimate carries a CI and n (drives, days).
- Use appropriate ML/statistical methods to prevent false-negative and false-optimistic results; report method
  disagreement (e.g. Path A vs Path B) instead of tuning to agree.

## Language discipline
- Generator/traction quantities are estimated / reconstructed / model-derived, never "measured".
- TOST "not established" is not "no degradation" (window too short). `CAP_KWH=2.1` and the 20,000 GTC threshold are
  `verified:false`. Three distinct "EFC" quantities exist (FCE / standard EFC / Rainflow-EFC): never conflate.
- The Ukrainian-language companion article is authored manually and is out of scope for code changes.

## CHANGELOG (standing rule)
Every applied change is recorded: newest first, `## M###` prefix, prepended by concatenation (never a
boundary-spanning `str_replace` on a heading). Use `python tools/changelog_draft.py ...`; the model writes only the
rationale line. Large function insertions: two-step marker-then-body pattern.

## Dashboard change rule (standing)
Whenever `xtrail_dashboard.html` is rebuilt with a content change (new/changed figure, KPI, tab or wording; not a
byte-identical rebuild): (1) present it in the session: `SendUserFile` with `display: "render"` on `xtrail_dashboard.html`,
plus one line stating what changed and which `S.*` keys it binds to; (2) commit it and push it to GitHub on the session's
working branch together with the sources (`xtrail_summary.jsx`, `summary_arrays.json`, `cohort_arrays.json`) in the same
commit, so the repo dashboard always matches its sources. Do not open a PR unless Andrii asks.

## Workflow entry points
- Routine ingestion: skill `ingest-drive` (runs `python tools/run_ingest.py`; stops on any failed gate).
- New analysis / method change: skill `new-analysis` (pre-registered spec, blind audit, Director decision).
- Article claims: no register (retired M301). A figure entering the article needs an Opus audit and Andrii's explicit sign-off, recorded in the CHANGELOG entry.
- Release gate (authoritative, clean environment): `python release_check.py`.
- jsdom validation needs `node_modules` (`npm ci`); wait a full 300 ms per tab before targeting content.

## Models and agents (token discipline)
Default main session: Sonnet. Subagents (`.claude/agents/`): `data-worker` (Haiku: run scripts, inventory, route
failures; NO code edits, NO gate bypass), `analytical-auditor` (Sonnet: blind reproduction, method review),
`research-director` (Opus: methodology, interpretation, go/no-go on figures). Subagents cannot spawn subagents;
the main session dispatches all of them. Agents exchange JSON briefs (<2 KB), never prose summaries of numbers.
Escalate: any new headline figure or method change -> blind audit; any figure entering the article -> Opus audit
plus Andrii's sign-off recorded in the CHANGELOG entry.

### Effort by role and task type (set per dispatch, escalate on a trigger, not a hunch)
| Work | Model / effort | Notes |
|---|---|---|
| Run scripts, inventory, MD5/row-count checks, log triage | `data-worker` Haiku, low | Deterministic; no interpretation, no code edits. |
| Tooling, tests, ingestion code, routine fixes | Sonnet main, medium | Read real signatures with grep first; known-answer test for new estimators. |
| Blind reproduction and method review | `analytical-auditor` Sonnet, high (Opus for article-bound/thesis-level) | Independence matters more than speed; give claim + data path only. |
| Methodology, go/no-go on a figure, article claims | `research-director` Opus, high | Compact JSON briefs only; needs Andrii sign-off for article figures. |

Escalation triggers: a flag in `delta_report.json`, a new headline figure, a method change, a KPI outside its previous CI,
or a failed gate that is not a plain environment error. No trigger -> stay at the cheap tier. Effort never replaces the
gates (script-written numbers, blind reproduction, Director decision). Each dispatch states scope and a stop condition
(e.g. "resampling unit and leakage only" vs "full method review") and returns a JSON brief (<2 KB).

## Owner decisions
- 2026-09-29 (Andrii): the CSVs in `raw/` are treated as the original raw data. 335/457 differ from `raw_manifest.json`
  sha256/normHash (row counts all match); this is accepted by owner decision, not verified. Do not "fix" raw files or the
  manifest; report the mismatch as a disclosed limitation. `tools/verify_import.py` (full mode) will keep reporting it.

## Open items (verify against CHANGELOG/disk before acting)
- Clean-room raw->master rebuild is an OPEN item (published master differs from a fresh rebuild in ML columns).
- F02 (raw-archive byte identity) blocked: requires an unavailable raw archive.
- `recon_engine.py` battery-current sign convention: confirm resolution in CHANGELOG (M258+); GTR headline must
  match `fuel_recon_master.csv` regenerated by `fuel_recon.py --all`.
- Bring-forward: `assemble()` in `m119v2_model.py` methodology text; `corpus_manifest._classify` e4orce bug.
- Article: three-way EFC disambiguation; stationary-start ratio rests on 7 events (Wilson CI).
