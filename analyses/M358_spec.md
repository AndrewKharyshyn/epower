# M358 spec (Rev 1): C-rate risk map, A and kW as primary axes, C-rate secondary (audit F21.r1)

Status: work in progress, Director review pending. Presentation + one additive payload key. No new estimator, no headline figure.

## 1. Problem
`CRateRiskMap` (xtrail_summary.jsx, section "1 - C-Rate vs Battery Temperature Risk Map") plots only C-rate on Y. C-rate = A / (CAP_KWH*1000 / V_nom) and scales with the unverified `CAP_KWH = 2.1` (verified:false). The quantity actually logged is current (A) (and power derived from I x V); C-rate is a normalisation by an assumed capacity. Audit F21.r1: A and kW should be the primary axes, C-rate secondary.

## 2. Data (all from `drive_master.csv`, no raw pass, no master write)
Point set = exactly the existing `cRatePoints` set (464 rows: drive_type class present, a charge C-rate present, T1 present). Existing key `cRatePoints` stays byte-identical.
New key `cRatePointsAK`, rows `[T1_at_peak_Crate_C, C, class, A, kW, file]` in the same order as `cRatePoints` (T, C, class repeated so the chart reads one array and a control asserts the first three columns equal `cRatePoints`):
- `A` = max over channels (`eng_charge_peak_A`, `dual_peak_A`, `regen_peak_A`) of |A| for the channel whose C-rate is the point's C-rate (same sample as T1 pairing). Magnitude, charge direction. 0.1 A resolution (logged integer-rounded in part of the `raw/` re-exports, F03: up to ~0.5 A on ~100-200 A, below the plotted resolution).
- `kW` = |`peak_charge_kw`| (drive-level maximum charge power, `e['P'].min()`). This is NOT guaranteed to be the same sample as the peak current; the payload carries a per-corpus diagnostic: n drives, correlation(A, kW), and the distribution of kW*1000/A against `V_pack_median` (implied-voltage consistency). Missing `peak_charge_kw` -> null, point drawn only in the A view, counted in `nKwMissing`.
- Reference lines (today in C only: median peak ens-clean, pure-regen peak, charge peak): new `cRateRefLinesAK.lines[]` with `{kind, C, A, kW, drive}` computed from the same columns and populations as `_crate_ref_lines` (max lines take A and kW from the defining drive; the median line takes the median of A and of kW over the same ens-clean set). `cRateRefLines` stays byte-identical.
- Secondary-axis conversion: `cRateAxes.ratio = {C_per_A: median(C/A), C_per_kW: median(C/|kW|), spread: IQR and min-max of each}`; the secondary axis is the primary axis x the median ratio, labelled "approx. C-rate at the median pack voltage; per-drive ratio varies by +-x% (IQR)" with x from the payload (C/A per drive differs only through V_pack_median; the control reports the spread).
Everything computed by `tools/m358_splice.py` (additive leaf-level splice of the three new keys; `--check` writes `analyses/M358_check.json`, `--splice` writes). Also wired into `compute_summary_arrays` so a fresh build produces the same keys (single implementation function `_crate_axes(dm, arrays)`), and into the ingestion post steps list is NOT needed because the function runs inside the arrays build.

## 3. Chart
- Selector (3 buttons, default **A**): "Peak charge current (A)" | "Peak charge power (kW)" | "C-rate (assumed capacity)". Primary left axis = chosen unit; right axis = the other conversion: A or kW view -> C-rate secondary (ticks from the median ratio); C-rate view keeps the existing axis with A secondary. Axis bounds derived from the data with headroom (same rule as M58).
- Same points, colours, hover; hover shows all three values (A, kW, C-rate) and file date; ring rule stays "C-rate > 30" (stated), cold/heat zones unchanged (x axis unchanged).
- Reference lines drawn in the active unit from `cRateRefLinesAK`; labels state value in the active unit and the C-rate.
- Section intro and callout: rewrite the Y description to "peak charge current (A) [also shown as kW and C-rate]"; add "C-rate is a normalisation by the unverified CAP_KWH = 2.1 kWh; current (A) is the logged quantity; kW is current x voltage, reconstructed from the logged PIDs, not a measured power". Remove nothing else; the M58/M239 history text stays.
- No change to the 29 other "C-rate" mentions (they are separate figures/definitions); the Methodology "C-rate reporting" paragraph gets one clause pointing to the A/kW views.

