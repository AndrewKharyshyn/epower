# Feasibility assessment of the two audits of 2026-10-11

Inputs: `epower_deep_audit_2026-10-11.pdf` (external "deep audit", 18 pp, revised 11 Oct 2026, M398, 22 open findings) and `XTrail_self_audit_2026-10-11.pdf` (6 pp; byte-identical to `analyses/self_audit_2026-10-11/XTrail_self_audit_2026-10-11.pdf`, MD5 `c5378355…`).
Repo state when assessed: branch `claude/next-milestone`, HEAD `4a43360` (M398 merged, PR #92), `drive_master.csv` MD5 `64dfd0cb…` (554 rows x 190 cols), nothing changed by this assessment (all files under `analyses/` are untracked).
Both PDFs were read page by page via text extraction; the deep audit's 7 embedded attachments (`open_findings.json`, `capacity_check.py`, ...) were extracted to a scratch folder and **read as data, not executed**. Every disk claim below was checked this session by grep / AST / pandas read-only scans; nothing was inferred from memory. Effort figures are **estimates, not measurements**.

## 1. Bottom line

- **Almost everything is feasible with current data** as either a wording/reporting correction, an engineering fix, or a clearly labelled scenario/sensitivity analysis. What is **not** feasible without an independent reference is *physical* validation: generator/DC-bus closure (F12), BSFC/efficiency calibration (F13), an external agreement target (F18), sensor-zero calibration (F14, partly) and any capacity SOH or full/accessible capacity (F16). Both audits say this themselves; the honest deliverable there is claim restriction, not a number.
- **Capacity (D1/D2/F14/F16) is already ~80 % designed here**: three independent analyses + Director ruling "revise / B-prime" + M399 spec v3 (awaiting Andrii's sign-off, not re-reviewed after v2->v3). The deep audit adds requirements that should be folded into an M399 **v4 amendment** rather than run as a parallel track (section 5). One new prerequisite surfaced: **no Ah-throughput producer exists** in the repo (see 3.2).
- **Quick, decision-free corrections (about 1-1.5 weeks of agent time, mostly tests-first wording and small code fixes)** remove every currently *misleading* statement: N09 (two P0 sentences), the Hz-vs-seconds error (7 lines), "scales linearly" (wrong direction, 7 sites), the blanket "not a published OEM spec" (3 sites), the F25 stale sidecar, the F06 stamp conflict, silent `?? 2.1` capacity fallbacks (10), N01-N04 detector/bootstrap bugs, N05 fingerprint, N07 stale tests, N08 import-time refresh.
- **Large items with real risk**: F20 atomic release, F11 replay package, F24 consolidation / stage DAG / arrays split, per-drive caching. Feasible but each needs a decision from Andrii first because it collides with a standing rule (flat working tree, "seasonal recomputed every ingestion", MIGRATION.md reproduction test).
- **Not worth doing** (cost > value for the paper or contradicts an owner decision): MCD outliers, EKF/UKF, RLS-1RC, GP interpolation, Willans/BSFC identification, a full specification curve, N06 chronological calibration, a 400-draw dev tier, a semi-empirical ageing scenario, raw/ to LFS, master-key/timestamp migration (D5/D6), renaming `compute_drive_summary_v6`, splitting the JSX. See sections 5-6b.
- **Several audit figures do not reproduce on disk** (316 broad excepts is 77; 128 un-encoded `open()` is ~195; "five stale GTR blocks" is one, `crossval`; "+0.73" and "r=0.5514" not located). See section 3.
- **Opus research-director triage (section 6b)** concurs with the split above and sets the order: wording wave -> N01-N03 -> M399a (Ah producer) -> M399 v4 -> GTR + F18 -> inference sensitivity -> F19/N06. It amends its own ruling 3(a) (CI and method range side by side, not a union) and advises against quoting the self-audit's 1.69 kWh / "+24 %".

## 2. Legend

| Class | Meaning |
|---|---|
| **Q** | Quick correction: deterministic, no scientific decision; failing test first, then fix (S). |
| **R** | Reporting/engineering change with a gate, no new scientific claim. |
| **M** | Method change or new figure: pre-registered spec + blind audit (analytical-auditor) + Director; Andrii sign-off if a headline moves; Opus audit + sign-off if it enters the article. |
| **X** | Needs an external reference/measurement. Only claim restriction is possible now. |
| **D** | Decision for Andrii first (collides with a standing rule or owner decision). |
| **N** | Decline / defer, with reason. |

Effort: **S** < 0.5 day, **M** 1-2 days, **L** 3+ days of agent time (the same scale as WP table in the earlier consolidated self-audit). Calendar time is dominated by Andrii sign-offs and the ~37-min ingest / ~5-min `release_check` cycles.

## 3. What the audits claim vs what is on disk

### 3.1 Confirmed exactly
| Claim | Evidence on disk |
|---|---|
| 288 Python files, 53,324 lines, 18,301-line arrays module, 34 stages | `git ls-files '*.py'`; `wc -l compute_summary_arrays.py`; `tools/ingest_stages.json` |
| JSX 12268 "gross runs ~2x net" (N09) | text present; also states net "degenerates toward zero or negative" |
| JSX 12387 footer "do not by themselves establish ... original logger exports" (N09) | text present; contradicts the M366 state (489/489 sha256-verified originals in `raw/`) |
| "~1.3 Hz" / "~1.26 Hz" (D3) | JSX 7385, 7440, 7500, 8468, 8882, 9041, 9290 (7 lines) |
| `refreshed at M373` basis note (F06/p8) | JSX 4902 |
| 10x `?? 2.1`, 36 numeric `??` fallbacks (silent fallbacks) | `grep -o "?? *[0-9]" xtrail_summary.jsx` |
| Standalone MC sidecar 1295.913 vs live 1568.9442 (F25) | `energy_uncertainty_mc.json` / `summary_arrays.json energyUncertaintyMC.grossThroughputMC.nominalReleasedThroughputKwh`; the sidecar is written only by `energy_uncertainty_mc.py`, not by any stage in `ingest_stages.json` or `release_check.py` |
| masterRefitAudit = 446 rows, generated 2026-09-25 (F06) | `summary_arrays.json masterRefitAudit.nRowsPublished=446`, `generatedAt` |
| `release_check` states raw->master rebuild NOT COVERED (F11) | `release_check.py:331` |
| Generator node fails +/-5 % (F12) | `gtrClosure.nodeExcess`: 0.0695 [0.0534, 0.0895], tolerance 0.05, `closedUnderRule:false` |
| Cold cohort 7 drives / 3 days suppressed; intake air valid 270/554, 284 none, last valid 2026-08-24 (F19) | `cohortMeta.cold`, `meta.intakeAir` |
| Detector bugs N01/N02/N03 | `tools/dissipation_events.py`: `dropna(subset=...)` before `_runs` (gaps merge), `t0` from each detector's own first row, `load.fillna(0)` |
| N04 NaN propagation / zero denominator | `tools/day_bootstrap.py` uses `np.bincount(weights=...)` and divides without a guard |
| N05 fingerprint omits raw content and `XT_RAW_DIR` | `tools/run_fingerprint.py`: raw part = sorted (name, size); env hash explicitly excludes `XT_RAW_DIR` |
| N07 stale tests, and not run in CI | `tests/synthetic/test_ambient_provenance.py:24` asserts 489; neither test appears in `.github/workflows/ci.yml` |
| N08 MC note refresh at import, parses prose | `tools/mc_dq_note_refresh.py`: module-level read/write of `summary_arrays.json`, `re.search(r"\(([0-9.]+) kWh corpus-wide\)", ...)` |
| N06 "effective hard level" wording | `tools/recal_gate.py:30`, asserted by `tests/synthetic/test_recal_gate.py:74` |
| `efc_per100km` is GTC (F16) | `compute_drive_summary_v6.py:1735` `s['gtc']/d*100`; `gtc = thr/CAP_KWH` at :692 |
| Offset circularity (D2/F14) | `compute_drive_summary_v6.py:114,1069,1696`: `I_off = sum(energy_residual_kwh)*1000/(sum(duration_h)*V)` |
| D4 odometer | rows 241-242: `odo_start 0.0 -> 63.8 -> 172.2` while neighbours sit at ~6,736; row 232 repeats `odo_start 6648.6` |
| D5 key forms | 367 `YYYYMMDD_HHMMSS.csv` / 187 `YYYY-MM-DD_HH-MM-SS.csv` |
| D6 clock-only `time_start/time_end` | e.g. `18:57:51.363` (a separate `date` column exists) |
| D10 12 NaN eligibility flags, 2 invalid | `ens_outlier_v2`/`ens_invalid`: NaN 12, True 2 |
| D11 ~70 untracked logs; no `*.log` rule | 68 `.log` untracked; `.gitignore` has only `*.pkl` |
| D12 raw/ tracked in git | 565 tracked files under `raw/`; `.git` = 280 MB |
| "Not a published OEM spec" wording (F16) | `summary_config.json:3710`, `compute_summary_arrays.py:162`; JSX 2506, 6611, 11897 "not an OEM nameplate figure" |
| "scales linearly" with the 2.1 kWh constant (F16) | JSX 11742, 11986, 12381 and `summary_config.json:1559` (GTC/FCE/C-rate scale **inversely**) |
| Run time 2,217 s; refresh_raw_seasonal 930 s | `runs/20261009T224535Z/status.json` (32 stages; also 2,315 s run) |
| Section-6 dashboard literals | JSX 4081, 4334, 8650, 7046, 6908, 7289, 3944, 3435, 11414, 8788, 8315, 7283 all contain the cited text |
| Raw roles (2 discontinued comparison-only + 9 auxiliary) | `raw_manifest` roles: canonical 554, comparison_only 2, auxiliary 9 |

### 3.2 Differs from what the audit says (or new finding)
| Item | Audit says | Disk says | Consequence |
|---|---|---|---|
| Broad `except Exception` in the arrays module (D8) | 316 | **77** (44 of them silent: body only `pass`/`continue`/`return None`); 166 repo-wide | Real defect, smaller than stated; work is ~44 silent handlers, not 316 |
| `open()` without `encoding=` (D7) | 128 | **~195** text-mode `open/read_text/write_text` without encoding (AST, 74 files); but `run_ingest.py:91` already sets `PYTHONUTF8=1` for stages | Affects direct/ad-hoc runs (I hit it myself while checking: cp1251 `UnicodeEncodeError`). Mechanical |
| Modules imported by nothing | 139 | 204 statically unimported, of which 62 are named in stage list / CI / release_check -> **~142** candidates; 83 look one-shot (m2xx/m3xx/f03) | Consistent |
| 930 s stage "reads its own raw_loader" | own loader, ignores `drive_raw_cache` | `tools/regen_seasonal_raw.py` imports `drive_raw_cache` and builds `make_frame_loader`, and also defines its own `raw_loader` | Root cause of the 930 s needs **profiling before any speed claim** (the deep audit says the same) |
| JSX size | 11,538 lines (self-audit); ~11.5k (CLAUDE.md) | **12,465** lines | Line numbers cited by both audits are valid against the current file |
| Ah-throughput producer (F16b; M399 table "Ah throughput: unchanged") | exists | **none found**: `drive_master` has only `cap_ah_est` and `gross_throughput_kwh`; `gtc = kWh / CAP_KWH` | New prerequisite for M399 (5 Ah normaliser needs Ah) |
| "+0.73 calendar/cadence narrative" and "r=0.5514 on 242 drives" (p8) | live in dashboard | **not located** in JSX / `summary_config.json` / `summary_arrays.json` (only an unrelated "+0.73/100km" per-drive note) | Need the audit's `targeted_literal_inventory.json` (not supplied) to find the exact string |
| "complete 34-stage workflow not independently benchmarked" (p15) | unbenchmarked | `runs/*/status.json` hold real end-to-end stage timings for two full ingests (2,217 s / 2,315 s) | A baseline for the next benchmark already exists |
| Stale "254 unavailable" intake-air total | still in use | **not found** in JSX/config; payload says 284 | Nothing to fix |
| "Five stale GTR blocks" (CLAUDE.md open items, self-audit WP10; the Director's brief said four) | gtrClosure, sensitivity, simultaneity, crossval, speedSplit stale | `generatorTractionRecon.staleBlocks.blocks = ["crossval"]` only (Path A coefficients unpreserved, not recomputable, basis M280, 82 drives); `refreshedBlocks` = sensitivity, simultaneity, speedSplit at 324 drives; `gtrClosure` recomputed at ingestion | WP10 collapses to **archiving `crossval` as historical** (S). The CLAUDE.md "speedSplit has no auto-splice" open item looks outdated: Andrii to update the file (not edited here) |

### 3.3 Not verified here
Deep-audit capacity numbers (1.7998 kWh, 4.9363 Ah, matched-lag 1.7007-1.8905 kWh, chronological RMSE 22 vs 38 Wh), 6.9467 % closure re-sample, batch-rank "1 % false alarm" claim, +4.49 % left-hold throughput, `stamp_contradictions.json`, `edge_cases.json`: they depend on the auditor's embedded scripts/bundle (untrusted, not executed). The repo's own capacity study and blind audit already support ~4.9 Ah independently; M399 will reproduce the numbers with pipeline code. Literature pointers (S1-S9, plus Plett, Schmalstieg, Cameron-Gelbach-Miller, Schuirmann, Guzzella-Sciarretta, ASTM E1049) must be verified before citation (the self-audit says so for its own).

## 4. Register A: deep audit (every item)

Priorities as in the audit. "Dep" = prerequisite or coupling.

### 4.1 Page 1 decisions and basis
| ID | Item | Class | Effort | Dep / gate | Note |
|---|---|---|---|---|---|
| DA-D1 | Capacity: publish ~1.8 kWh as exploratory logged-SoC response scale; full/accessible/SOH unidentified | M | L (part of M399) | M399 sign-off; Director B-prime already ruled | Fits ruling: "apparent capacity of the BMS SoC scale, estimated"; never "usable/true/measured". Article needs Opus audit + sign-off |
| DA-D2 | Cycle exposure: raw Ah/kWh primary, formulas+references, separate full-reference vs accessible-window turnover | R/M | M | Ah producer (3.2), M399 | See DA-F16 rows |
| DA-D3 | Reporting: stamps, sidecars, source claims, narrative contradictions, silent fallbacks | Q/R | M | tests first | DA-F06, F25, N09, p8 rows |
| DA-D4 | Reliability: detector clocks/missingness, bootstrap semantics, atomic release, replay | R | M-L | | DA-N01-N05, F20, F11 |
| DA-D5 | Efficiency: content-keyed deps, shared native features, consolidate producers, profile whole workflow | R/D | L | Andrii (standing rules) | DA-F24 |
| DA-B1 | Basis statement (554 drives, 8,976.84 km, 112 days, energy support 540, excluded files, "report revision only") | - | - | | Matches disk (554/112; roles 2+9); no action |

### 4.2 Findings register (22)
| ID | Pri | Item | Verified | Class | Effort | Dep / gate | What can be done now vs conditional |
|---|---|---|---|---|---|---|---|
| F06 | P0 | Historical stamps conflict (computed/489 vs 446-row audit of 09-25) | V (446, generatedAt 2026-09-25; schema split absent) | R | M | restamp stage (M388) & `semantic_gate`; payload metadata only, no numbers | Split `computedAt`/`inputBasis` from `includedInReleaseAt`; carried blocks keep their historical basis. Fully doable |
| F11 | P1 | Publication replay unverified | V (`release_check.py:331`) | D/R | L | Andrii: scope of replay (frozen ML fits, manual inputs, repairs ledger); CLAUDE.md forbids `run_pipeline()` except clean-room audit | Doable as a pinned replay package + clean-env run; cannot be made fully "from raw" because ML columns drift (open item) -> replay applies frozen state |
| F12 | P1 | Generator closure fails +/-5 % | V (6.95 %, CI 5.34-8.95) | Q + X | S (wording/bounds) | `gtrClosure` already has `excessWithoutDual`, `interval`, `closedUnderRule:false` | Keep failure prominent, attribution bounds, no "validated split". Physical closure needs an independent electrical reference (X) |
| F13 | P1 | BSFC/eta/auxiliary assumptions uncalibrated | V (model_constants / recon_engine) | M + X | M | spec + blind audit | Versioned assumption registry (S-M), regime sensitivity, held-out *internal* error. External calibration X |
| F14 | P1 | Offset conditional on SoC/capacity ledger | V (circular definition) | M | in M399 | M399 test (b) (in-fold I2R vs offset), (h) key-on | Rename "model-derived residual-balance offset"; separate from sensor zero. Sensor-zero calibration needs a zero-current reference (X; the ACC-mode part of the M399 experiment may help) |
| F15 | P1 | Aging equivalence margins unvalidated | not re-verified in code | R/D | S (wording) + M (margins) | Andrii/Director must choose pack-relevant margins *before* the next analysis | Demote k=2/imported SoC weights to "uncalibrated sensitivity indices"; drop 14-year transfer; simulate detection horizon (M) |
| F16 | P1 | Capacity & cycling references unidentified | V | M | L | see 4.3 | M399 v4 |
| F17 | P1 | Narrow MC omits cadence/model uncertainty | V (loggerCadence emulation exists) | M | M-L | spec + blind audit | Separate labelled scenario sensitivities (alignment, interpolation, gaps, offset, capacity) shown beside the MC; never one pooled interval |
| F18 | P1 | Historical correlation treated as validation (r=0.9966) | V (`staleBlocks`: crossval, Path A coefficients unpreserved) | Q + RC | S | none | Coefficients cannot be recovered, so **archive `crossval` as a dated historical internal comparison** (Director: Bland-Altman only if coefficients were recoverable). Never "validation". External target X |
| F19 | P1 | Thermal estimates selected; winter weak | V (cold 7/3, intake 270/554) | M | M-L | spec + blind audit | Candidate/accepted/rejected/censored ledgers for warm-up and oil/coolant thresholds; survival-style summaries; keep winter suppressed |
| F20 | P1 | Sequential writes can publish mixed versions | V (`ingest_core` has per-file tmp+`os.replace` and gate backups; `run_ingest` has no downstream rollback) | D/R | M (journaled swap) / L (release dirs) | A single-pointer release dir changes the flat tree -> blocked by MIGRATION.md rule | Feasible now as journaled copy-swap with rollback on any stage failure; a true pointer switch needs a layout decision |
| F24 | P2 | Too many mutating producers | V (288 files, 34 stages, 18,301-line arrays) | D/R | L | MIGRATION.md reproduction test; deep-diff gate | Staged: archive dead code (S-M), registry package (L), stage DAG (L). See 4.5 |
| F25 | P2 | Historical sidecars appear current | V (1295.913 vs 1568.9442) | Q | S | none | Regenerate from the live object or move to a dated `archive/`; add to `release_check` |
| N01 | P1 | Missing rows merge separate events | V | R | M | known-answer fixtures; monitor report-only | Keep the full 1 s grid; unknown breaks runs; durations/slopes from timestamps |
| N02 | P1 | Different time origins per detector | V | R | M | with N01 | Shared drive clock, store start+end; recompute overlap flags |
| N03 | P1 | Unknown engine load becomes 0 | V | R | S-M | with N01 | Require observed load; publish unknown-state coverage |
| N04 | P2 | Fast bootstrap NaN / zero-denominator | V | Q | S | known-answer 2-day fixture | Raise on non-finite input (explicit) or document skip-NaN; guard zero denominators. Estimator/seed/draws unchanged |
| N05 | P2 | Fingerprint ignores input content/path | V | R | S-M (raw via manifest sha256) / L (full stage graph) | none for S-M part | Hash raw bytes via `raw_manifest` sha256, resolved path of `XT_RAW_DIR`, shared fitted state |
| N06 | P1 | Rank resolution presented as error control | V | Q + RC | S | none | Replace "effective hard level" by "rank resolution" (`recal_gate.py:30`, test :74). Director: the chronological false-alarm / injected-shift calibration is **not worth doing** (too few batches); a non-flag means "no shift detected", not stable calibration |
| N07 | P2 | Two tests with stale counts | V | Q | S | none | Dynamic support assertions or dated fixtures; add to CI list (fast tests only) |
| N08 | P2 | MC refresh runs on import, parses prose | V | Q | S | none | Guarded `main`, numeric fields, single producer-owned object (with F25) |
| N09 | P0 | Residual dashboard statements contradict results | V | Q | S + M (checks) | semantic_gate/language_gate; Dashboard change rule | Delete/bind "gross ~2x net"; bind footer to the M366 original-byte record; add fact-aware checks (each sentence must fail its check before the fix) |

### 4.3 F16 capacity pages (4-7) in detail
| Item | Verified / note | Class | Effort | Where |
|---|---|---|---|---|
| p4 apparent scale table (5/10/15 pp windows; 10 pp = 1.7998 kWh, CI 1.7821-1.8164) | not re-run (audit script); consistent with repo study (~4.9 Ah) | M | in M399 | Add the nonoverlapping-window estimator as a **pre-registered sensitivity** in M399 v4 (spec says the method-range list is fixed; adding needs an amendment) |
| p4 chronological check (1.8 vs 2.1 kWh RMSE 22 vs 38 Wh) | not re-run | M | S | M399 (g) deliberately *drops* the comparison against 2.1 ("loses by construction"); keep it descriptive, state that predictors and targets share BMS channels |
| p4 `apparentSoCScale` output (model, thresholds, support, day-cluster CI, direction/cadence splits, lag sensitivity, chronological errors), separate from `fullRatedCapacity`/`accessibleWindowCapacity` | partly = M399 `capacityBasis` | M | M | Name/field alignment between `capacityBasis` and `apparentSoCScale` |
| p4 5/10/15-pp rules (nonoverlap, 10-600 s, reject gaps and jumps, SoC=0 artefacts not boundaries) | SoC extremes in corpus 42.5-88.0 % | M | in M399 | |
| p5 matched-support lag +/-2 s: 1.7007 / 1.8103 / 1.8905 kWh; 4.6611 / 4.9603 / 5.1791 Ah | not re-run | M | in M399 | Scenario sensitivity, **not** a CI; M399 already lists +/-2 s in the fixed method range. Do not optimise lag on the evaluation data |
| p5 separate charge model vs energy model with their own bias terms | M399 has `Q_SOC_EST` and `E_PER_SOC100_EST` kept apart | M | in M399 | Already specified |
| p5 whole-drive and direction-only fits as sensitivities | | M | S | add to method range via amendment |
| p6 metric table (discharge EFC, bidirectional FCE, GTC, charge-throughput EFC, SoC-rainflow EFC) | formulas consistent with the repo's three EFC quantities; GTC = Ed+Ec over Eref (twice FCE) | R | S-M | Document in glossary; no conflation; GTC keeps `verified:false` |
| p6 scenario table 2.1 -> 361.75 / 373.56 / 747.12; 1.8 -> 422.04 / 435.82 / 871.64; 540 drives: 759.667 / 809.277 / 1568.944 kWh | live payload gross = 1568.9442 (V); FCE headline 373.5 (self-audit) | R | S | must be **script-written** (CLAUDE.md), from `capacityBasis`; never typed |
| p6 "all cells participate; EFC is exposure, damage depends on depth/SoC/rate/T" | | R | S | wording |
| p7 F16a reference registry (value, units, class, basis, source, applicability, status, version; no auto-switch to 1.8; all consumers declare) | M399 step-0 inventory + `capacityBasis` cover most; `CAP_KWH` has 17 consumer files | M | M | extend `capacityBasis` fields |
| p7 F16b channel integration (positive Ah beside kWh on the same native intervals, export-only rounding, known-answer sign-crossing/gap tests) | **no Ah producer exists** | M | M-L | New prerequisite for M399; decide: master columns (changes MD5, control build) vs per-drive sidecar |
| p7 F16c SoC reference (full capacity vs remapped BMS window), rainflow stays on logged scale | X (cannot be identified from BMS data) | X + R | S | Publish denominators, glitch/floor/half-cycle rules, eligible IDs; no silent energy-ratio conversion |
| p7 F16d relabel `cap_ah_est` = assumedEnergy / medianVoltage; fixed charge reference for C-rate | M399 says `cap_ah_est` derived from `CAP_AH_RATED`, constant-per-voltage, excluded from capacity-health evidence | R | S | reconcile wording with M399 |
| p7 Nissan AU publishes 2.1 kWh (e-4ORCE) -> correct blanket "not a published OEM spec" | V (3 config/code sites + 3 JSX) | Q | S | M399 wording already adopts "Nissan-published marketing figure of undefined basis" |
| p7 5 Ah derived from Wh / nominal V; 5 Ah x ~360 V ~ 1.8 kWh is approximate, not a usable-energy test | consistent with Director: "do not derive a rated kWh" | R | S | |
| p7 do not publish "2.1 gross / 1.8 usable" as specification | consistent with Director | R | - | language gate |
| p7 "scales linearly" -> "scales inversely with the selected reference" (GTC/FCE/C-rate) | V (JSX 11742, 11986, 12381; config 1559) | Q | S | |
| p7 `efc_per100km` actually GTC: document, version a rename, do not change frozen feature values | V (:1735) | R | S | glossary + feature-schema note |

### 4.4 Pages 8-13
| Page / ID | Item | Verified | Class | Effort | Note |
|---|---|---|---|---|---|
| p8 N09 gross~2x net (JSX 12268) | V | Q | S | Delete (net is negative: -49.6 kWh vs gross 1568.9); or bind gross/discharge from payload |
| p8 N09 raw-originals footer (JSX 12387) | V | Q | S | Bind to M366 / `originals_manifest` record; label old audit limitation historical |
| p8 F06 carried refit stamp | V | R | M | = F06 |
| p8 F25 MC sidecar | V | Q | S | = F25 |
| p8 calendar/cadence correlation +0.73 -> r=0.5514 on 242 drives | **not located** | Q | S once located | needs `targeted_literal_inventory.json` |
| p8 milestone labels ("refreshed at M373", JSX 4902) and silent fallbacks | V (4902; 36 numeric `??`, 10 of them `?? 2.1`) | Q/R | S-M | producer date/basis from the `refreshedBlocks` record; missing required stat renders "unavailable" or fails the build; MC calibration defaults must not substitute silently |
| p8 capacity text and axes bound to one registry | | M | in M399 | |
| p8 one typed result object for chart/table/prose | | R/M | L | the digit-literal gate (self-audit WP7) is the enforcement; objects incrementally |
| p8 completion: all tabs/cohort modes pass semantic checks; each contradictory sentence fails its check first | | R | M | `semantic_gate` A2 extension |
| p9 N01-N04 acceptance cases | V; audit notes current raw event totals are unchanged on contiguous masks | R | M | Keep monitor report-only; publish affected-output differences |
| p10 F20 transaction boundary | V | D/R | see F20 | failure injection after master / arrays / before HTML |
| p10 F11 replay package | V | D/R | L | |
| p10 N05 fingerprint | V | R | S-M | |
| p10 N07 tests | V | Q | S | |
| p10 "retain always-run integrity checks; green status file insufficient" | | R | - | design constraint for F20 |
| p11 F14 label offset conditional | | M399 | | |
| p11 F17 separate sensitivities (alignment, cadence, interpolation, gaps, quantisation, offset model, capacity) | | M | M-L | not bundled into a probabilistic interval |
| p11 N06 calibrate chronological false alarms/power; account for overlap and seasonal/cadence shifts | | M | M | |
| p11 dependence: block-of-days, small-cluster inference; nuisance fitted inside training folds | | M | M | = self-audit WP11 |
| p11 "batch rank does not establish a 1 % false-alarm rate; non-flag != stable calibration" | wording present at `recal_gate.py:30` | Q | S | |
| p11 estimator sensitivity: left-hold +4.49 %, no-bridging >5 s -0.0956 %, backward-only V -0.0032 % | not re-run | M | M | fold into F17 integration band; matches self-audit "3 s vs 10 s moved net by 1 %" |
| p12 F12/F13/F18 acceptance (failed rule, attribution bounds, assumption registry, held-out error, agreement intervals) | | see rows | | "Implementable now: matched-support accounting, source-attribution bounds, internal chronological validation, regime diagnostics, honest labels" - agreed. External calibration: X |
| p13 F15 equivalence margins, demote k=2/weights, detection-horizon simulation, selection/confounding diagnostics | | R/M | S + M | all seven resistance intervals include zero (trend unresolved); no stability or SOH claim |
| p13 F19 thermal/winter ledgers + survival-style + input-driven thermal models only if identifiable | | M | M-L | |

### 4.5 Pages 14-16 (architecture, speed, acceptance)
| Item | Class | Effort | Note |
|---|---|---|---|
| Arrays builder -> separate energy/fuel/thermal/event/inference builders + one assembler | D/R | L | Byte-identical deep-diff gate exists; blocked by MIGRATION.md rule for tree changes; do last |
| GTR refresh/family/closure splices -> one result bundle | R | M | only `crossval` is still stale (3.2); do after the M399 test-(b) offset decision, because the offset feeds `recon_engine` and an earlier refresh would run twice |
| Seasonal/master/raw/cohort/cube passes -> one view layer | R | L | |
| Repeated model fits persisted under full input hashes | R | M | preserve frozen ML16 |
| N08 import-time refresh | Q | S | |
| Milestone wrappers / duplicate state: prove no dependency, archive | R | S-M | my scan: ~142 candidates (3.2); verify subprocess/doc references before moving |
| `thr_per100km` vs `efc_per100km` duplicate (standardised) | D | S | removing one needs a versioned model + held-out comparison; **not** to be claimed as unchanged |
| Target 8-12 domain producers | - | - | design target only |
| Speed 1: content-hashed stage graph | D | L | conflicts with "seasonal recomputed every ingestion" standing rule unless outputs provably identical and Andrii agrees |
| Speed 2: native-feature cache (float64, unknown states, no silent 1 Hz) | R | L | profile columnar storage first; `drive_raw_cache.py` already has 18 importers |
| Speed 3: OLS bootstrap via per-day X'X, X'y | R | M | only if profiling shows OLS bootstraps are a top cost; compare with row-based `lstsq`; QR/SVD fallback |
| Speed 4: share masks/group codes across cohort builders | R | M-L | preserve per-family denominators |
| Speed 5: profile hot loops, bounded per-drive workers | R | M | deterministic order, BLAS threads, measured RSS |
| "No MC draw reduction, no float32, no median shortcuts" | - | - | agreed; it also rules out the self-audit's 400-draw dev tier for anything published |
| Baseline: core 86.7 s on 524 drives, additive day-bootstrap 31 ms, MC 350 ms | not re-run | - | full-workflow baseline already exists in `runs/*/status.json` |
| Acceptance plan: 5 work orders; benchmark protocol (same inputs/interpreter/threads, alternate order, RSS, parse counts); exact IDs/nulls/flags; singular OLS tests; stage failure leaves release unchanged; known-answer + independent implementation for new math | R | - | adopted as the exit criteria for the plan in section 7 |

### 4.6 Pages 17-18
| Item | Note |
|---|---|
| S1 Nissan AU 13 Oct 2022 (2.1 kWh, e-4ORCE) | already used by M399 spec (page checked 2026-10-11 there) |
| S2 Nissan Europe battery disclosure (5 Ah, Wh / nominal V) | = Article-10 sheet used by the Director ruling |
| S3 JRC136381 (EFC/FCE conventions); S4 Preger 2020; S5 JCGM 101; S6 Politis-Romano; S7 Bland-Altman; S8 Lakens; S9 Keil | cite only after the author verifies them; none is needed to implement the engineering fixes |
| Embedded evidence: capacity scripts/JSON/CSV | treated as untrusted data; not executed |
| Scope limits (single FWD vehicle, app-derived fuel, no independent capacity/generator reference, no verified SoC remapping) | already the project's standing disclosures |

## 5. Register B: self-audit (every item)

### 5.1 Executive summary and section 3 table
| Item | Class | Effort | Note |
|---|---|---|---|
| Capacity ~20 % too high (joint 1.69 kWh [1.64, 1.74]; FCE 373 -> 464) | M | in M399 | Settled direction (Director): apparent scale ~4.9 Ah / ~1.8 kWh over SoC 44-83 %, method range 4.58-5.43 Ah. The 1.69 kWh differs from the deep audit's 1.80 and the Opus study's 1.75-1.80: the spread is the method range and must be reported as such. **Never type 464 or 1.69** |
| Residual closure circular (offset defined at 2.1 kWh) | M | in M399 (b) | V in code. Held-out-day residual; report closure "under an assumed scale" |
| Hz unit error | Q | S | 7 JSX lines; bind to `loggerCadence` (median interval 1.285 s); add language-gate rule for "Hz" next to cadence; revisit "non-resolvable relaxation" with the 0.78 Hz Nyquist limit |
| Odometer ledger (101.1 % logged share) | R | S | **Data-health item only**. The Overview KPI is the owner's totalKm/dash-ODO rule (2026-10-03) and must not change; add anomaly record + continuity check |
| Process weight (37-39 min; 139 unreferenced modules; 1.49 MB CHANGELOG; 316 excepts) | R | see below | numbers: 77 excepts, ~142 modules |
| Gross discharge/charge reproduced to ~1.5 %; arithmetic identities pass; net draw -49.61 vs -50.99 (10 s) / -50.45 (3 s) | - | - | positive confirmation; feeds F17 integration-policy band (+/-2-4 %) |
| Cell-spread trend reproduces (+0.263 vs +0.32; lag-1 autocorr 0.25 -> CI optimistic) | M | M | block bootstrap row beside day-cluster CI |
| Pack-resistance naive trend is a confound (adjusted ~0) | - | - | reproduces the M395 cadence study; no action |
| Capacity caveats (nonlinear SoC; I2R bias; 0.5-pt quantisation) | M | in M399 | (b) I2R model; (c) level test |

### 5.2 Defects D1-D12
| ID | Sev | Verified | Class | Effort | Recommendation |
|---|---|---|---|---|---|
| D1 | High | V | M | in M399 | CAP as bounded parameter with CI, dual report |
| D2 | High | V | M | in M399 | held-out residual validation; stop quoting residual ~ 0 as validation |
| D3 | Med | V (7 lines) | Q | S | |
| D4 | Med | V | R | S | data_health anomaly record for 2026-08-16 (`20260816_124817`, `20260816_144003`) and `20260813_144601`; continuity check; set `distance_source` explicitly; KPI unchanged (owner rule) |
| D5 | Med | V (367/187) | N/D | S (helper) | Works today (`ingest_core` maps names). Add a mapping helper, **do not** change the master key now (changes MD5, touches every join) |
| D6 | Med | V | N/D | S | `date` + `time_start` already gives a timestamp; provide an accessor in `tools/`, not a master change |
| D7 | Med | V* (~195, not 128) | R | S-M | `PYTHONUTF8` already set in `run_ingest.py:91`; add the same to test/CI runners and an AST guard for new code; fix files opportunistically (74 files) |
| D8 | Med | V* (77, 44 silent) | R | M | collect failures from silent handlers; `release_check` red on a non-empty list; expect pre-existing swallowed failures to surface |
| D9 | Low | V (0.0009 vs 0.0005 on a 1.9 Wh drive) | N | S | Master stores rounded columns by design; fixing it changes the master. Document; ratios downstream from unrounded values only |
| D10 | Low | V (12 NaN flags) | R | S | NaN-safe comparisons in `release_check`; explicit reason sidecar; M399 test (d) already covers the 12 drives |
| D11 | Low | V | Q | S | `.gitignore *.log`; move logs under `runs/`; keep `baseline_arrays.json`/`published_arrays.json` (control-build inputs) - move, do not delete |
| D12 | Low | V (565 files, 280 MB) | N/D | M | Moving files to LFS does **not** shrink existing history without rewriting it; benefit only for future growth. Defer; partial clones cost nothing |

### 5.3 Section 5 methodology
| Item | Class | Effort | Note |
|---|---|---|---|
| Retire "residual ~ 0" as closure evidence | M | in M399 | |
| Single capacity number in headline derived quantities must carry the interval/band | M | in M399 | dual report + window-fraction band |
| Hz statements; non-resolvable relaxation argument with 0.78 Hz | Q | S | |
| Remove milestone archaeology from reader text (JSX 3435, 11414, 3944-3945; "M174/M205") | Q | S | V all present |
| Re-word "seasonal" as within-season association (112 days, May 11-Oct 8; corr(T, day) -0.31..-0.37) | R | S-M | language gate; one vehicle |
| Week-block / moving-block bootstrap sensitivity | M | M | WP11 in the earlier consolidated self-audit; Director: do now, additive, article-bound |
| Alternatives table: Deming/TLS or EKF with current-bias state | M (Deming) / N (EKF) | M | Deming/EIV fits M399 as a sensitivity. **Director: EKF/UKF not worth it** (no OCV-SoC curve; I and V are not sampled simultaneously), and "EKF separates bias from scale" does not hold under those conditions |
| Resistance: RLS 1-RC with forgetting + Arrhenius term | N | L | Conclusion (unresolved, confounded trend) already reproduced. **Director: not worth it**; the RC time constants are close to the ~1.28 s logging cadence |
| Throughput ageing: Schmalstieg-style stress-weighted scenario | N | L | **Contradicts** deep audit F15 ("remove unsupported lifetime/damage implications; demote k=2 weights to uncalibrated indices"). Literature parameters are for other cells; if ever added, only as a labelled uncalibrated index |
| Inference: wild cluster / CR2 + block bootstrap; MDE beside every "not established" | M (additive, article-bound) | M | **Director: NOW.** Week-block bootstrap on the thesis KPIs; CR2/wild-cluster only for slopes with fewer than 50 clusters; MDE beside each "not established" (reporting-only). Day-cluster CI stays |
| Energy integration: ZOH vs trapezoid vs GP band | M | M | = F17. **Director:** keep the ZOH/trapezoid bracket; GP interpolation adds nothing beyond it |
| Generator/traction: Willans-line/BSFC identification; allocation as interval | N | L | **Director: not worth it** (the fuel counter is app-calculated). An interval/bracket beside the default Sankey is compatible with the 2026-10-03 owner decision; replacing the Sankey point is not |
| Outliers: MCD + rule gates instead of IF+LOF+MAD | N | M | **Director: not worth it**: rewrites the canonical exclusion and touches ML16 for 2 of 554 invalid drives |
| Multiverse / specification-curve table (capacity, offset, gap cap, outlier rule, regime handling) | N (full curve) | M-L | My first view was "highest value for the paper"; the **Director overrules** (cost > value). M399's fixed method-range list is the bounded form of the same idea |

### 5.4 Section 5.3 novelty and dashboard section 6
| Item | Class | Effort | Note |
|---|---|---|---|
| Lead the article with buffer behaviour + identifiability; ageing and GTR allocation secondary | D | - | Andrii's call; article text is out of scope for code changes |
| Add a falsification section ("what data would refute the buffer thesis") | R | S | analysis-side pre-registered criteria note; article wording is Andrii's |
| Second vehicle or external reference (OEM service data, dealer SoH read) | X | - | the only route to a capacity anchor beyond BMS data |
| Remove point-valued GTR Sankey allocations | D | - | conflicts with owner decision 2026-10-03; add intervals instead |
| Retire many single-use studies | R | S-M | archive; keep evidence |
| Dashboard literals: JSX 4081/4334, 8650-8651, 7046-7047, 6908-6909, 7289, 3944-3945, 3435/11414, 8788-8831, 8315/7283 | R | M-L | all V; bind to `generatorTractionRecon`, `engineStartContext`, `engineOnBySpeed`, `auxLoadAmbient`, `socHysteresisV2`, `engineRpmClusters`; 4081/4334 depend on partly stale GTR blocks |
| Digit-literal gate in `semantic_gate.py` (377 lines / 612 literals; ~91 approximations) | R | M | introduce as ratchet (WARN with allow-list, then FAIL); the 91 bindings are the long tail |
| Derived tables tracked in git and embedded in `summary_arrays.json` | N | M | little value; risk to `release_check` readers |

### 5.5 Sections 7-9
| Item | Class | Effort | Note |
|---|---|---|---|
| Split arrays into package with registry | D/R | L | = DA-F24 |
| Rename `compute_drive_summary_v6` | N | S | cosmetic, 17+ import sites |
| Archive ~60 one-shot scripts, ~70 logs | R | S-M | ~142 candidates after exclusions; verify dynamic references |
| Merge duplicate pairs (fuel_analytics/2, ladders, four one-off GTR scripts) | R | M | the GTR scripts only matter for blocks still stale: just `crossval` (3.2) |
| Repo layout, CHANGELOG split (keep head 30) | D | M | layout blocked by MIGRATION.md; CHANGELOG tools read the head, so keep the path |
| Stages as DAG in one YAML; drop `apply_m284_post.sh` | R | M-L | pairs with deep-audit stage graph |
| Split 12,465-line JSX by tab + bundler | N | L | maintainability only; high regression risk for the language-gate dumps |
| Speed table (refresh_raw_seasonal 930 s = 42 %; release_check 280; refresh_master_seasonal 206; record_spread_fit 190; gtr_family 96 + gtr_closure 79; fuel_analytics 57+88) | V | - | timings confirmed |
| Perf 1: one raw scan -> columnar Parquet per drive keyed by sha256 | R | L | `drive_raw_cache.py` already exists; profile first |
| Perf 2: per-drive memoisation (sha256, function-version) | D | M-L | seasonal-every-ingestion standing rule; version hash must capture dependencies |
| Perf 3: process pool / concurrent independent stages | R | M | determinism and BLAS threads |
| Perf 4: two-tier bootstraps (400 dev / 4,000 release) | N | - | contradicts the deep audit and CLAUDE.md (4,000 draws, seed 42); gain <8 % of runtime |
| Perf 5: fast gate <30 s per commit, full gate once per milestone | R | S-M | CI is already one job per PR (M368) |
| Target 8-10 min from 37-39 (estimate) | - | - | unproven; set after profiling |
| Section 9 actions 1-10 | | | map to plan phases in section 7: 1 blind capacity audit already done -> awaits M399 sign-off (P2b); 2 held-out residual = M399 test (b) (P2b); 3 Hz/s = P0; 4 odometer = P1; 5 canonical id / ISO timestamps = defer (D5/D6); 6 performance = P5; 7 digit-literal gate = P5 (ratchet after P0 text fixes); 8 hygiene / UTF-8 / excepts = P1 and P5; 9 stale GTR blocks = P4 (only `crossval`); 10 block bootstrap / CR2 + MDE = P4 |

## 6. Conflicts between the audits, the Director ruling and owner decisions

| # | Conflict | Proposed resolution |
|---|---|---|
| C1 | Capacity value: self-audit 1.69 kWh [1.64, 1.74] vs deep audit 1.80 vs Opus study 1.75-1.80 vs Director 4.9 Ah (method range 4.58-5.43) | Report the **method range** and the conditional CI side by side (M399 spec does). No single figure typed |
| C2 | Self-audit: stop using 2.1 / bounded parameter; deep audit: no auto-switch, 2.1 vs 1.8 are scenarios, and 2.1 *is* published by Nissan AU; Director: 5.0 Ah documentary normaliser | M399 dual-report design satisfies all three; the registry (F16a) makes each consumer declare its reference |
| C3 | Self-audit D4 suggests excluding reset drives from the logged-share KPI | Owner rule 2026-10-03: KPI number never changes, disclosure only. Keep; the anomaly goes to `data_health` |
| C4 | Self-audit: show GTR as intervals instead of a Sankey point | Owner decision 2026-10-03 shows the Sankey by default; add interval/bounds text beside it, never replace |
| C5 | Self-audit: add semi-empirical ageing scenario; deep audit F15: remove unsupported lifetime/damage implications | Do not add; demote existing k=2/SoC weights to "uncalibrated sensitivity indices" |
| C6 | Self-audit: 400-draw dev tier; deep audit and CLAUDE.md: never cut draws | Decline for anything published |
| C7 | Deep audit atomic pointer release vs flat working tree / MIGRATION.md | Journaled copy-swap with rollback now; release directories only after the reproduction test passes |
| C8 | Per-drive caches / stage graph vs "seasonal recomputed on every ingestion" | Andrii must amend the standing rule to "recomputed or proven identical via content-keyed cache" |
| C9 | M399 compares nothing against 2.1; deep audit's chronological 1.8-vs-2.1 RMSE favours 1.8 | Keep M399's stance (loses by construction); mention the audit result only as descriptive |

## 6b. Research-director triage (Opus, high; brief < 2 KB; triage only, nothing applied)

Decision: **revise**, `needs_andrii_signoff: true`. The two audits agree with ruling B-prime and M399 v3 in substance, but v3 does not match the code on disk (no Ah producer; kWh/(5 Ah x V) would derive a "rated kWh", which the ruling forbids), so a **v4 spec is needed**.

| Topic | Director's call |
|---|---|
| Own ruling 3(a) ("union of bootstrap CI and method range") | **Amended**: report side by side as in M399 v3 and deep-audit F17 (a union of a coverage interval and a min-max scenario range has no probabilistic meaning). The amendment must be recorded before Andrii signs off |
| Deep audit "publish ~1.8 kWh" | Ruling wins: dashboard only after the M399 gates pass; article additionally needs the NaN check, an Opus audit and Andrii's sign-off |
| Self-audit "carry capacity as a 1.6-2.1 kWh bound" | B-prime wins (5.0 Ah documentary normaliser + window-fraction band); 2.1 and 1.8 kWh EFC scenarios are the two ends of that band |
| Lag (+/-2 s) | Largest single source of capacity uncertainty, and its range includes 5.0 Ah. It **cannot be identified from round-robin logs**; only the fast 3-PID Ready-mode run can bound it. Frozen, never tuned on evaluation data |
| Fold into M399 v4 | F16a registry (extends `constantProvenance`: class, basis, market/drivetrain applicability, verified flag, version, no automatic switch); F16d relabel; 5/10/15-pp windows and matched lag into the method-range list (allowed because no code exists yet); chronological folds in test (b); SoC=0 artefacts excluded from support bounds; descriptive pre-Ready zero-current check for F14; five-formula EFC/FCE/GTC table with raw Ah/kWh primary |
| Separate milestones | **M399a** = F16b (positive Ah discharge/charge on the same support as kWh; known-answer sign-crossing and gap tests; Ah totals checked against kWh/V; fix the "Ah throughput unchanged" row). Wording wave (reporting-only). N01-N03 before winter data (tooling fix, not a method change, not article-bound). GTR refresh after the offset decision. Inference sensitivities |
| Order | wording wave -> N01-N03 -> M399a -> M399 v4 -> GTR + F18 -> inference sensitivity -> F19 / N06 |
| Do now | F16b; F13 assumption registry (reporting-only); F17 + MDE beside "not established" (reporting-only); week-block bootstrap + CR2 (additive, article-bound); N01-N03; wording wave |
| Restrict claims only | F12 closure, F15 margins, F19 (censoring ledger, no survival models), F18, N06; keep the Sankey |
| External reference needed | F16c (full vs remapped SoC window), F12 DC-bus closure (needs HV instrumentation) |
| Not worth it | MCD outliers, EKF/UKF, RLS-1RC, GP interpolation, Willans/BSFC identification, full specification curve, N06 chronological false-alarm calibration |
| Over-reaching audit claims | Self-audit's 1.69 kWh and "+24 %" (drive-level dSoC regression is attenuated by SoC noise; a constant offset absorbs I2R loss of a different form): **do not quote**. F16c "determine full vs remapped window" is not identifiable. "EKF separates bias from scale" is not true here. F12's external reference needs HV instrumentation |
| Thesis relevance | Only capacity (A) and the dependence rows of C touch the buffer evidence (SoC band, |net|/gross, peak share). B, F15, F19, D should stay restricted, not expanded |
| Language | 2.1 kWh: "Nissan-published (AU e-4ORCE), basis undefined, FWD applicability unverified", never "not a published OEM spec"; FCE/GTC/C-rate "scale inversely with the selected reference"; residual ~ 0, r=0.9966, rank resolution and the M398 re-pin are never validation, error control or closure; lag/cadence spreads are scenario sensitivity, never a CI |
| Also | Renaming `efc_per100km` is blocked by ML16 / M326 (document the historical schema only); D4 stays a `data_health` flag (owner KPI rule wins); GTR interval/bracket goes beside the Sankey (owner decision wins) |

## 7. Proposed plan (order, agents, gates)

Numbers are proposals; renumber from the CHANGELOG head. One open method branch at a time; the session branch must first be restarted from latest `main` (`git fetch origin main && git checkout -B claude/next-milestone origin/main`, per CLAUDE.md) because PR #92 is merged.

| Phase | Content | Effort | Model / effort | Gate |
|---|---|---|---|---|
| **P0 truthful output** | N09 (2 sentences), D3 Hz (7), "linearly"->"inversely" (7), "not a published OEM spec" (6 sites), JSX 3435/11414/3944 archaeology, `?? 2.1` x10 fallbacks, M373 label, F25 sidecar + N08, F06 stamp split, calendar-correlation line (once located). Failing language/semantic-gate rule first for each (old wording becomes a ledger rule), then fix | M-L (about 4-6 days) | Sonnet medium; data-worker Haiku for verification | `release_check` green; dashboard render + commit with sources (Dashboard change rule); no numbers change |
| **P1 detector/arithmetic** | N01-N04 + known-answer fixtures, N06 wording, N07 tests into CI, D10 NaN-safe compare, D4 anomaly + continuity check, D7 UTF-8 guard, D11 `.gitignore`/move logs | M (about 3-4 days) | Sonnet medium; analytical-auditor Sonnet for N01-N03 | affected-output differences listed in CHANGELOG; monitors stay report-only |
| **P2a M399a Ah producer (F16b)** | Positive Ah discharge/charge on the same eligible intervals as kWh, known-answer tests (sign crossing, gaps), Ah vs kWh/V cross-check; decide master columns (new MD5, control build) vs per-drive sidecar | M-L | Sonnet medium; analytical-auditor Sonnet | totals independently checked; if master columns: 0 pre-existing-row diffs, MD5 before/after |
| **P2b capacity M399 v4** | Andrii sign-off on v3; v4 amendments per section 6b (registry, windows and matched lag in the method range, chronological folds in (b), pre-Ready zero-current check, EFC table); record the Director's 3(a) amendment first; A1 experiment by Andrii (also the only way to bound lag) | L | Sonnet medium for code; analytical-auditor (Opus) blind audit; research-director (Opus) decision | spec tests (a)-(i), control build diff within expected set, MD5 before/after, Andrii sign-off before article use |
| **P3 reliability** | F20 journaled publication + failure injection; N05 manifest-hash fingerprint; F11 replay package (scope first) | M-L (about 1 week) | Sonnet medium | injected failure leaves previous set intact; replay reproduces IDs/nulls/flags within tolerances |
| **P4 scientific boundaries** (Director order) | after P2b: archive `crossval` + refresh offset-dependent GTR blocks once (F18, F12 wording, Sankey stays); F17 scenario sensitivities + MDE beside "not established" (reporting-only); F13 assumption registry; week-block bootstrap + CR2 on thesis KPIs (additive, article-bound); F15 wording + margin declaration; F19 censoring/rejection ledger only (winter stays suppressed); N06 wording only | M-L (about 2-3 weeks) | Sonnet + analytical-auditor; Director per item | method changes need spec + blind audit + Director; dropped on Director's advice: N06 calibration, specification curve, EKF/RLS/MCD/GP/Willans |
| **P5 efficiency / hygiene** | profile the full workflow (baseline exists), per-drive cache + pool after Andrii amends the standing rule, fast gate tier, archive dead code, replace silent excepts (D8) | L | Sonnet; data-worker for timings | 0 cell diffs, MD5 unchanged, identical releases cold vs incremental |
| **P6 structure** | arrays registry package, stage DAG, layout, CHANGELOG split | L | Sonnet | only after the MIGRATION.md reproduction test passes |

## 8. Requires external reference / cannot be closed in this repo
- Generator/DC-bus physical closure (F12), BSFC/eta/auxiliary calibration (F13), external agreement target (F18), sensor-zero calibration (F14), full / accessible / SOH capacity (F16), SoC remapping (F16c), a gross 2.1 kWh with a hidden buffer <= ~15 % (cannot be tested from BMS data). Disclosure and restriction are implementable now; closure is not.

## 9. Decisions needed from Andrii
1. Sign off M399 spec v3 (and consider v4 amendments in 7/P2); the number M399 is a proposal.
2. Allow P0 now as a separate wording milestone ahead of M399 (recommended: removes misleading text immediately and de-risks M399).
3. Amend the "seasonal recomputed every ingestion" standing rule to allow a provably identical content-keyed cache.
4. F20: journaled swap now vs release directories after MIGRATION.md.
5. F11 replay scope.
6. D5/D6 (file key / timestamps) and D12 (raw/ out of git): recommended to defer.
7. Where the Ah throughput should live (master columns vs sidecar).
8. Record the Director's amendment of ruling 3(a) (side by side, not union) in `analyses/capacity_director_ruling_2026-10-11.md` before sign-off (not edited here).
9. CLAUDE.md "Open items" still lists `speedSplit` as having no auto-splice and five stale GTR blocks; the payload shows only `crossval` stale (not edited here).

## 10. Implementation status (updated 2026-10-11, after M405)
Merged to `main` (tags): **M399** wording wave (N09, D3, F16 wording, 10 silent `?? 2.1` fallbacks, F25 MC sidecar, N08); **M400** detectors N01-N03 (0 of 554 drives changed; unknown-state coverage reported); **M401** N04, N06 wording, N07, D4 odometer ledger + gate, D7 ratchet, D11; **M402** Ah-throughput sidecar (F16b, blind-audited); **M403/M404** capacity spec v4 steps 1-2 (additive `capacityBasis`, `CAP_AH_RATED`, tests (a)(b)(c)(d)(h), shadow eligibility 0 flips, exposure table, Director ruling, two blind audits that each found a real defect); **M405** N05 content-keyed fingerprint.
Found already implemented on disk (no work needed): D10 (`eligibility._true` is NaN-safe and stops on a flag disagreement); F18 residual (the stale `crossval` block already carries a dated status "not a validation of the current headline" and the dashboard says the two paths correlate through shared priors); F13 (the assumption registry already has class, verified flag, source, band and sensitivity for BSFC, efficiencies and P_aux; only a version stamp is missing, not worth a milestone); the "five stale GTR blocks" were one (`crossval`).
Pending owner decisions: commit 2 of the capacity basis (conditional GO from the Director, needs Andrii's recorded acceptance, the control build and the method-change list); F20 atomic release (journaled swap now vs release directories), F11 replay scope, amending the "seasonal recomputed every ingestion" rule (needed for F24 caching); the Ready-mode experiment is Andrii's task.
Not started: F06 stamp schema split (own spec), inference sensitivities (week-block bootstrap, CR2 on thesis KPIs, MDE beside "not established": method change, spec + blind audit), F19 censoring ledger, F17 scenario budget, performance work (profile first).
