# M516 inventory: canonical-clean eligibility in the raw-pass blocks of compute_summary_arrays.py (2026-10-26)

Origin: audit 2026-10-25 A03 found that `_soc_balanced_fuel` lacked the canonical exclusion (fixed at M511 with a matched sensitivity); the M511 Director asked for an inventory of the sibling `_thermal_fuel_penalty`. This sweep lists every function of `compute_summary_arrays.py` that reads raw data per master drive (`raw_loader` / `frame_loader` / `_of_grid`) and loops over the master rows, and whether its body mentions a canonical filter (`_canonical_bad`, `ens_outlier_v2`, `ens_invalid`, `clean`). It is a static heuristic (a mention is not proof of correct use; an absence is not proof of a defect) and changes nothing.

Standing rule (CLAUDE.md): the canonical exclusion is `ens_outlier_v2` (== `ens_invalid`); ENERGY RATES use canonical-clean eligibility. Descriptive census and event-structure blocks are not energy rates, and the project has historically computed many of them on all drives (the builder comment near line 488 records the QC convention). Which of the blocks below are rate- or estimate-bearing (and so fall under the rule) and which are descriptive censuses is a policy decision for the owner / Director; this inventory does not decide it.

| function | line | canonical filter mentioned |
|---|---|---|
| `_rf_dod_histogram` | 5131 | no |
| `category_B` | 5265 | no |
| `_battery_temp_traj` | 5323 | no |
| `_motor_temp_stats` | 5436 | no |
| `_highspeed_census` | 5561 | no |
| `_near_limiter` | 5664 | no |
| `_buffer_impulse_summary` | 5949 | no |
| `_ramp_latency_summary` | 6131 | no |
| `_start_event_analytics` | 6243 | yes |
| `_soc_hysteresis_summary` | 6448 | no |
| `_thermal_step_response` | 7539 | no |
| `_dissipation_census` | 7707 | no |
| `_low_speed_dissipation` | 8560 | no |
| `_crawl_stop_go` | 9206 | no |
| `_crawl_stop_go_phases` | 9407 | no |
| `_crawl_stop_go_two_part` | 9508 | no |
| `_accel_decel_envelopes` | 9860 | no |
| `_rpm_speed_sync` | 10082 | no |
| `_engine_start_context` | 10294 | no |
| `_buffer_debt_recovery` | 10560 | no |
| `_driving_state_taxonomy` | 10760 | no |
| `_departure_arrival` | 10959 | no |
| `_engine_state_machine` | 11150 | no |
| `_engine_dwell_survival` | 11340 | no |
| `_thermal_warmup_lag` | 11878 | no |
| `_soc_balanced_fuel` | 12081 | yes |
| `_handoff_sequence` | 12338 | no |
| `_start_event_chain` | 12484 | no |
| `_cell_spread_relaxation` | 12641 | no |
| `_vgt_airpath` | 12818 | no |
| `_high_soc_regen` | 12980 | no |
| `_high_soc_regen_covariates` | 13268 | no |
| `_soc_control_surface` | 13455 | yes |
| `_energy_shifting` | 13732 | no |
| `_baro_compensation` | 13887 | no |
| `_thermal_fuel_penalty` | 14305 | no |
| `_thermal_fuel_penalty_continuous` | 14522 | yes |
| `_audit_raw_manifest` | 16356 | no |

Checked for a numerical effect today: the master has 2 canonical-invalid drives (`_canonical_bad`); `_thermal_fuel_penalty` selects cold-start fuel drives (coolant start < 60 C reaching >= 70 C with a used-fuel accumulator delta > 0.02 L): neither canonical-invalid drive qualifies, so aligning that block would change no number at the current corpus (read-only check, 2026-10-26). `_soc_balanced_fuel`: aligned at M511 (one trip excluded, matched sensitivity kept).

Recommendation for the owner decision: (1) apply the rule to the rate-bearing fuel and thermal-penalty estimators (`_thermal_fuel_penalty` and its continuous companion, with the independent selection in `tools/thermal_support_ledger.py` kept in step), each through `eligibility.py` with a matched sensitivity, as M511 did; (2) leave descriptive censuses on all drives but state the population label in their methodology text; (3) do not mix this with the ingestion (a population change must be attributed separately).
