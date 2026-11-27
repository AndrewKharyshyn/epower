# M779 spec: BMS-reported charge and discharge power limits versus pack temperature (new Thermal-tab chart, exploratory, auxiliary)

Rev 1. Committed BEFORE any result of this milestone exists. Owner request (Andrii, chat, 2026-11-27): "Perform the analysis of the BMS limits for battery charge/discharge depending on the pack temperature. A new chart to Thermal tab should be introduced as the new study." Wave E of the dashboard rework (memory `dashboard-redesign-waves-2026-11-27`).

## 0. What is already known (read from the repository, not re-derived)
- Channels (raw OBD csv, Car Scanner ELM OBD2): `[BMS] Input possible power` (the reported CHARGE limit) and `[BMS] Output possible power` (the reported DISCHARGE limit), in horsepower `(hp)` before the logger rename and in `(kW)` since 2026-09-30. Header inventory (this spec, headers only, no value read): hp pair in 256 raw files, kW pair in 228, none in 235 (of 719 OBD files; e4ORCE files excluded). M626/M627 (`S.headroomUtilization`, `compute_summary_arrays.py` 6690-6740) established: metric horsepower factor 0.73549875 (86.6758781031239 hp = 63.750 kW), 0.25 kW grid (unit gate passed), 63.75 kW (255 x 0.25) is a possible one-byte saturation (flagged, not identified), the Output limit is NOT constant in either era, the channel is sparse (about 1-2 % of ordinary BMS current/voltage density), alignment tolerance 2 s.
- The existing block reports utilisation (measured power divided by the reported limit). It does NOT show the limit itself against pack temperature; M140 named pack temperature and SoC as candidate drivers "not modelled, future work". The stage-MF spec (M457) is shelved and is not resumed here.
- Pack temperature channels: `[BMS] HV Battery Temperature Sensor 1..4`, `Intake Air Temperature`. The project has two pack-temperature definitions (T1 versus the four-sensor mean; the audit asked to reconcile the probe choice before a common scale).
- Era and temperature are confounded: the hp era is May to September (warm), the kW era starts 30 September, so the cold pack temperatures (below about 15 C) exist almost only in the kW era. A temperature effect cannot be separated from a logger-era or firmware effect where the eras do not overlap.

## 1. Constraints
- Wording: "BMS-reported limit", logged / app-calculated; never "capability", "derating", "protective limit", "the BMS reduces / limits power because of temperature" (a cause), never "measured"; no identified BMS threshold; the 63.75 kW value is "the highest value the channel reports (possible saturation)". Cold bins are exploratory.
- No published figure changes: `drive_master.csv` MD5 `d514d6009d6d9a0a168ad4fb09b9bb98` unchanged, `headroomUtilization` untouched, additive payload key `bmsLimitByTemperature` only.
- Statistics: calendar day is the resampling cluster; day-clustered percentile bootstrap (seed 42, 4000 draws); every estimate carries n (samples, drives, days); canonical-clean eligibility (`ens_outlier_v2` false) and the M626 header-based selection; no pooling of eras without saying so.
- Raw CSVs read-only. Privacy: aggregates only.

## 2. Data and definitions (frozen)
- Population: canonical-clean drives with a possible-power pair of either name (header-based, as M626). Each possible-power sample is aligned to the nearest pack-temperature sample within 2 s (M626 tolerance); unmatched samples are dropped and counted. Each sample's weight is its owned time: the interval to the next possible-power sample of the same drive, capped at G = 5 s (sensitivity 2 and 10 s).
- Pack temperature: primary = mean of the four pack sensors at the aligned time (a sample with fewer than four valid sensors is dropped and counted); sensitivity = sensor 1 only. Bins of 5 C: below 5, 5 to under 10, ..., 40 to under 45, 45 and above; the full observed range is always drawn (owner decision (e) of 2026-10-14: cold displayed when collected). Bin edges are display and analysis bands, not identified BMS thresholds.
- SoC: BMS SoC at the aligned time; bands as the regeneration programme (edges 40, 50, 55, 60, 63, 66, 69, 72, 100, explicit "below 40" row). SoC-standardised view: ONE fixed reference mix, the all-sample time-weighted SoC-band mix of the whole population (never per bin).
- Era: `hp` or `kW` by header. Unit gate (M626 R4): at least 99.9 % of converted samples on the 0.25 kW grid within 1e-6 kW; if it fails for an era, that era is not used and the failure is reported.
- Support floor per displayed cell (owner decision (d)): at least 200 samples, at least 10 drives on at least 5 days; cells below it are drawn as "not shown (support)" with their n, never as zero.

