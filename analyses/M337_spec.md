# M337 Fuel analytics v1 (FUEL-12, FUEL-01, FUEL-11): pre-registered spec rev 1 (work in progress: Director review pending)

Origin: audit v3 fuel addendum (FUEL-01, -11, -12), owner decision O1 (single Fuel tab), plan order agreed 2026-10-02 (GTR M336 merged). Predecessors: M334 `fuelContract` (coverage, definitions, E10 basis banner).
Scope of v1: three NEW observed-fuel views, one script-written payload key `fuelAnalytics`, no change to any existing figure, to `CAP_KWH`, to the E10 constants (C05) or to the GTR block. FUEL-02/03/04 follow later.

## 0. Language and basis (binding)
The logger (Car Scanner ELM OBD2) calculates the fuel rate (L/h) and the fuel counter: they are "logged/app-calculated", never "measured fuel" or "meter". Volumes are litres as logged. No energy, cost, BSFC or generator quantity appears in these views. Basis: `raw/` (F03: provenance-sensitive), reported per view together with an F03 sensitivity (section 5). Agreement of rate-integral and counter does not establish independence or external accuracy (both derive from the same app).

## 1. Common eligibility and units
- Trip = one canonical drive file (`drive_master.csv` row, `ens_outlier_v2` not True, `distance_km > 0`).
- Fuel-usable trip: fuel counter column present with >= 2 numeric samples and max > min AND rate column present with >= 10 samples (the `fuelContract` definition; expected about 243 trips, from 2026-08).
- Counter reset flag: any decrease of the counter by more than 0.01 L inside the file. Reset trips are excluded from all three views and listed (ids and count) in the payload.
- Distance = master `distance_km` (canonical, reset-repaired); never the logger's own average fields (their reset window and update timing are not established; FUEL-12 average-field validation is OUT of v1).
- Resampling unit for every interval: calendar day; day-clustered percentile bootstrap, seed 42, 4000 draws; every estimate reports n (trips, days). Ratio-of-sums only; never an average of per-trip L/100 km into a fleet rate; never summed percentages.
- Strata/bands with < 5 distinct days are not interval-estimated: individual points are shown and the band is labelled "sparse (n days)".

## 2. FUEL-12: rate-integral versus counter agreement
- Per trip: V_cnt = counter(last valid) - counter(first valid); V_int = integral of the logged rate between the same two sample times (time-weighted rectangle rule on the logged timestamps, per-sample dt capped at `recon_engine.DT_CAP` = 5 s as in the pipeline; sensitivity: trapezoid, cap 2 s and 10 s). Both in litres on the same endpoints.
- Per trip: difference d = V_int - V_cnt and mean m = (V_int + V_cnt)/2; difference-versus-mean plot (litres); relative difference d/m is shown only where m >= 0.05 L (declared resolution floor); trips below the floor appear in the litre plot only.
- Corpus: aggregate relative difference = sum(d)/sum(V_cnt) with the day-clustered CI; median and IQR of per-trip relative difference as descriptors (not a fleet rate); count of trips with |d/m| > 5% (flag, filterable list in the payload: id, date, V_int, V_cnt, d, flags).
- Regression reference (audit R9, frozen data version): 234 trips with +0.240% aggregate difference. It is a known-answer reference for the audit's frozen data, NOT an acceptance tolerance: this milestone reports our value, the trip count, and the difference to the reference, and must not tune any step to match it.
- Distinguish, in the text: logger consistency (this view) from numerical-integration sensitivity (the variants above) from fuel-meter accuracy (not tested) from model validity (not tested). A high correlation does not validate a fuel meter or the generator split.

## 3. FUEL-01: consumption versus trip length
- Trip fuel V = V_cnt (counter basis; V_int shown only in FUEL-12). Rate r = 100 V / km.
- Eligible: fuel-usable, no reset flag, km >= 0.5 (zero/short-distance journeys are not in the rate panel; they appear only in the litres panel with a note).
- Panels (identical eligible trip ids): (a) litres versus km, (b) L/100 km versus km; colour by start thermal state: first valid engine-coolant sample in bands {< 40 C, 40-60 C, >= 60 C, unknown} (oil as fallback; bands are descriptive, not the cold gate of the model). Tooltip: trip id, date, litres, km, L/100 km, start coolant, SoC change (soc_end - soc_start, percentage points), source flags.
- Distance bands (fixed a priori): [0.5,2), [2,5), [5,10), [10,20), [20,inf) km. Per band: n trips, n days, pooled rate (ratio of sums) with day-clustered CI; bands with < 5 days are marked sparse. Also the same pooled rates split by start-temperature band where n days >= 5.
- Any fitted line is descriptive (log-km on pooled rate by band, not a regression intercept) and is not interpreted as "fuel wasted at startup"; the existing cold-start fuel-rate association (ThermalFuelPenalty) is unchanged and cross-referenced.

