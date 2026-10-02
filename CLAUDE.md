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

## Session ledgers (standing, owner decision 2026-09-30)
On EVERY ingestion the new drives must appear in the dashboard section "Sessions (grouped by phase)": `summary_config.json`
`sessionGroups` (that section) and `sessions` (the detailed per-day panel) get one row per new calendar day. They are hand-curated
ledgers that nothing else extends, so this is enforced: stage `extend_session_ledgers` (`tools/extend_session_ledgers.py`, numbers
computed from the master, never typed) runs in `tools/ingest_stages.json`, and `release_check.py` fails if the newest drive date is
not covered or a ledger row disagrees with the master (`sessionLedgerAudit`). An ingestion is not complete until the new days show in
that section (verify in the rebuilt dashboard). The historical Sep 04-11 gap was backfilled in M313 (`--from-date` backfills any uncovered window).

## Language gate (standing, M326)
Forbidden/required wording lives in `language_gate.py` (RULES) and is enforced by `semantic_gate.py` check A2 on the rendered tab dumps, payload string values, `summary_config.json` and `xtrail_summary.jsx` strings (comments WARN). Matching is normalised (NFKC, punctuation collapsed, plural-safe, stripped form, context rules). Every wording fix adds the OLD wording as a rule with its ledger id; a wave (spec `analyses/M326_spec.md`) never renames payload keys.

## Dashboard change rule (standing)
Whenever `xtrail_dashboard.html` is rebuilt with a content change (new/changed figure, KPI, tab or wording; not a
byte-identical rebuild): (1) present it in the session: `SendUserFile` with `display: "render"` on `xtrail_dashboard.html`,
plus one line stating what changed and which `S.*` keys it binds to; (2) commit it and push it to GitHub on the session's
working branch together with the sources (`xtrail_summary.jsx`, `summary_arrays.json`, `cohort_arrays.json`) in the same
commit, so the repo dashboard always matches its sources. The agent opens the PR itself (see Version control); Andrii does not.

## Version control (standing)
- `main` = last validated state only: `release_check.py` green, CHANGELOG `M###` entry present, commit tagged `M###`.
- One short-lived branch per milestone (ingestion batch, method change, tooling change). The session's assigned branch
  (`claude/...`) is that branch; push only there, never to another branch without Andrii's permission.
- Only one ingestion branch open at a time: `drive_master.csv`/`summary_*.json` conflict across parallel ingestions.
  Merge before starting the next.
- The agent opens the pull request itself (owner decision 2026-09-30: Andrii neither opens PRs nor merges; do not hand him a compare
  link or ask him to click) when the milestone is complete, the release gate is green, the CHANGELOG entry is written and any required
  audit/Director decision is done. Never for work in progress or a red gate. If no tool can open the PR (no `gh`, no GitHub connector,
  Chrome extension not connected), say so and name what is missing; do not stop at a compare URL, and do not use stored credentials or
  tokens to call the API. Use a merge commit (not squash) so `M###` history survives. PR body follows the repo template if one exists.
- Merging is done by the agent, not by Andrii (owner decision 2026-09-30). Merge only when ALL hold on the PR's current head: every CI
  check green (no pending/red; `release-gate` included), the PR is not a draft and has no merge conflict, no open review thread
  waiting on the agent, the CHANGELOG `M###` entry exists and any required blind audit / Director decision is recorded. Use
  `merge_method: merge` with `expectedHeadSha`. Never merge on red or pending CI, never force-push or bypass a gate; if a condition
  fails, fix it or tell Andrii what blocks. After the merge, restart the branch from `main` and push (see the rule below).
- After a PR is merged, restart the branch from the latest `main` (`git fetch origin main && git checkout -B <branch> origin/main`);
  never stack new commits on merged history.

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
- 2026-09-29 (Andrii), superseding the earlier same-day decision "raw/ treated as original": open integrity item **F03
  (raw content provenance)**, linked to F02. 335/457 files in `raw/` (at that time; 333/489 on the current corpus) fail `raw_manifest.json` sha256 AND normHash (row counts
  match); a stratified re-analysis showed hash-matching files reproduce the published master exactly (0 cells) while
  hash-failing files do not (442 cells in 15 sampled). (The same-day statement "no other originals exist" is superseded by the
  2026-10-02 entry below.)
  Reference of record for published figures = the published master/arrays (`drive_master.csv` MD5 `0bcfc400...`);
  a fresh rebuild from today's `raw/` is a **provenance-sensitivity analysis**, not a correction. Do not switch silently.
- Wording (Director, 2026-09-29; counts and originals clause revised 2026-10-02): never "reproducible from raw data" for
  raw-pass keys. Disclose: "published values derived from the M299 corpus; 333/489 archived raw copies in `raw/` do not match
  recorded hashes (lower-precision re-exports); sha256-verified originals exist and are consistent with the published per-drive
  raw-derived values (see 2026-10-02 entry)". Never "proven", never "corrections". Call fresh-rebuild deltas "provenance sensitivity", never "corrections"/"errors". No new article figure from
  raw-pass keys until F03 is resolved or Andrii signs off a disclosed dual report. A delta that moves a figure outside its CI or
  flips a TOST/decision outcome escalates to the Director.
