# M348 spec (rev 1): Compare numeric-x parity (audit F11)

Status: work in progress, Director review pending. Pre-registered before any code change.

## 1. Problem (verified on disk this session)
`CmpLines` (`xtrail_summary.jsx`) places points by array INDEX (`X(i)=L+i/(n-1)*pw`) and takes the x labels from the "all" cohort only.
1. WarmupCurve grid (km) = 0, 0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 5, 6, 8 is drawn equispaced; the single-cohort chart uses a true km axis (`xS`). Compare and single views disagree on the shape of the same curve.
2. BatteryThermalCurve (minutes): Shoulder has 6 points (0-50 min), All/Warm 19 (0-180). Index alignment is correct only because the shorter series is a prefix; nothing enforces it.
3. WarmupCurve pooled y = n-weighted mean over `Object.values(d.classes)`. The payload carries the legacy alias `city` with points identical to `urban` (verified: identical in all 3 cohorts), so Urban is counted twice (script `tools/m348_warmup_pool_check.py` -> `analyses/M348_warmup_pool_check.json`: maximum effect on the pooled curve 0.43 degC All, 0.30 degC Warm, 0.0 Shoulder). `highway` is empty (null points). Classes may be `null`.
4. The pooled value is an n-weighted mean of per-class MEDIANS. It is not a pooled-sample median and the payload does not allow recomputing one. The chart title/legend do not say so.
5. All-zero / empty class arrays render as zero bars in Compare (M341 note, SpeedDist Shoulder "highway"): "not observed" must be handled in the Compare renderer.

## 2. Scope (stop condition)
Compare renderer only (`COMPARE_SPECS` kind `lines`, `CmpLines`, and the `bars` zero case). No payload change, no pipeline change, no new estimand, no number changes in single-cohort views. The deterministic effect of item 3 is a displayed-value change of the Compare Warm-up curve (at most 0.43 degC); it is a defect repair (alias double count), disclosed in the CHANGELOG.

## 3. Design
- `spec.pts(d)` returns `[{x, y}]` with a numeric `x` (km, min) for numeric axes; for ordinal-bin charts (TorqueBySpeed speed bands, RpmDistribution bins) `x` is the bin label and the axis stays ordinal.
- `CmpLines` outer-joins the series by `x` (numeric: tolerance 1e-9; ordinal: label), keeps a series gap where a cohort has no point (existing gap marker and segment-break logic retained), and positions numeric axes by value (true scale, min..max of the union), ordinal axes by rank in the union order.
- WarmupCurve pooling: canonical classes only. Alias keys are dropped by `clsKey` (`city` -> `urban`) with first-wins de-duplication; `null` classes skipped. Weight and rule unchanged (n at that km, fallback 1).
- Wording: the Compare WarmupCurve title and note state "n-weighted mean of per-class medians (a weighted summary of class medians, not a pooled-sample median)". Wording passes a Director string review; the old unlabelled title goes into `language_gate.py` RULES with M348 if it becomes forbidden.
- Operating-temperature reference (`operatingC`, 80 degC level) is drawn as a separate dashed grey reference line labelled as a reference, not as a series, not in the legend of observed cohorts, and not included in the y-range logic as an observation.
- `bars`: a category whose values are all zero/empty for a cohort and whose cohort has no drives for that class is drawn through `NotObservedRow` / the existing hatched marker. Rule: not-observed = payload value null OR (all values of the array for that cohort-class are exactly 0 AND the count field, where present, is 0). Where the payload has no count field, an all-zero array is NOT reinterpreted (no new inference); only the existing null handling applies, and the case is listed in the check JSON.

## 4. Tests (jsdom, `validate_jsdom.js` / `test_cold_fixture.js`)
1. WarmupCurve Compare: x positions proportional to km (pixel distance ratio between any two points equals their km distance ratio within 1e-6).
2. Unequal x: synthetic fixture where Shoulder has a shorter, offset grid; the union x is plotted, each series at its own x, gaps preserved.
3. Alias: fixture with `urban` and identical `city`: pooled value equals the canonical-only value (known answer from the check script).
4. Reference line present exactly once, not in series list.
5. All-zero class in a fixture with count 0 renders `data-not-observed`.
6. Existing 10-tab validation, 0 console errors, semantic gate, release_check green.

## 5. Process
Director review (Opus) of this spec -> implement -> check JSON written by script -> rebuild -> gates -> blind audit NOT required (no new estimate; renderer and alias repair, deterministic known-answer) unless the Director says otherwise -> CHANGELOG via `tools/changelog_draft.py` -> release_check -> commit (jsx, summary_arrays.json, cohort_arrays.json, html together) -> PR -> SendUserFile render.

## Rev 2 (Director review: verdict "revise"; all changes accepted)
Evidence added to `analyses/M348_warmup_pool_check.json` (script-written): single-view WarmupCurve reads only `urban/mixed/mixed_highway/highway` (no iteration over `classes`, `city` never drawn), so the single-cohort view has no alias double count and "no number change in single views" holds; the Compare pool is the only affected site. Fallback-weight-1 points: 0 in all/warm/shoulder (the tooltip flag is therefore a guard, tested with a fixture). SpeedDist Shoulder `highway` is an all-zero array and SpeedDist carries no count field.
1. Pooling note must state that weights are drives per class at each km, so the class mix changes along the km axis (short drives drop out). Points that used fallback weight 1 are flagged in the tooltip.
2. Ordinal union order comes from the canonical bin order (payload `bins`/`zones` of the "all" cohort, else the spec's fixed list), never first-seen order. Test: cohorts with different subsets of bins.
3. Not-observed rule: null, `[]`, NaN and non-numeric arrays are treated as null. An all-zero array with no count field is NOT reinterpreted: it stays a zero bar (jsdom test asserts not hatched) and is listed in the check JSON. The M341 SpeedDist Shoulder `highway` case stays UNRESOLVED; the follow-up is a payload count field, not renderer inference.
4. The reference line (80 degC) is clipped/annotated and does not enter the y-range; label: "reference level 80 degC (not observed data)".
5. Process: audit_required = true, narrow scope: a blind Sonnet reproduction recomputes the canonical-only pooled curve from `cohort_arrays.json`, confirms alias identity and compares with the rendered Compare values; stop there.
6. Wording (Director): title "... (n-weighted mean of per-class medians)"; note "weighted summary of class medians, not a pooled-sample median; weights = drives per class at each km; alias classes counted once". Forbidden: "median warm-up curve", "pooled median" for the pooled line, "measured", "correction of results", an unlabelled "average warm-up" title (added to `language_gate.py` RULES with M348). CHANGELOG states: defect repair, legacy alias city==urban counted twice in the Compare pooled curve; max displayed change 0.43 degC (All), 0.30 (Warm), 0 (Shoulder).
