# M394 spec (pre-registered before the stage is registered): winter-readiness monitor for the unfuelled (motored) dissipation mode

Owner request (2026-10-09): the system must be ready to detect the unfuelled dissipation mode when it is observed in winter and normal driving. Scope: a REPORT-ONLY ingestion monitor
(`tools/dissipation_monitor.py`, library `tools/dissipation_events.py`). No change to the published census (`dissipationCensus`), the master, any estimator or any payload value.

## Mode (from the code's own description, compute_summary_arrays._dissipation_census, M46)
Series-hybrid: the ICE couples only to the generator. When the pack cannot accept surplus / regenerative energy the VCM can dump it by motoring the engine through the generator, spun UNFUELLED
(throttle closed, deep intake vacuum, calculated load ~0) at elevated rpm. HYPOTHESIS (not observed): a cold pack accepts less charge, so the mode becomes more frequent, may start at lower SoC and
at different rpm in winter. Until a cold drive has a sustained event this is a hypothesis, not a finding.

## Evidence on the current corpus (script output: analyses/M394_dissipation_scan.py, M394_fuel_crosscheck.py, monitor bootstrap)
- Published census (rpm > 2000 & boost < -0.70 & load < 8): 1,473 motored samples in 56 of 496 evaluable drives (27 drives hold an event >= 3 s), 126 events >= 3 s, 24 sustained (in 13 drives); every event with a sustained shape has mean SoC 75-85 %.
- No pack-temperature coverage in the cold: lowest drive pack temperature 9.7 C; drives below 15 C: 20 (one below 10 C); 0 census events in drives below 15 C in the scan (the baseline does hold 2 fuel-only sustained events in the 10-15 C band, one drive at 14.9 C near the band edge). Intake air temperature channel unavailable since 2026-08-24.
- An INDEPENDENT indicator (logged fuel rate < 0.2 L/h, absolute throttle B < 10 %, rpm > 1200; 60-column logging generation only, 324 drives): the census samples have median logged fuel rate 0.0 L/h, engine power 0.0 kW,
  throttle ~2 % (air still pumped, MAF ~3 g/s); fuelled samples above 2000 rpm: 6.2 L/h, 24 kW, 90 % throttle. 46 of the 71 census seconds on those drives are also fuel-indicator seconds (the other 25 are not; the reason per sample was not examined); the indicator finds 1,210 s of unfuelled spin, 1,164 s of it outside the census, almost all at 1200-2000 rpm and almost all SHORT transients (80 events, median 5 s, 69 % falling rpm = engine start / stop motoring). FUEL alone is therefore sensitive, not specific: SUSTAINED is the discriminator.
- Normal fuelled generation has a floor at ~1500 rpm (5th / 10th percentile 1499 / 1500) and 85 % of all low-manifold-pressure samples sit at 1200-2000 rpm: relaxing the census rpm gate would flood it with light-load generation. The gate stays.
- Baseline (monitor bootstrap on 554 drives; a blind audit reproduced the counts event for event once the 1 s bins are aligned to the wall-clock second): 35 sustained events (24 census in 13 drives, 11 fuel-indicated that the census does not see, in 9 drives, mean rpm 1520-1736, e.g. 30-41 s at ~1520 rpm and SoC 77-79 %; they sit just above the ~1500 rpm generator floor, so 'unfuelled' rests on logged fuel < 0.2 L/h and throttle < 10 % only; low-power fuelled generation with a quantised fuel rate is not ruled out and the SUSTAINED test is the only guard there); mean SoC 76.9-84.8 %; mean rpm 1520-3594; no census event
  that the fuel channel fails to confirm on fuel-capable drives; sustained events in the 10-15 C band: 2 (one drive); none below 10 C. Validation gap: bands < 5 C and 5-10 C have no sustained event (one drive in 5-10 C, none below 5 C).

## Definitions (fixed, not tuned; `tools/dissipation_events.py`)
1 s grid as in the census (mean, forward fill <= 3 s), bins aligned to the wall-clock second of the time-of-day index, NOT to the first row (event counts depend on this phase: first-row bins give 22 instead of 24 census events). Event duration counts grid rows after dropping rows with a missing needed channel. PUB = rpm > 2000 & boost < -0.70 & load < 8. FUEL = rpm > 1200 & logged fuel rate < 0.2 L/h & absolute throttle B < 10 %. Event = run >= 3 s.
SUSTAINED = duration >= 10 s and |OLS rpm slope| < 30 rpm/s (not a start / stop transient). Pack-temperature band = drive mean T_pack_mean_avg: < 5, 5-10, 10-15, 15-25, >= 25 C.
Fuel rate / engine power are logged / app-calculated (Car Scanner), never "measured".

