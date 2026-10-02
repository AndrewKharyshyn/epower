# HANDOFF: external audit v3 follow-up (written 2026-10-01 for a fresh session)

Read this first, then CLAUDE.md "First actions" (`python tools/state.py`, read STATE.md). Disk is ground truth; this note can be stale.

## 1. What this is
Andrii received `epower_project_deep_audit_v3_2026-10-01.pdf` (88 printed pages: Fuel-tab addendum F1-F15, continuation C1-C14, original audit pp.1-59; audited release M316). He asked the Director (research-director) to rule on feasibility of EVERY requirement. That is done. Nothing in the pipeline, master, raw files or raw_manifest.json was changed. Everything below lives in `analyses/audit_v3_triage/` (untracked, NOT committed).

PDF: `C:\Users\AndriiKharyshyn\Downloads\X-Trail Investigation\epower_project_deep_audit_v3_2026-10-01.pdf`. Extracted text: `analyses/audit_v3_triage/audit.txt` (4314 lines; `page_map.json` maps printed page label to line range).

## 2. Repo state at handoff (verify!)
- Branch `claude/next-milestone`, HEAD was 5d15f63 (M320 pre-registered spec rev 2). CHANGELOG head M319. drive_master.csv MD5 `bd9d10726bb064d857cf9ff98d2b7338` (489 rows).
- M320 is IN FLIGHT (m119v2_model.py, tools/m320_ladder.py, tests/synthetic/test_m320_ladder.py, STATE.md, state.json modified/untracked). Do not touch; finish and merge M320 first (one open milestone branch at a time).
- UNEXPLAINED: `git status` also showed `summary_arrays.json`, `xtrail_dashboard.html`, `xtrail_summary.jsx` modified; not done by the audit work. Find out what changed them (`git diff --stat`) before any commit.
- New untracked: `analyses/audit_v3_triage/`. Commit it with the first milestone or separately; it is documentation only.

## 3. Owner decisions (Andrii, in chat, 2026-10-01) - record in CHANGELOG at the relevant milestone
- O1 single top-level Fuel tab holds all fuel charts (confirmed). The code's host tab is named "charts"; there is no "Energy" tab.
- O2 retire UNUSED files only; `soc_patterns.json` is KEPT (imported by xtrail_summary.jsx:17, inlined by build_html.js).
- O3 fuel cost (FUEL-13) rejected.
- GateA2 (amend the M308 plausibility gate: resolution check per voltage channel + signal_representation.json): GO, small, flag-only (never repairs), land after M320 merges and before the next ingestion; needs a spec + Sonnet audit.
- ZIP/archive sweep: approved (done, see 4). Unused-file retirement: approved. f01_perdrive_correction.csv: KEEP (M229 evidence). highspeed_130_runlength_check.csv: KEEP until M321 scripts an equivalent.
- Article directions: Andrii does not need to act now (see 7).
- Not yet approved: any CLAUDE.md edit (e.g. "335/457" -> 333/489 from f03_provenance.json). Ask first.