## 4. FUEL-11: consumption distribution and chronological trend
- Distribution: eligible trips with km >= 2 (rate stable enough; sensitivity km >= 0.5 and >= 5). Two separate statistics: trip-weighted ECDF of r and distance-weighted ECDF of r (weights = km); quantiles (10/25/50/75/90) of each with day-clustered CIs; the two are labelled and never mixed. Distance groups as in section 3 (ECDF per group where >= 5 days, else points).
- Trend: pooled consumption = sum(V)/sum(km) x 100 over calendar windows of 7 days (Monday start, non-overlapping; sensitivity 14 days); per window: litres, km, trips, days, CI (day-clustered within the window if >= 5 days, else "sparse"); windows with no eligible trip are gaps (no interpolation, no continuous seasonal story). Composition annotation per window: share of km in trips < 5 km and share of trips with start coolant < 40 C, so changes in trip mix are visible. Window ordering and non-overlap are disclosed.
- Compare mode: Warm / Shoulder overlays use the thermal-cohort label of each trip from `seasonal_drive_master.csv`; Cold has n = 0 (shown as such). Cohort colour and line style per the dashboard convention (S.driveTypes / cohort palette), no new hex.

## 5. Provenance (F03) sensitivity
Per view, re-estimate the headline (aggregate relative difference; pooled rate by band; pooled trend) on the subset of trips whose `raw/` file passes the `raw_manifest.json` sha256 (hash-passing), and report both numbers side by side. Fuel columns may be unaffected by the HV-current precision issue; that is a hypothesis to be shown, not assumed. The sha256-verified originals live outside the repo and are not used.

## 6. Implementation contract
- `tools/fuel_analytics.py` (new, script-written payload key `fuelAnalytics`, additive leaf splice into `summary_arrays.json`, idempotent, asserts no other leaf changes; carried forward or recomputed on every ingestion per CLAUDE.md fuel rule, add to `tools/ingest_stages.json` after `fuel_contract`). Per-trip rows are stored (about 243 rows) so the dashboard binds every plotted point to the payload; no typed literals.
- Known-answer tests (`tests/synthetic/`): synthetic drive with constant rate and a counter that increments consistently -> d = 0; a 1.0% biased counter -> aggregate +/-1.0%; a reset trip is excluded and listed; band edges inclusive/exclusive as specified; ECDF weighting (trip vs distance) on a two-trip example.
- Dashboard: three new components in the Fuel tab after the fuel-basis banner; every displayed figure bound to `S.fuelAnalytics.*`; language gate additions (forbidden: "fuel meter", "measured fuel", "accurate/validated fuel", "fuel wasted at startup", "average of trip L/100 km as fleet rate"; required: "logged/app-calculated", n (trips, days), F03 label, "agreement does not establish independence"); `semantic_gate` REQUIRED checks; jsdom test for the three components in All/Warm/Shoulder/Compare/Cold.
- Not in v1: FUEL-02/03/04/05/06-10, app-average validation, E10 harmonisation, any energy/cost conversion, any change to `fuelContract`, to GTR or to the Sankey.

## 7. Decision rules and stop conditions
- FUEL-12 agreement is reported as an estimate with CI; it is not accepted or rejected against 0.240%. If the aggregate difference CI excludes 0 by more than 1% of volume, the view is shown with a "logger inconsistency" flag and the milestone stops for Director review before wording.
- Any figure entering the article needs the Opus audit and Andrii's sign-off (recorded in the CHANGELOG entry); v1 is dashboard-only.
- Blind audit (analytical-auditor): claim = FUEL-12 aggregate and per-band pooled rates on the stated eligibility, data path only; Director decision before the dashboard build.
