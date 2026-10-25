# Audit 2026-10-23: disposition of every finding (generated, M502; CD-05, CD-07 and ST-09 updated at M506; ST-06, ST-07 and PB-06 at M507)

Source: `findings_register.csv` of the independent audit (95 findings; stream folders and the PDF were produced outside the repo tree). Dispositions are as of the M507 milestone. "Documented limitation" means no code change and a stated reason; "deferred" means it needs a pre-registered spec and Director review; nothing here is a claim that the audit finding was wrong unless it says "audit finding corrected".

| disposition | count |
|---|---|
| already built / declined | 3 |
| already disclosed | 1 |
| audit finding corrected | 2 |
| cancelled (owner) | 1 |
| confirmation (no action) | 5 |
| decided: keep locked bound | 1 |
| deferred (new analysis or wording decision) | 6 |
| deferred (spec-verbatim text) | 1 |
| documented limitation (pipeline / master change) | 9 |
| fixed | 29 |
| fixed (disclosure + sensitivity) | 2 |
| fixed (disclosure) | 1 |
| maintainability backlog | 14 |
| measurement / design limitation (disclosed) | 19 |
| no action | 1 |

| id | severity | title | disposition | note |
|---|---|---|---|---|
| RC-01 | Medium | SoC-bookkeeping capacity CAP_KWH=2.1 lies outside the payload's own capacity estimate; the | already disclosed | offsetUncertainty.capacitySensitivity (M421) |
| RC-02 | Low | distance_km rounds the odometer-counter endpoints to 0.1 km before differencing (per-drive | documented limitation (pipeline / master change) | fixing alters drive_master or hashed pipeline code and needs its own pre-registered milestone with refit-risk control; no published figure is wrong by more than the stated scale (e.g. short-trip distance rounding, corpus total unbiased) |
| RC-03 | Low | Midnight unwrap depends on raw row order: a non-time-ordered file spanning midnight gives  | documented limitation (pipeline / master change) | fixing alters drive_master or hashed pipeline code and needs its own pre-registered milestone with refit-risk control; no published figure is wrong by more than the stated scale (e.g. short-trip distance rounding, corpus total unbiased) |
| RC-04 | Low | energy_null_reason is empty for 12 of 14 null-energy drives; a voltage outside 200-450 V a | documented limitation (pipeline / master change) | fixing alters drive_master or hashed pipeline code and needs its own pre-registered milestone with refit-risk control; no published figure is wrong by more than the stated scale (e.g. short-trip distance rounding, corpus total unbiased) |
| RC-05 | Low | drive_master file key uses two naming forms; 239 of 606 rows differ from raw_manifest cano | documented limitation (pipeline / master change) | fixing alters drive_master or hashed pipeline code and needs its own pre-registered milestone with refit-risk control; no published figure is wrong by more than the stated scale (e.g. short-trip distance rounding, corpus total unbiased) |
| RC-06 | Low | tools/ah_throughput.manifest_sha_lookup reads key "records" but raw_manifest.json has "fil | fixed | M496 (explicit None) |
| RC-07 | Low | Column name gtc carries two bases (drive_master: 2.1 kWh legacy; seasonal_drive_master and | documented limitation (pipeline / master change) | fixing alters drive_master or hashed pipeline code and needs its own pre-registered milestone with refit-risk control; no published figure is wrong by more than the stated scale (e.g. short-trip distance rounding, corpus total unbiased) |
| RC-08 | Info | Gross throughput (hence GTC/FCE) depends on the integration rule and logger cadence; indep | measurement / design limitation (disclosed) | inherent to the observational design, logger or capacity basis; stated in the dashboard caveats and CLAUDE.md language discipline |
| RC-09 | Info | Stored offset constant and the kWh actually removed derive from slightly different offset  | measurement / design limitation (disclosed) | inherent to the observational design, logger or capacity basis; stated in the dashboard caveats and CLAUDE.md language discipline |
| RC-10 | Info | The distance channel is the logger app's cumulative distance (identical to its trip meter, | measurement / design limitation (disclosed) | inherent to the observational design, logger or capacity basis; stated in the dashboard caveats and CLAUDE.md language discipline |
| RC-11 | Info | "2 primary files lack current/voltage" is ambiguous: 14 canonical drives have null energy | measurement / design limitation (disclosed) | inherent to the observational design, logger or capacity basis; stated in the dashboard caveats and CLAUDE.md language discipline |
| RC-12 | Info | Nearest-neighbour state alignment flips at exact time ties (2 drives, about 1.5 Wh) | measurement / design limitation (disclosed) | inherent to the observational design, logger or capacity basis; stated in the dashboard caveats and CLAUDE.md language discipline |
| RC-13 | Info | fuelStates litres total not reproduced (gap) | measurement / design limitation (disclosed) | inherent to the observational design, logger or capacity basis; stated in the dashboard caveats and CLAUDE.md language discipline |
| CD-01 | Medium | Released cell-spread slope (CI lower bound > 0) is better described by an October level st | already built / declined | windowCaveat (M485), serialDependence HAC and moving-block rows (M477); a governing interval stays undesignated (M477 Director ruling) |
| CD-02 | Medium | Day-cluster CI understates multi-week temporal dependence of the cell-spread slope | already built / declined | windowCaveat (M485), serialDependence HAC and moving-block rows (M477); a governing interval stays undesignated (M477 Director ruling) |
| CD-03 | Info | Cell-spread slope is not produced by logger timing, alignment, decimation, gaps or quantis | measurement / design limitation (disclosed) | see M499/M500 wording |
| CD-04 | Medium | M379b/M393 emulation changes I-V co-timing, so the displayed "-1.5 to -1.7 mOhm at slow ca | fixed | M500 |
| CD-05 | Medium | Resistance-proxy trend conclusion depends on the I-V alignment rule (method disagreement n | fixed | M505 (alignment-rule sensitivity of the resistance proxy; dated snapshot) |
| CD-06 | Medium | Resistance-proxy eligibility is defined in sample counts, so it depends on logger cadence | deferred (new analysis or wording decision) | each needs a pre-registered spec and Director review; listed in the M502 CHANGELOG entry |
| CD-07 | Low | Undisclosed coarse-resolution window of HV current/voltage (2026-08-29..09-30) | fixed | M503 (logged-grid record of HV current and pack voltage; dated snapshot) |
| CD-08 | Low | Two raw-time readers bypass clock_unwrap (midnight rollover) | documented limitation (pipeline / master change) | fixing alters drive_master or hashed pipeline code and needs its own pre-registered milestone with refit-risk control; no published figure is wrong by more than the stated scale (e.g. short-trip distance rounding, corpus total unbiased) |
| CD-09 | Low | Cadence regime is a drive-level median dichotomy; within-class and within-drive cadence va | measurement / design limitation (disclosed) | inherent to the observational design, logger or capacity basis; stated in the dashboard caveats and CLAUDE.md language discipline |
| CD-10 | Info | Timing model of the raw logs: sequential single-PID rows, no backward jumps, no midnight c | measurement / design limitation (disclosed) | inherent to the observational design, logger or capacity basis; stated in the dashboard caveats and CLAUDE.md language discipline |
| CD-11 | Low | Magnitude of the spread slope depends on the current-band definition of a loaded sample | measurement / design limitation (disclosed) | inherent to the observational design, logger or capacity basis; stated in the dashboard caveats and CLAUDE.md language discipline |
| ST-01 | Medium | M119-v2 rolling-origin validation still shown as 'confirmed' after M495 flagged degradatio | fixed | M496 |
| ST-02 | Medium | Unconditional sentence says the data cannot distinguish improving/worsening/flat while the | fixed | M496 |
| ST-03 | Low | Hardcoded collinearity literal corr(T_pack, I_peak)=0.63 and temperature-coefficient range | fixed | M502 |
| ST-04 | Medium | Cell-spread equivalence bound is derived from a different statistic than the tested outcom | decided: keep locked bound | every candidate bound gives the same verdict (M501) |
| ST-05 | Medium | Day-clustered bootstrap / CR1 under-cover under day-to-day serial dependence; trend conclu | already built / declined | windowCaveat (M485), serialDependence HAC and moving-block rows (M477); a governing interval stays undesignated (M477 Director ruling) |
| ST-06 | Medium | Percentile day bootstrap displayed with 5-10 day clusters under-covers materially | fixed (disclosure) | M507 (stylised few-cluster coverage simulation + one dashboard sentence; no interval changed) |
| ST-07 | Medium | Path A vs Path B agreement statistic r = 0.997 is a trip-size artefact | cancelled (owner) | the road-load data needed for the Path A vs Path B cross-validation do not exist now and will not exist in future (owner, chat 2026-10-25); the old crossval block stays labelled historic |
| ST-08 | Medium | Wilson intervals on per-second at-risk counts treat seconds as independent trials | fixed | M497 (SoC-standardised, day-clustered ratio replaces the max-over-bins headline) |
| ST-09 | Medium | Warm vs Shoulder thermal-cohort contrast is strongly confounded with date, time of day and | fixed | M504 (covariate balance and design-dependence of the Warm-vs-Shoulder contrast) |
| ST-10 | Low | Evidence-ledger wording over-interprets non-significance and labels a model-derived proxy  | fixed | M502 |
| ST-11 | Low | Field named MDE is the CI half-width (about 50 % power) | maintainability backlog | no effect on a reported result; optional speed-ups (PF-16..19) need a deep-diff gate |
| ST-12 | Low | Comparison cube departs from the standing bootstrap convention (seed 42, 4000 draws) | deferred (new analysis or wording decision) | each needs a pre-registered spec and Director review; listed in the M502 CHANGELOG entry |
| ST-13 | Low | Headline intervals carry sampling uncertainty only; model/preprocessing uncertainty is rep | deferred (new analysis or wording decision) | each needs a pre-registered spec and Director review; listed in the M502 CHANGELOG entry |
| ST-14 | Low | No machine-readable estimand status on thousands of intervals | deferred (new analysis or wording decision) | each needs a pre-registered spec and Director review; listed in the M502 CHANGELOG entry |
| ST-15 | Low | TOST with day-CR1 is anti-conservative under serial dependence (relevant to the first 'est | deferred (new analysis or wording decision) | each needs a pre-registered spec and Director review; listed in the M502 CHANGELOG entry |
| ST-16 | Info | Reproduced headline intervals; day clustering is justified versus drive-level | confirmation (no action) | reproduction or no-leakage findings |
| ST-17 | Info | M495 rolling-origin: no leakage found; limits disclosed | confirmation (no action) | reproduction or no-leakage findings |
| PB-01 | High | Stationary-vs-high-speed engine-start ratio headline is the maximum over SoC bins with an  | fixed | M497 (SoC-standardised, day-clustered ratio replaces the max-over-bins headline) |
| PB-02 | Medium | docs/overview.md and docs/findings-and-methods.md state superseded figures and closed defe | fixed | M502 |
| PB-03 | Info | [CORRECTED 2026-10-24] CHANGELOG head-window reads are small, but the M442/M444/M460 froze | audit finding corrected | frozen_ok() is False because the specs carry later revisions, not because of the read window (M496) |
| PB-04 | High | Resistance equivalence bound transfers the OEM relative limit onto a proxy with a differen | fixed (disclosure + sensitivity) | M499 (temperature specifications, tipping row, bound wording); the locked bound is unchanged |
| PB-05 | High | Resistance-proxy time trend is aliased with season inside a 5.1-month warm-season window | fixed (disclosure + sensitivity) | M499 (temperature specifications, tipping row, bound wording); the locked bound is unchanged |
| PB-06 | Medium | Fixed-point engine operation and battery power buffering are OEM-stated design features, f | fixed | M507 (docs wording: consistent with the OEM fixed-point strategy) |
| PB-07 | High | Generator-traction share rests on app-calculated fuel and an assumed BSFC surface, has no  | audit finding corrected | the f_gen interval and 23-variant range exist (gtrClosure.fGen); what stands is the dependence on app-calculated fuel and the non-closing balance |
| PB-08 | Medium | Logger cadence regime is aliased with calendar time and cannot be separated retrospectivel | measurement / design limitation (disclosed) | inherent to the observational design, logger or capacity basis; stated in the dashboard caveats and CLAUDE.md language discipline |
| PB-09 | Medium | Regeneration recovery levels are resolution-conditional; pre-registered cadence-invariance | measurement / design limitation (disclosed) | inherent to the observational design, logger or capacity basis; stated in the dashboard caveats and CLAUDE.md language discipline |
| PB-10 | Medium | Engine start/stop hazard model flagged degradation out of time; design was selected on ful | measurement / design limitation (disclosed) | inherent to the observational design, logger or capacity basis; stated in the dashboard caveats and CLAUDE.md language discipline |
| PB-11 | Low | Legacy 'Real measured capture by temperature' wording remains in the payload | no action | string is in the deprecated-provenance record, not rendered |
| PB-12 | Low | Strict GLM fit contract not adopted in m119v2_model.py at the M463 refit | deferred (new analysis or wording decision) | each needs a pre-registered spec and Director review; listed in the M502 CHANGELOG entry |
| PB-13 | Medium | Single-vehicle, single-season scope bounds every inference | measurement / design limitation (disclosed) | inherent to the observational design, logger or capacity basis; stated in the dashboard caveats and CLAUDE.md language discipline |
| PB-14 | Medium | Capacity-dependent cycle metrics rest on an unidentified capacity basis | measurement / design limitation (disclosed) | inherent to the observational design, logger or capacity basis; stated in the dashboard caveats and CLAUDE.md language discipline |
| PB-15 | Low | Literature-based life/damage scenarios do not transfer to this duty and pack | measurement / design limitation (disclosed) | inherent to the observational design, logger or capacity basis; stated in the dashboard caveats and CLAUDE.md language discipline |
| PB-16 | Info | Positive cell-spread slope is conditional, procedure-dependent and season-confounded | measurement / design limitation (disclosed) | see M499/M500 wording |
| DB-01 | Medium | High-SoC regen envelope: secondary (all-charging) curve misaligned to the primary bin grid | fixed | M496 |
| DB-02 | Low | Thermal tab Cold view renders 'about null °C' | fixed | M496 |
| DB-03 | Low | Same history window labelled 159 days and 160 days in one view | fixed | M496 |
| DB-04 | Low | History-chart annotations: date band and increment off by one day; Jun 21 increment attrib | fixed | M502 |
| DB-05 | Low | GTR difference-table caption 'Shoulder ... is ~98% urban' | fixed | M496 |
| DB-06 | Low | Hardcoded narrative shares drifted from the bound payload (engine-start triggers, energy s | fixed | M496 |
| DB-07 | Low | Sessions-by-phase bars use a fixed 1100 km scale | fixed | M502 |
| DB-08 | Info | Cross-vehicle MWU p-value shown as '0' | fixed | M502 |
| DB-09 | Medium | Corpus-wide section 'P — Accumulated Turnover' shown without the All-data reference tag in | fixed | M496 |
| DB-10 | Low | Unfilled placeholder 'time to c C' in the warm-up Kaplan-Meier caption | deferred (spec-verbatim text) | the placeholder sits in the pre-registered M435 required sentence R2; changing it is a spec revision |
| DB-11 | Info | semantic_gate.py crashes on a default Windows console (cp1251) | fixed | M502 |
| DB-12 | Info | Literal-snapshot warning and script index are noisy/stale | maintainability backlog | no effect on a reported result; optional speed-ups (PF-16..19) need a deep-diff gate |
| DB-13 | Info | Payload and config keys computed but never displayed | maintainability backlog | no effect on a reported result; optional speed-ups (PF-16..19) need a deep-diff gate |
| PF-01 | Medium | raw_cache entries are not invalidated by changes to the code that built them | fixed | M498 (cache keys by code closure) |
| PF-02 | Medium | capacity_cache and the per-drive sidecar rows are keyed by raw sha256 + a manual METHOD_VE | fixed | M498 (cache keys by code closure) |
| PF-03 | Low | regen_cache closure hash does not cover drive_raw_cache.add_file | fixed | M498 (regen closure includes add_file) |
| PF-04 | Low | manifest_sha_lookup always returns None (reads 'records', the manifest stores 'files') | fixed | M496 |
| PF-05 | Medium | running the CI unit-test list in a checkout overwrites two tracked evidence files with tes | fixed | M496 |
| PF-06 | Low | local Windows replay of the CI unit list: 136/139 pass; the 3 failures are environment-dep | maintainability backlog | no effect on a reported result; optional speed-ups (PF-16..19) need a deep-diff gate |
| PF-07 | Low | 21 test files are not run by CI or release_check; 4 of them fail now | maintainability backlog | no effect on a reported result; optional speed-ups (PF-16..19) need a deep-diff gate |
| PF-08 | Info | release gate and unit list replayed in an isolated copy; canonical tree and raw unchanged | confirmation (no action) | reproduction or no-leakage findings |
| PF-09 | Info | corpus and eligibility denominators recomputed from disk match the payload | confirmation (no action) | reproduction or no-leakage findings |
| PF-10 | Low | null canonical-exclusion flag means 'clean' in the arrays but 'STOP' in eligibility.py | documented limitation (pipeline / master change) | fixing alters drive_master or hashed pipeline code and needs its own pre-registered milestone with refit-risk control; no published figure is wrong by more than the stated scale (e.g. short-trip distance rounding, corpus total unbiased) |
| PF-11 | Low | many independent implementations of the day-clustered bootstrap | maintainability backlog | no effect on a reported result; optional speed-ups (PF-16..19) need a deep-diff gate |
| PF-12 | Low | duplicated canonical-file-name logic | documented limitation (pipeline / master change) | fixing alters drive_master or hashed pipeline code and needs its own pre-registered milestone with refit-risk control; no published figure is wrong by more than the stated scale (e.g. short-trip distance rounding, corpus total unbiased) |
| PF-13 | Info | reachability inventory: one-off and unreachable code | maintainability backlog | no effect on a reported result; optional speed-ups (PF-16..19) need a deep-diff gate |
| PF-14 | Info | stale navigation and environment documentation | fixed | M502 |
| PF-15 | Low | fast_time / cached 'time' depend on the run date | documented limitation (pipeline / master change) | fixing alters drive_master or hashed pipeline code and needs its own pre-registered milestone with refit-risk control; no published figure is wrong by more than the stated scale (e.g. short-trip distance rounding, corpus total unbiased) |
| PF-16 | Medium | end-to-end bottleneck: the arrays build is ~24 min, single-core | maintainability backlog | no effect on a reported result; optional speed-ups (PF-16..19) need a deep-diff gate |
| PF-17 | Info | optimisation: pair-slope reuse in the cluster-bootstrap Sen slope (bitwise equal) | maintainability backlog | no effect on a reported result; optional speed-ups (PF-16..19) need a deep-diff gate |
| PF-18 | Info | optimisation: vectorised day-bootstrap median (bitwise equal) | maintainability backlog | no effect on a reported result; optional speed-ups (PF-16..19) need a deep-diff gate |
| PF-19 | Info | optimisation: parse each raw CSV once per build | maintainability backlog | no effect on a reported result; optional speed-ups (PF-16..19) need a deep-diff gate |
| PF-20 | Info | no action needed: JSON serialisation and rendering are not bottlenecks | maintainability backlog | no effect on a reported result; optional speed-ups (PF-16..19) need a deep-diff gate |
| PF-21 | Info | full vs incremental and cold vs warm equivalence holds | confirmation (no action) | reproduction or no-leakage findings |
| PF-22 | Info | brief says 2 primary files lack current/voltage; disk shows 14 drives without an energy in | measurement / design limitation (disclosed) | inherent to the observational design, logger or capacity basis; stated in the dashboard caveats and CLAUDE.md language discipline |
| PF-23 | Low | release_check temp trees leak on Windows | maintainability backlog | no effect on a reported result; optional speed-ups (PF-16..19) need a deep-diff gate |
| PF-24 | Info | dashboard rebuild is never byte-identical; build_html warns of hard-coded drive counts | maintainability backlog | no effect on a reported result; optional speed-ups (PF-16..19) need a deep-diff gate |
| PF-25 | Info | measurement environment differs from the pinned CI environment | measurement / design limitation (disclosed) | inherent to the observational design, logger or capacity basis; stated in the dashboard caveats and CLAUDE.md language discipline |
