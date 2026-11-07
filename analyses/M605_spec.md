# M605 spec (Rev 1 after Director review; Rev 0 pre-registered before any result): fueled, high-SoC, cold-coolant, pack-neutral engine context (independent audit, roadmap row "Cold engine context and fuel")

Status: Rev 1, 2026-11-07, written before any code or result; Rev 1 applies the Director's nine required changes (section 0, which supersedes any conflicting clause below). Owner request: Andrii, chat 2026-11-07 ("continue"). Source: `xtrail_epower_independent_audit.pdf`, section 04
("Cold, high-SoC engine activity: at SoC >= 68 %, coolant <= 60 C, RPM >= 500 and app fuel >= 1.5 L/h, four >= 10 s intervals show <= 3 A charging; one ~26 s interval stays
within +/- 3 A at about 4 km/h ... A candidate fueled, pack-neutral context ... Traction, auxiliary use and heat can overlap") and the roadmap row ("Promote a fueled,
high-SoC, low-pack-charge candidate with supported seconds and overlap states ... Treat motive as unknown"). The audit's counts are a sanity target, never a gate and never typed into the repo.

## 0. Rev 1 (Director REVISE, frozen; supersedes conflicting clauses below)
1. Rotation threshold. The M559 rule is rpm > 400 (strict). The base qualifying rule uses rpm >= 500 (the audit's value); rpm > 500 and rpm > 400 are sensitivities. The
   reconciliation test uses rpm > 400 strict on both sides.
2. Cadence. M559 strata (fast, slow, slow_fuelValid = slow-polled drives with a usable fuel rate, unknown; regime from `cadence_regime.csv`) are kept apart. Every count, support label and
   rate is reported per stratum and nothing is pooled. Support is judged per stratum.
3. Forward fill. Each interval carries the number of REAL (unfilled) 1 s bins per channel (rpm, fuel rate, current, SoC). A pre-registered sensitivity requires a real sample of rpm, fuel
   rate and current in every second of the run (filled seconds dropped), at the same 10 s minimum.
4. Grid pins (exact audit). Grid = M559 `_grid`: speed priority, `resample("1s").mean()` (left-closed, left-labelled, origin at midnight of the first sample's day), forward fill limit 3.
   A run is consecutive grid seconds (index step exactly 1 s); any non-qualifying or NaN second breaks it; no run crosses a drive. Sign: discharge-positive current I; pack-neutral = |I| <= 3 A;
   I == 0 counts as pack-neutral with sub-field "zero" (neither charging nor discharging). Speed bands: standing speed < 5, low 5 <= speed < 30, moving speed >= 30 km/h (a NaN speed is its own band
   "unknown"). Calculated-load bands: < 8 %, 8 <= load < 30 %, >= 30 % (NaN = unknown). rpm bands: [500,1000), [1000,2000), >= 2000. Coolant bands: <= 40 C, (40,60] C. Fuel-rate bands:
   [1.5,3), >= 3 L/h. Time since the first rotation: seconds since the first grid second with rpm > 400 in the drive, bands < 300 s and >= 300 s.
5. Support floor counts only interval-bearing drives and days (never fragments). Sensitivities are one at a time, not factorial.
6. The conservative flip rule stays. A relaxed setting that reaches support is reported and never promoted. Falsification reads "not established".
7. Conditional rate: kept, computed only for a supported stratum, with the confounding stated (speed and load; warm-coolant seconds at >= 1.5 L/h are mostly driving; coolant 60-80 C is excluded
   and stated). The cold and warm shares are reported separately, each with its day-clustered interval and n; no difference, no "versus", by speed band when n allows.
8. Display rule, pre-registered here: if no stratum is supported, the result stays in the payload and analyses, with at most ONE line in the Fuel tab giving the counts ("candidate, not
   supported": intervals, seconds, drives, days per stratum); no table, rate or paragraph. If a stratum is supported: one short paragraph, the overlap-state table and the conditional rate.
9. Limits and language-gate rules: |I| <= 3 A is about +/- 1 kW net, not zero flow, and means the generator output roughly balances traction plus auxiliary load, not that the generator is idle.
   The M559 2 A deadband count is reported beside the 3 A count for comparability. Forbidden as findings (language-gate rule M605): "pack-neutral mode", "warm-up mode", "heating mode",
   "engine runs to heat", "idle charging". Sidecar adds the cadence stratum and the real-sample counts per interval.

## 1. Question
Under what logged conditions does the engine run, fueled and at cold coolant, while the pack is at high SoC and the net pack current is near zero? The question is descriptive: how
many seconds, intervals, drives and days, in which overlap states, and is the context supported or only a handful of events. It makes no claim about the purpose of the running
engine (warm-up, cabin heating, defrost, dissipation, generation for traction); motive is unknown and stays unknown.

## 2. Definitions (frozen here; counts are computed, not typed)
Unit = one second of the M46/M559 1 s grid (1 s mean, forward fill limit 3, speed priority; `tools/engine_context_fields.py`), with the M559 coolant rule (last non-null raw
coolant sample, valid <= 30 s, no grid fill). A second qualifies (base) when ALL hold: SoC >= 68 %; coolant <= 60 C (the existing `_ISC_COOL_COLD`); engine rpm >= 500;
app-calculated fuel rate >= 1.5 L/h (logged / app-calculated, never "measured"); net pack current |I| <= 3 A (discharge-positive sign convention; both signs; sign reported as a sub-field:
charging <= 3 A versus discharging <= 3 A).
An interval = a maximal run of consecutive qualifying seconds of length >= 10 s. Seconds in shorter runs are counted separately ("fragments") and never promoted.
Overlap states per interval (non-exclusive descriptors, never causes): speed (standing < 5 km/h; 5-30; > 30), rpm band (500-1000, 1000-2000, >= 2000), calculated engine load band, coolant band
(<= 40, 40-60 C), fuel-rate band (1.5-3, >= 3 L/h), time since the first engine rotation of the drive (< 300 s, >= 300 s), and the M559 candidate labels active on the interval.
HVAC, defrost and cabin settings are not logged: that column is "not observed". The audit's proposed HVAC/defrost annotation needs driver input and is out of scope for the code.

## 3. Population
Canonical-clean drives with a defined 1 s grid, coolant and fuel-rate series (M559 `eligible`). Drives with a missing or all-zero fuel rate cannot qualify and are counted (not
silently dropped). Report n drives and n calendar days for every count.

## 4. Method
- Primary output: n qualifying seconds, n intervals (>= 10 s), n fragments, n drives, n days, total and median interval length, by overlap state.
- Support rule (frozen, equal to the M559 common floor): the context is labelled "supported" only with >= 200 qualifying seconds in intervals, >= 10 drives and >= 5 calendar days;
  otherwise it is shown as "candidate, not supported" with the raw counts and nothing else (no rate, no share). An interval figure below the floor is never drawn as a rate.
- Conditional rate (descriptive, only if the base support rule is met): among seconds with SoC >= 68 %, rpm >= 500 and fuel >= 1.5 L/h, the share that is pack-neutral (|I| <= 3 A)
  at cold coolant (<= 60 C) versus warm coolant (> 80 C); share pooled over seconds and per drive mean, day-clustered percentile bootstrap (seed 42, 4000 draws), both with n drives and days.
  No contrast test and no causal wording; it shows whether pack-neutral running is specific to cold coolant.
- Sensitivities (reported, not tuned): SoC 65 / 68 / 72 / 75; fuel 1.0 / 1.5 / 2.0 L/h; rpm 400 / 500 / 600; |I| 2 / 3 / 5 A; minimum interval 5 / 10 / 20 s; coolant 55 / 60 / 65 C; engine-on
  threshold 400 (project rule) against 500 (audit). Report which choices change the supported/unsupported label; if the label flips, the label is "unsupported" (conservative).
- No new estimator and no `drive_master.csv` write. The tool reads the per-drive 1 s records through the M559 extractor (cached by raw sha256 and extractor hash) and writes a sidecar of
  intervals (`engine_cold_neutral_intervals.csv`: file, date, start second, length, mean SoC, mean coolant, mean rpm, mean fuel rate, mean |I|, sign share, speed band, load band, rpm band, time since first rotation).

## 5. Known-answer tests (`tests/synthetic/test_cold_neutral_context.py`, written before the tool)
1. A 12 s synthetic run meeting all conditions -> one interval of 12 s; a 9 s run -> a fragment, no interval; two 6 s runs separated by one failing second -> fragments, no merged interval.
2. Threshold edges: SoC 68 inclusive, 67.9 excluded; coolant 60 inclusive, 60.1 excluded; rpm 500 inclusive, 499 excluded; fuel 1.5 inclusive, 1.49 excluded; |I| 3 inclusive, 3.1 excluded.
3. Missing coolant older than 30 s or missing fuel rate -> not qualifying (NaN is never "cold" or "fueled").
4. Overlap-band assignment on hand-built intervals; sign sub-field counts.
5. Support rule: 199 s -> "not supported" with only counts; 200 s on 10 drives and 5 days -> "supported"; 200 s on 9 drives -> "not supported".
6. Day-clustered bootstrap known answer (degenerate data -> degenerate interval) for the conditional-rate step.
7. Reconciliation: qualifying seconds with the relaxed set (SoC 0, coolant any, rpm > 400 strict, fuel >= 0, |I| any) equal the M559 engine-rotating seconds on the same drives (zero tolerance).

## 6. Accept / reject and decision rules
- Accept if: tests pass, reconciliation 0 mismatches, a blind audit (Sonnet, claim + raw path + this spec, no author code) reproduces the counts exactly and the support label, Director go.
- Display shape (if accepted): one short labelled paragraph in the Fuel tab next to the M559 engine-context block, bound to the new payload block, showing "candidate, not supported" counts or,
  if supported, seconds, intervals, drives, days, the overlap-state table and the conditional rate; wording "fueled (app-calculated), cold coolant, high SoC, pack-neutral; motive unknown; traction,
  auxiliary use and heat can overlap".
- Reject / leave in analyses only if the label is "unsupported" and the Director prefers not to add a paragraph for a handful of intervals.
- Falsification: if the supported label fails under any single sensitivity step, the context is "not established" (never "refuted": unsupported is not evidence that the state does not exist).

## 7. Language and scope
"Logged", "app-calculated", "estimated"; never "measured fuel", never "warm-up mode", "heating", "defrost" or "dissipation" as a finding (they are candidate labels at most); no efficiency, range or health claim;
not article-bound; raw/ = sha256-verified originals (M366).

## 8. Out of scope
HVAC/defrost annotation (needs driver input and a logging convention), a new logger setup, any change to the M559 labels or to `engineContextFields`.