## Monitor (`tools/dissipation_monitor.py update`, stage `dissipation_monitor`, report-only: exit 0, never stops an ingestion)
State `analyses/dissipation_monitor.json`: one record per drive (deterministic, no timestamps), coverage by band, `last_update` flags, cumulative `flag_history`. First run bootstraps the baseline without flags; later runs record unseen drives and
flag each against the drives with an earlier (date, file) (a backfilled older drive is compared with older drives only); a run with no new drives leaves the file untouched (a pipeline rerun cannot erase an alert). Flags: `first_sustained_in_band` (first winter observation), `below_baseline_soc` (mean SoC more than 5 pp below every earlier
sustained event), `fuel_event_not_in_census` (detector gap), `census_event_not_fuel_confirmed` (possible false positive), `channel_gap` (rpm / boost / load / SoC missing: not evaluable, never a pass), `fuel_indicator_unavailable` (info), `sustained_event_unknown_temperature` (no pack temperature: no band logic), `read_error` (unparseable raw file: not recorded, retried, batch continues), `raw_file_missing` (info), `census_event_fuel_unknown` (info). Same-date drives are ordered by file name (a space sorts before an underscore, so mixed name formats on one date could sort out of time order; the master has none). The monitor's main() prints monitor_error and exits 0 on an unexpected failure, so it can never stop an ingestion (the run log shows it; the state is left as it was). A recorded drive is never recomputed (its band is the one at first recording). A persistent read_error enters `flag_history` once.

## Reviewer action
A flag is a prompt to look, never a conclusion: open the drive, check the event (SoC, rpm trend, pack current, ambient from the driver), and record in the CHANGELOG. The first `first_sustained_in_band` below 10 C starts the winter validation:
only then are cold-band thresholds, the SoC ceiling (census CEIL_SOC = 85, above where the mode appears) and the rpm gate reviewed, by a separate spec with the cold data.

## Gates and limits
Known-answer tests `tests/synthetic/test_dissipation_monitor.py` (CI): steady unfuelled spin = sustained for both detectors; start / ramp transient not sustained; fuelled 1500 rpm floor not an event; missing channels = not evaluable;
each flag has a firing and a non-firing case; idempotence and rerun safety. Blind audit reproduces the baseline counts independently. Limits: the grid is anchored at 1900-01-01 (a drive crossing midnight would wrap; none does); the 1200 rpm FUEL gate admits the generator floor region; FUEL needs the 60-column generation (324 of 554 drives); thresholds were set on summer data;
SoC / pack-temperature context is drive-level for temperature; no dashboard figure yet (a display follows the first cold observations; every displayed figure will bind to S.* keys); T_intake unavailable so pack temperature is the temperature axis.

## Director ruling (M394: accept) and conditions
Report-only stage registered after cadence_regime; it never fails, blocks or reruns an ingestion; read_error / channel_gap are not evaluable, never a pass. No change to the census, master, estimators or payload; release_check unchanged, master MD5 identical.
FUEL gate stays at 1200 rpm with SUSTAINED as the required guard; FUEL-only sustained events are reported as "fuel-indicated unfuelled (unconfirmed by census; low-power fuelled generation not ruled out)". Thresholds are labelled
"set on data with pack temperature >= 9.7 C; unvalidated for cold". The auditor re-checks the fixed audit points before merge (scoped, not a new audit). Flags are surfaced in delta_report as an informational block (never route_to_audit) and listed in the CHANGELOG acknowledgement text.
Dashboard display deferred until cold sustained events exist (any display binds to S.* keys). With zero cold events a cold rate is reported with a Wilson CI only once cold drives exist, never as "no effect".

## Stop rule / cold validation protocol (Director follow-up, stated here)
Trigger: the first `first_sustained_in_band` flag in a band below 10 C. Steps: (1) a manual event check (SoC, rpm trend, pack current, ambient and context from the driver) recorded in the CHANGELOG; (2) a separate pre-registered spec that reviews, on the cold data,
the cold-band thresholds, the census CEIL_SOC = 85 (above where the mode appears), the census rpm gate and the classifier; (3) a blind audit; (4) a Director ruling; Andrii signs off any change to the census or estimators. Neither the monitor nor the main session changes a threshold on its own.

## Owner actions (Director)
Keep the 60-column PID set unchanged through winter (the fuel and throttle channels are the independent indicator; changing the PID set also changes sampling cadence, see M393, and would confound winter vs summer). When a cold drive is flagged, note the ambient
temperature and anything unusual (preconditioning, short trip, full-SoC start). If possible restore the intake-air temperature PID.