## 4. Key findings that change the plan
1. ORIGINALS EXIST. Read-only sweep (`zip_sweep.py`, `zip_sweep_report.json`): 4,329 CSVs hashed (331 loose + 43 ZIPs in the Investigation folder). All 333 canonical files that fail raw_manifest.json have a BYTE-IDENTICAL original (sha256 = manifest) there (161 in exported_records_full.zip, 143 loose, 29 other ZIPs). The "originals unavailable" premise of F03 is wrong. This likely also explains the 9 coarse-grid voltage files (C01/F02): the originals probably carry the published fine values. NOT yet verified: whether master reproduces from originals, whether originals = what the published values used.
2. LOGGER = Car Scanner ELM OBD2, automatic fuel calculation: fuel rate/counter are app-calculated (air-flow based), not an ECU measurement. Wording "logged/app-calculated", never "measured". FUEL-12 (rate vs counter) = internal consistency of one derivation, not validation; FUEL-06 map partly circular; external check needs fill-up records. Re-rule when the fuel contract spec (M328) is written.
3. ARTICLE-10 TABLE verified against Nissan PDF (https://www-europe.nissan-cdn.net/content/dam/Nissan/nissan_europe/ev-battery-regulation/X-Trail_e-POWER.pdf; rendered copy `nissan_article10_table.png`): summary_config.json officialDisclosure is exact. OEM rated capacity 5 Ah vs repo C-rate basis (CAP_KWH 2.1 kWh / median V ~ 5.85 Ah): 5 Ah x ~359 V ~ 1.8 kWh, ~14% below 2.1. LEAD only; needs a Director spec; do NOT change CAP_KWH silently.
4. Hard defects verified on disk (details in ledger): battery-work floor has no canonical mask (F05); 130+ s record is cumulative not continuous (F06); intake max is a trip mean (F07, plus M319 outage since 2026-08-24); GTR generator branches do not close, 15.94 vs 16.99 kWh/100 km, and Compare bypasses GtrFlowGate (F04/F20); Cold = 2 drives/1 date shows as 0 in seasonalCharts so cohorts sum to 487 (F08); 37 seasonal contracts on a 410-drive basis and 9 on 446 (F03); "410/410 byte-identical" footer contradicts 333/489 (jsx:11622); _HF_LHV 8.9 vs E10 8.58435 kWh/L (C05); chart_registry.json stale and consumed by nothing.
5. Thesis caution: M329 (GTR repair) may move the generator share across 0.5; any "battery majority" wording waits for it (Opus audit + Andrii sign-off).

## 5. Artifacts in analyses/audit_v3_triage/
- `ledger_all.tsv` (1,214 rows) and `ledger/P*.txt` (per-partition sources). Row format: `ID | page | audit.txt line | class | ver | milestone | effort | action`. class = FIX-NOW/SPEC-FIRST/BLOCKED/STALE/DECLINE/BACKLOG/INFO/OWNER; ver = V verified on disk / NV / D disputed / n/a. "CHG:" in action = differs from the first-round ruling.
- `compile_ledger.py`: `python compile_ledger.py 11` re-verifies (0 malformed, 0 duplicate, 88/88 pages, gaps). Run it after any ledger edit.
- `director_brief_v2.md` (rules given to every Director pass), `wave1_digest.md` (cross-findings), `README.md` (summary + addenda), `header_inventory.txt` (raw column presence counts), `appendixE_consumers.txt` (file-consumer scan), `zip_sweep.py`/`zip_sweep_report.json`.
- Useful query: `python -c "import csv;[print(r['id'],r['ln'],r['action']) for r in csv.DictReader(open('ledger_all.tsv',encoding='utf-8'),delimiter='\t') if r['ms'].startswith('M321')]"`
- Totals: FIX-NOW 496, INFO 307, SPEC-FIRST 270, OWNER 39, BACKLOG 34, BLOCKED 26, STALE 23, DECLINE 19. Audit numbers are known-answer TARGETS for scripts; never type them into the repo.

## 6. Plan (Director's order; proposed M-numbers, not yet in CHANGELOG)
0. Finish and merge M320 (do not stack work on it).
1. NEW F03-originals (read-only first): data-worker verifies the 333 originals (sha256 vs manifest; copy to a separate dir, NOT into raw/), then tests whether master/arrays reproduce from them (stratified, as in M305). Director decides; Andrii decides any re-anchoring. Never modify raw/ or raw_manifest.json; the "provenance sensitivity" language stays until he decides. Re-rule BLOCKED/OWNER rows on originals: F01, F01.r2, C3.18, C14.9, C14.12, E-N1, p1.6.
2. NEW GateA2 spec + implementation (before the next ingestion).
3. M321 Records+floor (72 FIX-NOW): F05, F06, F07, Appendix A labels/ties, C04 fields; Sonnet blind reproduction; records-key splice only.
4. M322 wording sweep (241): includes F01 footer from f03_provenance.json, Cold observed counts, "Season"->"Thermal cohort", Article-10 URL/verified label, "Fuel (chem) measured"->logged volume x assumed E10, false "no fuel-flow data" text.
5. M323 Compare/GTR gate + release hardening (103): GtrFlowGate in Compare, accounting table (no Sankey), numeric x, Records statistic identity, parity WARN, chart_registry decision, build manifest.
6. M324 Fuel tab (needs M323; no new estimand): move SocBalancedFuel, ThermalFuelPenalty (renamed association), gated GTR table; C05 single E10 basis with scripted delta; record O1, O3.
7. M325 cell-spread sensitivity + grid table (may simplify after step 1); M326 raw-pass sidecars (never master); M327 regenerate 50 seasonal contracts on 489; M328 fuel contract v1 (fuel_analytics.py; FUEL-01,02,03,04,11,12); M329 GTR repair (Opus blind audit); M330 supported contrasts + FUEL-10; M331 fuel phase 2 (FUEL-05..09,14).
8. Housekeeping (any time after M320): retire unused files after `git ls-files` check + sha256 manifest: `_det1/_det2` (first move test_seasonal t15 to tempdirs), five `*_backup.json`, `m294_patch.py`, `kpi_ci*.py` family, `chart_registry.json` (unless M323 adds a consumer). KEEP apply_m284_post.sh, patch_m284_data.py, m295/m296 (until M327), m297, soc_patterns.json, f01 csv, highspeed csv.
Every milestone: stop on red gate, master MD5 change, isolation diff outside declared keys, or KPI outside previous CI -> Director. Use `tools/changelog_draft.py`; skills `new-analysis` (spec first) and `ingest-drive`.

## 7. Article directions (plain language)
The audit lists ten possible papers (pack-energy ledger, engine-start hazard model, buffer dynamics, thermal response, SoC-balanced fuel, temperature-fuel association, etc.). Andrii only has to decide LATER whether and which to write. No action now; revisit after steps 1-6. Any figure built from raw-derived keys (all fuel keys) needs an Opus audit and his signed dual report until F03 is resolved.

## 8. Procedures and pitfalls learned
- Director = `research-director` (Read/Grep/Glob only, cannot write). Dispatch from the main session with a brief file + line range; ask for rows in ONE fenced code block. Finished background agents' transcript files come back EMPTY, so copy rows from the hand-back message into files (this is how the ledger was built). Parallel foreground dispatch of 5 took ~35-40 min.
- Windows: use `C:/Users/...` paths in Bash; scratchpad path has `ANDRII~1` short name; set `PYTHONIOENCODING=utf-8`; Grep over the repo root without `path`+`glob` times out (raw/, node_modules/). pip installed this session: pypdf, pymupdf (for rendering image-only PDFs).
- Raw file names mix spaces/underscores: key = digits `YYYYMMDD_HHMMSS.csv`. normHash definition: corpus_manifest._norm_hash.
- Subagents' claims were verified only where marked V; NV rows are plausible, not checked.

## 9. Open questions for Andrii
- Decide re-anchoring only after step 1 results. Provide the audit's evidence ZIP (chart_parity, hash_validation, statistical_validation) if he has it (known-answer targets).
- Optional: fill-up records (litres + odometer) for an external fuel check; the app's fuel-calculation setting.
- Approve a CLAUDE.md wording fix (333/489) when step 1 is settled.

## 10. Update 2026-10-02 (after M323 merged to main, tag M323)
- Step 1 (originals) DONE: M323 = F03 originals recovered; see `analyses/F03_originals/RESULT.md` (G1-G4 passed, Python 3.11.15 and 3.12 identical). CLAUDE.md Owner decisions updated with Andrii's approval (2026-10-02). Re-anchoring still NOT decided.
- M321/M322 were taken by M119-v2 ladder work; the milestone numbers in section 6 are proposals. Director re-ruled 18 ledger rows on the originals evidence (`rerule_M323.txt`, applied to `ledger/P*.txt`, `ledger_all.tsv` recompiled): new proposed M324 = F03 follow-up (refresh stale `f03_provenance.json` originalsAvailable:false/"335/500"; read-only grid check of the 9 coarse-voltage originals, C3.18/C14.12; F01 footer; originals manifest prep pending Andrii). Rows still labelled M325/M328 use round-1 plan labels: renumber from the CHANGELOG head.
- Director caveats: cell_spread_adj_hub is among the 25 drifted ML/refit columns, so confirm the F02 response column is non-drifting before attributing the opposite-sign slope to the re-exports; ~12% of the 333 raw/ copies may be value-neutral; do not carry the CHANGELOG word "reproduce" into dashboard/article.
- Next: GateA2 spec (before the next ingestion), then M324.
- Numbering update: GateA2 takes M324 (spec `analyses/M324_gatea2_spec.md` rev 2, Director spec review "revise" applied; implementation pending); the Director's "M324 = F03 follow-up" shifts to M325 (f03_provenance.json refresh, 9-coarse-file originals grid check C3.18/C14.12, F01 footer). Ledger rows still say M324/M325 from the re-ruling: renumber when each spec is written.
