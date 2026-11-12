# M624 pre-registered spec (Rev 0): coolant / oil warm-up chart and its text (work item W1-03 of the 2026-11-11 self-audit)

Status: Rev 0, written BEFORE any M624 result exists (2026-11-12; master 665 drives, MD5 77bbe275f8c22eaf62d8636867764af3; builds on M623, PR 303: the last curve bin is now '600-900' s and per-bin drives and days exist). Needs a Director review (`research-director`) before any code; a blind audit of the new payload leaves and a Director decision after. Display and wording change plus additive payload leaves; no new estimator, no article figure.
Wording: coolant and oil temperatures are logged / app-calculated, never "measured" (Car Scanner ELM OBD2 logger); the curve is a descriptive median over cold-start drives; later bins hold only drives that ran that long (survivors).

## 1. Defects (read from `xtrail_summary.jsx` ThermalWarmupLag, ~9534-9650)
1. The x axis is categorical: `xB(i)` places bins at equal spacing, so the 0-30 s and 420-600 s bins are the same width (non-proportional time axis).
2. `line()` drops null bins and joins the neighbours across the gap (a gap is drawn as a trend).
3. The caption calls the vertical gap between the curves "the coolant-oil thermal lag"; the lag in this block is a time quantity (oil_t70 - coolant_t70, seconds); the curve gap is a temperature difference.
4. Tones: `tone="measured"` on the lag and `EvidenceBadge status="measured"`: coolant and oil are logged/app-calculated.
5. No per-bin support is shown (n drives, IQR); bins with few drives look as firm as the rest.
6. Two cold-start definitions are not stated in the titles: the lag/curve block uses coolant start < `coldStartMaxC` (60 C); other thermal blocks use other thresholds.
7. "steady-state offset" is `median(coolant - oil)` while coolant >= 80 C; the row label does not say so.
8. "MEDIAN OF REACHERS ONLY" rows show a censoring-biased statistic as a headline panel while `thermalSupportLedger.timeToThreshold` already carries the Kaplan-Meier median with a day-cluster CI for the cohorts all / warm / shoulder.
9. The caveat says "Nothing below X C is logged, so these are mild-ambient cold-starts", which the payload range (`S.ambientTable.rangeC`, lowest start ambient now below 0 C in the Cold cohort) no longer supports as a general statement.

## 2. Changes (pre-registered, no tuning after the result)
Payload (script, additive leaves in `_thermal_warmup_lag`; cohort copies via `tools/regen_seasonal_raw.py`, producer of the cohort copies; splice through the M623 pattern with pinned leaves): per bin p25 and p75 of the per-drive medians (coolant and oil), next to the M623 `NDrives` / `NDays`. Support floor for display: a bin is "supported" when n >= 10 drives on >= 5 calendar days (the project cohort floor); the flag is script-written (`coolantSupported`, `oilSupported` arrays).
Chart: (a) x position proportional to elapsed seconds at the bin mid-time (the last bin mid-point 750 s); (b) the polyline is split at null bins; (c) unsupported bins are drawn as hollow markers without IQR; supported bins carry an IQR whisker; (d) the caption reads "coolant minus oil, temperature difference (C), median per time bin; later bins contain only drives that ran that long"; (e) tone 'derived' and badge 'derived' for the logged/app-calculated temperatures; (f) the chart title and the block header state "cold start = coolant at start below {coldStartMaxC} C" from `coldStartMaxC`; (g) the offset row reads "coolant minus oil while coolant >= 80 C (median, IQR)"; (h) the reachers-only panel is replaced by the Kaplan-Meier median and its 95 % day-cluster CI from `thermalSupportLedger.timeToThreshold.cohorts[cohort][flow][threshold].median` where the cohort exists (all, warm, shoulder); for Cold, which has no ledger entry (UI-04), the panel states "Kaplan-Meier median not computed for this cohort" and shows the reachers-only value ONLY with the existing label; (i) the stale caveat sentence is derived from `S.ambientTable.rangeC` and the Cold cohort support fields, with no literal temperature.
Language gate: the OLD wordings are added to `language_gate.py` RULES with this ledger id ('the vertical gap between the curves is the coolant-oil thermal lag', 'steady-state offset' without its definition where it appears as a row label is NOT banned; only the 'thermal lag' attribution of the curve gap, and 'so these are mild-ambient cold-starts').

## 3. Known-answer tests
jsdom: x pixel of each bin is proportional to elapsed seconds (a synthetic payload with bins at known mid-times: positions within 0.5 px); a null bin splits the polyline into two `polyline` elements; a bin below the floor renders a hollow marker and no whisker; the caption text; the panel prints the ledger's KM median and CI for the all cohort (equality with the payload) and the 'not computed' text for cold. Python: p25/p75 per bin for a synthetic drive set with known medians; the support flag at n = 9, 10 drives and at 4, 5 days.

## 4. Isolation
Payload diff limited to the new per-bin leaves in `thermalWarmupLag.warmupCurves` and the four `seasonalCharts.charts.ThermalWarmupLag.data.*` copies (additive); every existing leaf (medians, NDrives, NDays, time-to-threshold, lag, offset) byte-identical; `thermalSupportLedger` unchanged. Master MD5 unchanged.

## 5. Acceptance and falsification
Known-answer tests green; isolation diff as above; language gate and `semantic_gate.py` green; jsdom text equals payload; blind audit reproduces p25/p75 and n for every bin from the raw files with its own script (the open M623 observation, auditor coolant median 39.5 vs payload 40.0 in the 30-60 s bin, is reconciled FIRST: the audit states which population rule explains it; if the pipeline's rule is the defensible one the observation is closed, otherwise the difference is reported to the Director before any display change). The change is rolled back if any existing leaf moves or the audit cannot reproduce a bin.

## 6. Out of scope
Cold-cohort Kaplan-Meier (UI-04, needs its own spec); table-to-chart conversions of the time-to-threshold tables (UI-05); gap-cap sensitivity (UI-06).
