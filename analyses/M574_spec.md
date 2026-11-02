# M574 spec Rev 1 (2026-11-02): additive payload block `cellSpreadStep` and a bound dashboard note (follow-up of M573)

Status: Rev 1, frozen before code. Base: `main` at M573 (`6d48fca`). Andrii, 2026-11-02: "yes, proceed" (the follow-up named in the M573 CHANGELOG entry and Director ruling). No ingestion:
`drive_master.csv` (MD5 `5556a0c6...`), `raw/` and `raw_manifest.json` untouched; the nine un-ingested Nov 1-2 files NEVER enter the payload.

## Scope
1. `tools/m573_cell_spread_step.py --splice`: runs the M573 analysis (items 1-5 and 4b, no external files) and writes the additive payload block `cellSpreadStep` (+ stamp) into
   `summary_arrays.json` by the leaf-level splice pattern used by `windowUse` / `signalValidity` (assert: no other key and no other stamp changes). Check JSON: `analyses/M574_check.json`.
   Ingestion stage `cell_spread_step` (after `window_use`): refreshes the block at every ingestion; the step date is FIXED at 2026-10-01 and never re-picked.
2. Confirmatory block (pre-registered in M573 Rev 2): drives dated after 2026-10-17 are scored against the pre-step model (y ~ T + I + SOC fitted on drives before 2026-10-01):
   mean residual with a day-clustered t(G-1) interval, and the post-step months slope (drives from 2026-10-01 on, same covariates). It is evaluable only with >= 10 drives on
   >= 5 days after the cutoff; otherwise `status: awaiting data` and no number. Outcome labels (script-written, not interpretation): `raised level, flat slope` (residual interval
   above 0 and slope interval spans 0), `back at pre-step level` (residual interval spans 0), `continued rise` (slope interval above 0), `mixed`.
3. Dashboard: a short note bound to `S.cellSpreadStep` beside the cell-spread trend (`CellSpreadStepNote`, `data-csstep-note`): model table (released, step, step + SOC + rest, month fixed
   effects: estimate, interval, AIC, day-blocked CV RMSE, n, days), the equal-length and cold-start rows, the confirmatory status and every limit. Plus a wording-only cross-reference in
   `spreadConclusion().caveat` generated from the block (no typed number).
4. Language gate: new rule `M573-cell-spread-step` (forbidden: detected / confirmed change-point, step at October 1 as fact, imbalance growing, cadence or balancing ruled out, measured
   degradation) with its old/forbidden wording; test `tests/synthetic/test_m574_wording.py` (fires on targets, silent on the dashboard wording).

## Required wording (Director, M573)
"within the 5.1-month window, a level shift around late September / early October (date chosen post hoc) fits better than a steady linear trend (model-derived); the steady trend is
not established once the shift is allowed; degradation and real imbalance growth are neither established nor excluded; the cause is unidentified." Step size only as "conditional on a
post hoc date, not adjusted for selection". The window length and every number are read from the block.

## Known answers and gates
- KA1-KA5 of M573 stay (`test_m573_cell_spread_step.py`). New: KA6 confirmatory on synthetic data (raised level + flat slope; back at pre-step level; continued rise; awaiting data below the
  support floor). KA7 the spliced block equals the M573 result JSON leaf for leaf on the shared quantities (payload tie-out to the audited numbers). KA8 splice is additive (deep diff).
- A0 MD5 and ML16 unchanged; A1 the numbers in the block are the ones the M573 blind audit reproduced (tie-out), so no new blind audit of values; the display wording follows the
  Director ruling and `semantic_gate.py` A2 must stay green; A2 jsdom view test `test_cell_spread_step_view.js`; A3 `release_check.py` green; A4 no article figure.

## Limits carried into the block (all printed)
Step date post hoc (data-driven scan best 2026-09-27); AIC and intervals ignore date selection and multiplicity; residual lag-1 autocorrelation about 0.27; late window 8 days, 23 week
clusters; month fixed effects fit as well as the step; cold-start early-window intervals are wide (not detected, not excluded); polling regime reported, not excluded; cell-level
temperatures are not logged; one half-season only.
