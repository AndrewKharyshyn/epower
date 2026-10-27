# M521 spec (Rev 1, DRAFT for Director review): engine-on time-base mapping (audit 2026-10-26, time-base follow-up; M520 Part C)

Status: PRE-REGISTERED DRAFT, 2026-10-27. Owner: Andrii (chat, 2026-10-27: "continue as you suggest"). Scope: a mapping table and, only after the ruling, wording edits that name the base. NO new estimate, NO change to any payload value, NO dashboard figure change; wording edits go through `language_gate.py`.

## 1. Question

`analyses/M520_timebase_inventory.json`: 23 lines of `xtrail_summary.jsx` quote engine-on time or hours, 17 name no base on the same line. At least three bases coexist in the payload; a reader can compare numbers that are not on the same base.

## 2. Bases seen before this spec (descriptive totals only, read from `summary_arrays.json`, no outcome statistic)

| Base | Producer | Rule | Total |
|---|---|---|---|
| B1 `rpmDistribution` | `compute_summary_arrays.py` ~4580 (`rpm_hist`) | 1 Hz grid, duration-weighted, rpm >= 300 (`engineOnThresholdRpm`); bins[1:] summed | 99.867 h of 230.506 h gridded (engine-off bin 130.639 h) |
| B2 `engineRuntime.totals` (M512) | `compute_summary_arrays.py` ~917 | RPM-supported intervals, eng_rpm > 400; on-time inside supported time | supportedOnHours 97.5425 h of 229.5476 h supported; 232.6344 h elapsed |
| B3 duration-scaled imputed (M512; `legacyEngineOnHours`) | same | B2 on-share applied to the unsupported time | 98.3732 h |

B1 vs B2 differ by 2.3 h (2.4 %) with a different threshold (300 vs 400) and integration (grid vs interval). Whether the whole gap is the threshold is NOT yet shown; this spec tests it (section 3 step 3).

## 3. Method (deterministic, no new estimator)

1. For each of the 23 lines: line -> bound `S.*` / `R.*` key (or hard-coded literal, flagged) -> producer function -> denominator definition (B1, B2, B3, or other: name it). Output `analyses/M521_mapping.json`, script `tools/m521_timebase_map.py` (extends `tools/m520_timebase_inventory.py`).
2. Scope widened: rendered tab dumps and `summary_config.json` strings, not only `xtrail_summary.jsx`.
3. Reconciliation check: recompute B1 on-hours with the threshold set to 400 on the same grid from the per-drive histograms (or state that the stored histogram edges cannot do it, then leave the 2.3 h unexplained and say so). Accept: gap closed to within 0.5 h, or reported as not explained.
4. Blind check: `analytical-auditor` receives only the line list and the payload path, produces its own mapping for 6 lines (9609, 9611, 12080, 12010, 12014, 10983 plus the two M512 lines); disagreement is reported, not tuned.
5. Director ruling decides which lines get a base named and which wording (e.g. "of engine-on time (rpm >= 300, 1 Hz grid)").

## 4. Falsification / stop

- A line whose base cannot be identified from code: left unchanged, listed as unresolved.
- Any proposed edit that changes a displayed number: out of scope, stop.
- Lines 9609/9611 compare a per-drive median (load-point share) with a pooled share: the edit may only add the base, not restate the contrast.

## 5. Language

Allowed: "engine-on time (rpm >= 300, 1 Hz grid)", "RPM-supported engine-on time (eng_rpm > 400)". Not: "engine runtime" without a base, "fuelled" for rpm-only bases, "measured" engine time (rpm is logged).

## 6. Gates

py_compile, `node build_html.js`, `node validate_jsdom.js`, `semantic_gate.py` (language rules, old wording added as rules with this ledger id), `python release_check.py`, CI unit list; CHANGELOG entry M521; spec SHA-256 recorded before the mapping run.

## 7. Rev 1.1 (2026-10-27): Director review (verdict "revise"); sections 3-4 are superseded where they differ

- **Step 3 re-posed.** First sub-step, before any computation: read and record the stored `RPM_HIST_EDGES` and their closure convention and declare the reconciliation feasible or infeasible. The edges are [0, 300, 1400, ...]; 400 is not an edge, so a threshold-only recompute is INFEASIBLE from stored data. No raw or 1 Hz re-integration (new computation, out of scope). The gap is decomposed and reported in `M521_mapping.json` only: (a) threshold term = not separable (bound: the 300-1400 bin hours); (b) denominator / support term: gridded vs supported vs elapsed hours; (c) residual integration = remainder, unexplained. Comparison pairs pre-registered: B1 vs B2 and B1 vs B3. The 0.5 h tolerance is dropped; "closed" is not claimed. A remaining difference is listed as an unresolved time-base difference.
- **Step 4 re-posed.** Blind sample = 8 author-listed lines (9609, 9611, 12080, 12010, 12014, 10983, 12076, 12119) + 3 lines drawn at random (numpy `default_rng(42)`, seed recorded before the run) from the lines that name no base + 1 string from `summary_config.json`. The auditor gets the text and the payload path, no B-labels. Agreement reported as k/n.
- **Step 1.** Hard-coded literals are flagged and listed, not edited, in M521.
- **Language.** B3 = "duration-scaled imputed engine-on time"; rpm is logged and the 300 rpm rule is an engine-off proxy (owner decision g); never "measured", never "fuelled" for rpm bases, never "engine runtime" without a base, never "corrected" for a wording edit. Lines 9609/9611: add the base only; "per-drive median" vs "pooled share" stays explicit; no contrast restated. Old wording enters `language_gate.py` with ID M521; allowed phrases must not trip context rules.
- Spec SHA-256 is recorded before the mapping/decomposition run (and in the CHANGELOG entry). No Andrii sign-off required (no article figure).
