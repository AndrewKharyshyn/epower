# M597 spec (Rev 1 after Director review; Rev 0 pre-registered before any result): audit D2, highway share scope (joint vs conditional)

Status: Rev 1 incorporates the Director's six required changes and optional items; no result has been computed. No result has been computed. Owner request: Andrii, chat 2026-11-07 ("Continue as you suggest").
Source: independent audit (`xtrail_epower_independent_audit.pdf`, defect D2).

## 1. Problem
`deficit_80_120_pct` (payload `deficitMeanPct`) divides the seconds with engine rotation and battery discharge inside 80-120 km/h by ALL
eligible band seconds (`compute_drive_summary_v6.py` lines ~816-831; `eng_on = eng_rpm > 400`, discharge = `Id > 0`). Short labels in the
dashboard can be read as "share of the time the engine was turning". These are two different quantities. Today only the first exists.

## 2. Estimands (names are fixed here; payload keys are new, existing keys are NOT renamed)
Per drive d, with band seconds B_d (speed in [80,120]), engine-on band seconds E_d (B and rpm > 400), and engine-on discharging band seconds
D_d (B and rpm > 400 and Id > 0), all as sums of the same per-sample dt used by the existing column:
- Joint share J_d = D_d / B_d (existing quantity; label "battery supplying power while the engine turns, as a share of all 80-120 km/h time").
- Conditional share C_d = D_d / E_d (new; label "share of engine-on 80-120 km/h time in which the battery was supplying power").
- Engine-on share of band time R_d = E_d / B_d (new; context, so J = R x C is visible).
By construction J_d <= C_d <= 1 and J_d = R_d x C_d. The identity holds per drive and for time-pooled values only; for per-drive MEANS mean(J) != mean(R) x mean(C) and the dashboard must not imply it. The existing column alias is `engon_dis_share_80_120`. These are control-strategy observables of logged signals; they say nothing about generator
limits or saturation (M41 wording stays).

## 3. Population and eligibility
- Joint: unchanged. Canonical-clean drives with `deficit_80_120_valid` (B_d >= 120 s, M14). n = 112 on the current corpus (check, do not type).
- Conditional and R: the same drives AND E_d >= 60 s (floor pre-registered here; the number of drives lost to the floor is reported, with the
  count of drives excluded because E_d = 0 and the count with R_d = 1). J and R are ALSO reported on this conditional population so J, R and C
  refer to the same drives; J on the full 112 stays as the existing headline. No other eligibility change.
- Reported per estimand: n drives, n calendar days.

## 4. Data path (no hand edit of the master)
`drive_master.csv` has B_d and D_d (`band_80_120_s`, `deficit_80_120_s`) but NOT E_d. E_d is computed by a new tool `tools/highway_share.py`
that reuses the pipeline's per-sample frame preparation (same loader, same dt, same eng_on and band masks) over `raw/`, and writes a sidecar
`highway_share.csv` (file, B_s, E_s, D_s) in the style of `ah_throughput.csv`. `drive_master.csv` is NOT written. Reconciliation gate: the
E_s uses the exact mask `eng_rpm.fillna(0) > 400` and the same NaN handling of `Id` (compute_drive_summary_v6.py lines 722 and 815-819); the sidecar B_s and D_s, after the same `round(., 1)`, must equal the master's `band_80_120_s` and `deficit_80_120_s` for every drive with ZERO tolerance; any mismatch fails the
tool. This proves the new E_s comes from the same frame as the published columns. The tool joins the ingestion stages (new drives get a row).

## 5. Method
- Primary: per-drive means of J_d, C_d, R_d over eligible drives (the existing headline convention), 95% interval by day-clustered percentile
  bootstrap (calendar day = cluster, seed 42, 4000 draws).
- Secondary (reported next to it, always labelled "time-pooled"): pooled J = sum D / sum B and pooled C = sum D / sum E, same bootstrap. The audit's
  quoted conditional figure is of this pooled kind; both kinds are shown so the reader is not left to guess which one is meant.
- Method disagreement (per-drive mean vs pooled) is reported, never tuned to agree.
- All quantities are computed from seconds, not from the rounded per-drive percentages.
- Sensitivity (not a gate): E_d floor 30 s and 120 s (the floor is new); engine-on threshold 300 rpm instead of 400 (owner decision g); B_d >= 300 s.
- Paired difference C - J = C(1 - R) >= 0 per drive, so it excludes 0 whenever any R < 1 (degenerate). Materiality margin pre-registered: the split
  of the two labels ships as a new figure only if the lower 95% bound (day-clustered, per-drive mean, primary) of C - J is >= 2 percentage points.

## 6. Known-answer tests (`tests/synthetic/test_highway_share.py`, written before the tool)
1. Audit fixture: 100 s in band, 40 s rotation, 20 s discharge while rotating -> J = 20 %, C = 50 %, R = 40 %.
2. Discharge while the engine is off (rpm <= 400) must not enter D or E.
3. Samples outside 80-120 km/h must not enter B, E or D (edges 80 and 120 inclusive, as in the existing mask).
4. E_d = 0 -> C undefined (None), drive excluded, counted. E_d < 60 s -> excluded by the floor.
5. Non-uniform dt: seconds are dt sums, not sample counts.
6. Day-clustered bootstrap known answer: two days with equal weights.

## 7. Dashboard
Wording and bindings only; no tab, order, button or selector change (owner rule 2026-11-06). The existing highway block states the joint share
under its precise name and shows the conditional share and the engine-on share beside it, all from new payload keys `highwayShare.*`
(estimate, 95% interval, n drives, n days, per-drive and pooled). The short labels at the three sites named by the audit are replaced by the
joint-share wording; the "zero screened events" statement is bound to the screened-drive count (`saturCoverageN`), not 632.
Language: "estimated", "logged", never "measured"; not evidence of generator saturation.

## 8. Accept / reject
- Accept to display if: fixture tests pass; sidecar reconciles with the master (0 mismatches over all eligible drives); blind audit reproduces J and C per drive within 0.1 percentage point; Director go.
- Reject / do not display the new figure if: reconciliation fails, the blind audit cannot reproduce within tolerance, or the margin decision (lower bound of C - J >= 2 pp) changes under any sensitivity ('flips the reading'; reported to the Director).
- Sanity check, NOT a gate: pooled J vs the audit's 48.9 % and pooled C vs 49.9 %. Record the audit's corpus and n; if the corpus differs, report the gap and do not fail. Audit figures are never typed into the repo.
- Falsification / fallback: if the lower bound of C - J is below 2 pp, only the naming fix ships (joint-share wording, R shown), with no conditional headline.
- Every displayed conditional figure states whether it is a per-drive mean or time-pooled; wording: logged-signal control observable, estimated, not saturation.

## 8b. Separate wording ledger id
The `saturCoverageN` rebinding (screened drives, not 632) is its own wording defect: ledger id M597-w1, with a `language_gate.py` rule for the old wording.

## 9. Article restriction
Not article-bound. No article figure from this without the Opus audit and Andrii's sign-off (CLAUDE.md).