## 4. Controls and tests
- C1: `cRatePoints`, `cRateRefLines` byte-identical before/after (canonical JSON); the first three columns of `cRatePointsAK` equal `cRatePoints`; every other top-level key byte-identical (deep-diff allow-list = the three new keys).
- C2 known answer (`tests/synthetic/test_crate_axes.py`): synthetic master with known A, C, kW, V -> rows, ratio and null handling exact; `C == A / cap_ah_est` within the master rounding for all 464 rows (reported, tolerance 0.05 C).
- C3: per row A is from the channel with max C (assert equal to argmax channel).
- JS: `test_crate_axes.js` (axis tick generation, unit switch, conversion monotone, null kW skipped) plus jsdom render of the three states.
- Gates: semantic gate A2 REQUIRED strings for the new wording, language gate RULES for any old wording replaced, release_check green.

## 5. Out of scope / caveats
- No change to what is plotted as T (x axis), to the point set, or to zone thresholds (external reference values, unchanged).
- kW is the drive-level peak charge power, not guaranteed co-timed with peak current (stated in the UI footnote with the correlation from the payload).
- A raw-pass kW-at-peak-sample variant is NOT built (would need raw frames, F03-sensitive); can be a later milestone if the diagnostic shows material disagreement.
- Article: no figure enters the article; no blind audit needed beyond the C1-C3 controls (no new estimator), Director decides whether an audit is nevertheless wanted.

## 6. Questions for the Director
1. Is kW = drive-level peak charge power acceptable as the kW axis given it is not guaranteed co-timed with the peak-current sample, with the diagnostic disclosed? Or require the raw-pass kW at the peak sample?
2. Default view A (recommended) vs kW?
3. Secondary-axis via corpus-median ratio (+- spread disclosed) acceptable, or draw the secondary axis only as tick annotations per primary tick?

---
# Rev 2 (Director: revise, applied)
Director answers: Q1 accept drive-level `peak_charge_kw` only if the axis itself says "drive peak charge power (not co-timed with peak current)" (not only a footnote); Q2 default view A (logged BMS-reported PID via OBD, no capacity assumption, no co-timing issue); Q3 corpus-median C/A accepted for the A view only.
Changes applied to Rev 1:
1. Convention fixed: C = A / cap_ah_est per drive, cap_ah_est = CAP_KWH*1000 / V_pack_median (per drive). Hence C/A = V_pack_median/(CAP_KWH*1000) and the secondary-axis spread comes only from V_pack_median.
2. Secondary axis: A view -> C-rate secondary from the corpus-median C/A. Pre-registered fallback: if the C/A IQR exceeds +-3% of the median, per-tick annotations replace the secondary axis. kW view: NO C-rate secondary axis (C/kW median ratio rejected: mixes non-co-timed samples); it may carry an A-equivalent axis at median V_pack_median labelled "approx.". C-rate view keeps its axis with A secondary.
3. Every C-rate axis/tick label, and the C-rate view title, carries "assumes CAP_KWH = 2.1 kWh (verified:false)". The ring rule is stated as "C-rate > 30 (assumed-capacity units)".
4. Wording: A is "logged (BMS-reported via OBD)", never "measured". kW is "derived as logged HV current x logged HV voltage (app-logged PIDs)" (the phrase "not a measured power" is dropped). kW axis label: "Drive peak charge power (not co-timed with peak current), kW".
5. F03 label "raw/ basis, provenance-sensitive (F03)" on the A and kW views. The rounding magnitude claim is not typed: it cites the F03 comparison output (`analyses/F03_originals/`) or is omitted.
6. Plausibility screens: rows of `cRatePointsAK` apply NO A/kW screen (they must equal `cRatePoints`, which has none); `cRateAxes.diagnostics` reports the counts of A > 300 and kW > 150 (the screens `_crate_ref_lines`-adjacent record code uses), so a reader sees whether any plotted point would be screened elsewhere. Reference lines in `cRateRefLinesAK` use the same columns/populations as `_crate_ref_lines` (no screen, as C).
7. Raw-pass co-timed kW variant trigger pre-registered: implied V = kW*1000/A outside [0.9, 1.1] x V_pack_median on more than 10% of drives -> open a follow-up milestone. The diagnostic block reports the fraction; this milestone does not build the variant.
8. Median reference line: median A and median kW are separate medians (not co-timed, not one operating point); labelled "median of per-drive peaks" per axis and never as an operating point.
9. UI text binds all counts to payload n (`S.cRatePointsAK` length, `nKwMissing`); no typed 464.
10. Controls added: C1 asserts `cRateRefLines.axis` unchanged (deep-diff allow-list = the 3 new keys); new JS test that kW-null rows are excluded from the kW-view axis bounds.
Status: Rev 2 applied; no blind audit required (no new estimator/headline; not article-bound). A Sonnet spot-check of `analyses/M358_check.json` C1-C3 is advised.