- 2026-10-02 (Andrii, after Director ruling "revise" and a blind audit): **originals recovered**. A read-only sweep of the
  Investigation folder (loose CSVs + 43 ZIPs; `analyses/audit_v3_triage/zip_sweep_report.json`) found a byte-identical original
  (sha256 = `raw_manifest.json`) for all 333 hash-failing canonical files; copies are in `<Investigation>/originals_recovered/`
  (outside the repo, produced by `tools/originals_recover.py`; do not place them in `raw/`; inventory in `originals_manifest.json`, `archiveOfRecord:false`, generated by `tools/originals_manifest.py`, not a re-anchoring). The `raw/` copies of these files are
  lower-precision re-exports (e.g. HV current -2.5999 -> -3). Evidence (`analyses/F03_originals/`, spec pre-registered): rebuild
  from the originals gives 161/186 identical columns vs 69/186 from `raw/`; 0 raw-derived non-ML columns drift on the 333 swapped
  drives; the 25 remaining drifted columns are ML/refit outputs and drift identically on the 43 hash-verified new drives, are
  deterministic run to run and identical under Python 3.11.15 and 3.12 (ML16 frozen historic fit; not raw content). Blind audit:
  0 mismatches original-vs-published (41 drives, vs both current master and 0bcfc400); `raw/` copies mismatch on 36/41 (the 5
  matches differ only in GPS cells, i.e. ~12% of the 333 may be value-neutral). Allowed wording: "consistent with the published
  raw-derived per-drive values deriving from the sha256-verified originals; the archived `raw/` copies of 333 files are
  lower-precision re-exports". NOT yet decided and NOT to be done silently: re-anchoring (originals as a second sha256-manifested
  archive is the preferred path; swapping `raw/` only by Andrii's separate decision after a no-new-drive arrays control build with
  deltas inside CI). Until then F03 stays open; the dashboard F03 disclosure uses the allowed wording from M325 (generated from `f03_provenance.json`, canonical counts 333/489); article wording stays unchanged (the Ukrainian companion is out of scope); and no new article figure from
  raw-derived keys without the Opus audit and Andrii's sign-off. F03 ledger rows (F01, F01.r2, C3.18, C14.9, C14.12, E-N1, p1.6)
  are re-ruled by the Director per row.
- 2026-10-02 (Andrii): the GTR flow diagram (Sankey) in section 4b stays HIDDEN behind its reveal button (`GtrFlowGate`) until the GTR repair (M329) closes the generator branches; Compare mode must not bypass the gate (planned in the Compare/GTR-gate milestone). Do not show it by default before that.
- 2026-10-01/02 (Andrii), external audit v3 triage (`analyses/audit_v3_triage/`; ledger of 1,214 rows, not committed): single
  top-level Fuel tab holds all fuel charts (the code's host tab is named "charts"); retire UNUSED files only (`soc_patterns.json`,
  `f01_perdrive_correction.csv`, `highspeed_130_runlength_check.csv` are kept); fuel cost (FUEL-13) rejected; GateA2 (M308
  plausibility gate: per-channel resolution check + `signal_representation.json`, flag-only, never repairs) is GO after M320-M322
  and before the next ingestion, needs spec + Sonnet audit. The logger is Car Scanner ELM OBD2: fuel rate/counter are
  app-calculated, so say "logged/app-calculated", never "measured". The OEM Article-10 rated capacity (5 Ah) vs `CAP_KWH=2.1`
  is a lead only: do not change `CAP_KWH` silently. Audit figures are known-answer targets, never typed into the repo.
- Ingesting new drives (new phone exports) is allowed under: sha256/normHash of each new file recorded at ingestion and an
  off-chat backup kept; 0/16 ML diffs and 0 pre-existing-row diffs gates; arrays step attributed via a no-new-drive control build
  (or splice) so provenance drift is not mixed into new-data changes; post-ingest arrays labelled "not M299-reproducible".
- Do not modify raw files or `raw_manifest.json` records; `tools/verify_import.py` (full mode) keeps reporting the mismatch.

## Open items (verify against CHANGELOG/disk before acting)
- Clean-room raw->master rebuild is an OPEN item (published master differs from a fresh rebuild in ML columns).
- F02 (raw-archive byte identity): the originals for the 333 hash-failing files now exist outside `raw/` (see Owner decisions
  2026-10-02), so F02 is no longer blocked for those; the 156 hash-passing files already match. F03 (raw content provenance) stays
  open until Andrii decides on re-anchoring. Audit v3 follow-up plan: `analyses/audit_v3_triage/HANDOFF.md` (milestone numbers there
  are proposals, renumber from the CHANGELOG head).
- `recon_engine.py` battery-current sign convention: confirm resolution in CHANGELOG (M258+); GTR headline must
  match `fuel_recon_master.csv` regenerated by `fuel_recon.py --all`.
- `generatorTractionRecon.speedSplit` has no auto-splice: `speed_split.py` only writes `speed_split.json`; ingestion carries the previous block forward (stale until a splice script exists).
- Bring-forward: `assemble()` in `m119v2_model.py` methodology text; `corpus_manifest._classify` e4orce bug.
- Article: three-way EFC disambiguation; stationary-start ratio rests on 7 events (Wilson CI).