## 3. Estimands (pre-registered)
For each direction D in {charge limit (Input), discharge limit (Output)}:
- E1 (primary): time-weighted median of the reported limit (kW) per temperature bin, pooled over eras, with a day-clustered 95 % interval, n samples, drives, days; plus the time-weighted share of samples at the channel's highest value (63.75 kW) and the 10th percentile.
- E2 (co-primary, confounding control): the same median per temperature bin and SoC band, and the SoC-standardised median per temperature bin (weights = the fixed reference mix; bands missing in a bin are reported, and the standardised value is shown only if the covered share of the reference mix is at least 80 %). E1 and E2 are both shown; disagreement is reported, not tuned away.
- E3 (era control): E1 per era in the temperature bins where both eras meet the support floor (the overlap). Era difference per overlap bin with a day-clustered interval. Pre-registered rule: if the era difference in any overlap bin has an interval excluding zero AND exceeds 1.0 kW, the pooled cross-bin contrast is labelled "not separable from logger era" and the chart shows eras separately.
- E4 (profile, descriptive): the ratio of the bin median to the median of the reference bin (25 to under 35 C pooled), per bin, with a day-clustered interval. No change point and no onset temperature is estimated or named.
- Sensitivities (reported, never gating): T1 versus four-sensor mean; weight cap 2 / 5 / 10 s; matching tolerance 1 / 2 / 3 s; bin width 5 versus 10 C.

## 4. Decision rules (frozen before any result)
- D1 (display): the chart is shown iff (a) the blind audit reproduces every E1 cell median within 0.25 kW (one grid step) and every sample count within 1 %, and (b) the unit gate passes for each displayed era. If (a) fails the chart is withheld and the table is shown.
- D2 (reading ladder, per direction): "the reported limit differs between pack-temperature bins" is said only if at least two supported bins have non-overlapping day-clustered 95 % intervals in BOTH E1 and E2; otherwise "no difference between bins is resolved". If E3 flags era separation, the sentence is restricted to within-era bins. Never "decreases with cold" or "increases with heat": say "is lower in the {bin} bin than in the {bin} bin" with the interval.
- D3 (saturation): the share at the highest channel value is reported per bin; a bin where more than 50 % of the weighted samples sit at that value is labelled "limit mostly at the channel's highest reported value (possible saturation)"; no inference about the limit above it.
- D4 (cold support): bins below 15 C are labelled exploratory unless they meet the floor on at least 10 days; the number of days is printed in the bin.
- D5 (association language): any association is described as "associated with pack temperature, SoC and logging period moving together"; no causal or protection wording. Every figure is auxiliary and not an article figure.
- Falsification: "the reported limit depends on pack temperature" is falsified for a direction when, in E1 and E2, the interval of every supported bin median overlaps the interval of every other and the full range of bin medians is within one grid step (0.25 kW). "Era and temperature are separable" is falsified by the E3 rule above.

## 5. Gates
1. `drive_master.csv` MD5 unchanged; isolation diff: only the new `bmsLimitByTemperature` key and its stamp are added; no tracked frozen, summary or other payload file changes.
2. Known-answer tests (`tests/synthetic/`): planted step function of limit versus temperature recovered exactly per bin; SoC confounding planted (limit depends on SoC only, temperature correlated with SoC): E1 shows a spurious bin difference, E2 removes it; planted era offset: E3 flags it; saturation share recovered; support-floor suppression; hp to kW conversion on the metric factor; day-clustered bootstrap seeded and reproducible; matching tolerance and weight cap behave at their edges; the tool skips cleanly without raw files.
3. Every payload number is written by the script from the live corpus; the dashboard binds to `S.bmsLimitByTemperature` only (no typed number).
4. Blind audit (claim and data paths only) reproduces E1 per cell (median, n samples, drives, days), the saturation share and the era-overlap bins with its own implementation. Director decision. CHANGELOG entry with this spec's sha256 and the master MD5.

## 6. Display (after gates 1 to 4)
New Thermal-tab section "BMS-reported charge and discharge limits by pack temperature (logged / app-calculated)". One bound lead sentence per direction following the D2 ladder. Two aligned panels (charge limit, discharge limit): dot-and-interval per 5 C bin (E1), marker shape by era where eras are shown separately (E3), the value above each dot, n (samples, drives, days) beside it, a thin strip for the saturation share, an "SoC-standardised" toggle (E2), unsupported bins drawn empty with their n. Method note ("How we calculated it"): definitions, sensitivities, era overlap, support floors. Source tag "BMS-reported (logged)". Language rule with a ledger id added to `language_gate.py` for the forbidden wording above.

## 7. Out of scope
Utilisation (M626 stays as is), any change to the regeneration, energy or thermal analyses, a physical battery-limit model, identification of BMS thresholds, any article figure.

## 8. Questions for the Director
(a) Are E1 and E2 together an adequate defence against SoC and era confounding, or must E3 be primary? (b) Is the four-sensor mean the right primary pack temperature given the open probe reconciliation? (c) Are the support floor and the 80 % reference-mix coverage rule defensible for a sparse channel? (d) Is the saturation labelling (D3) and the reading ladder (D2) sufficient to prevent a capability or protection reading? (e) Any wording that conflicts with M626 or the language gate?
