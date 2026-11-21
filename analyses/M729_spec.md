# M729 spec: MyNISSAN cloud export as an auxiliary source (importer, report-only)

Status: Rev 1, written before the importer ran on the real export. Owner: Andrii. Director review of the concept: 2026-11-21 (revise: auxiliary, report-only first).

## 1. Owner decisions (chat, 2026-11-21)
- The cloud export is a SECONDARY (auxiliary) source. OBD remains the primary source for every KPI, figure and test. No cloud value replaces an OBD value.
- Geoposition privacy is waived: cloud GPS is used in full for parking anchors, map matching, road grade and DEM matching.
- Seatbelt states are accepted as a load proxy (wording: "proxy"; never payload in kg or occupancy as observed).
- All usable cloud parameters are to be used: odometer, displayed speed, accelerator opening, ambient and coolant temperature, tyre pressures, wipers, lighting, GPS, belts, alert codes.
- Exports arrive periodically, ideally with each ingestion, never guaranteed. The importer is an optional, non-blocking, idempotent stage; drives without cloud coverage are labelled "no cloud data", not treated as a defect.

## 2. Scope of M729 (this milestone)
Tooling and report-only side tables. No change to `drive_master.csv`, `summary_*.json`, `cohort_arrays.json`, the dashboard, any frozen winter file or any payload key. Everything derived is labelled auxiliary and carries export provenance and coverage.

Deliverables:
1. `tools/mynissan_import.py`: reads export ZIPs (or unpacked folders), writes a sha256-manifested normalised store (default `cloud_store/`, git-ignored, override `XT_CLOUD_STORE`), exact-row dedup, conflict log, idempotent re-import, optional-stage behaviour.
2. `tools/mynissan_coverage.py`: per-drive and per-drive-gap side tables on the live `drive_master.csv` basis and a JSON brief (`analyses/M729_cloud_brief.json`, `analyses/M729_cloud_coverage.csv`, `analyses/M729_cloud_gaps.csv`).
3. Tests `tests/synthetic/test_mynissan_import.py` (known answers: exact dedup, conflicts, DST, idempotence, missing stream, non-blocking when no export).

Out of scope here (later milestones, each needs its own spec, blind audit and Director step where it touches a frozen or published output): map matching and DEM grade, thermal-forcing comparison, missing-period exposure model, clock-offset estimation, payload sensitivity.

## 3. Time and identity rules
- Cloud `Timestamp` is parsed as UTC. Drive windows come from `drive_master.csv` `date` + `time_start` + `duration_s`, interpreted as `Europe/Kyiv` local time (DST transition 25 Oct 2026 is tested). Original timestamps are never altered; estimated alignment is recorded per channel in later milestones.
- Dedup key: the full row (stream, all fields). Conflict: same stream and timestamp with different non-blank values in the same field; both are kept in `conflicts.csv`, the first is not preferred silently.
- A blank is unknown, a zero is an observed value.
- Window join pad: 60 s each side (sensitivity 30 and 120 s in the brief).

## 4. How each cloud parameter is used (value classes: Direct, Auxiliary, Proxy)
| Parameter group | Class | Use in the study | Stage |
|---|---|---|---|
| Odometer (`StatusDistanceTotalizerComputed`, alias `StatusDistanceTotalizer`) | Direct (distance) | Independent per-drive distance check; unlogged-use bound (cloud-only km); missed-drive detection; stationary-consistent parking test; endpoint-age fields. Alias is cross-checked. | M729 |
| Displayed speed | Auxiliary | Motion flag, coarse speed strata, cloud-only bursts, clock-offset estimation (later). Capped at 130 km/h, about 30 s cadence; OBD speed stays primary for 80-120 km/h, transients and high-speed bins. | M729 coverage; offset later |
| Accelerator opening | Auxiliary | Coarse demand bins for cloud-only bouts; coverage and agreement with OBD pedal channel. Called "accelerator opening", not acceleration; acceleration from 30 s speed differences is not derived (too coarse). | M729 coverage; bins later |
| Ambient temperature (+unit code) | Auxiliary | Denser ambient series beside the driver-recorded value; settled in-drive mean (3 min after sustained movement, sensitivity 2 and 5); start and parking estimate with explicit age and flag; never pooled or silently substituted for the manual ambient. | M729 counts; forcing later |
| Engine coolant | Proxy | End-of-drive engine thermal anchor for cloud-only bursts and warm-start state; residual against OBD coolant by phase and age. | M729 anchor table; model later |
| Tyre pressure (four corners, axle cold targets, wheel-state alert) | Proxy | Within-epoch pressure trend, sample age, cold-versus-warm flag, target deviation; wheel-state code 2 marks the 14 Jul puncture epoch (excluded from routine comparisons). Scale (tenths of kPa) to be validated against a dash or gauge reading. | M729 counts; trend later |
| Wipers | Proxy | Precipitation, spray or washing context; spans over 30 s; source code kept (6, 7). | M729 shares |
| Lighting (low, high, DRL, position, front fog, rear fog) | Proxy | Visibility and darkness context; rear-fog rule (consecutive ON samples spanning over 30 s, steps up to 35 s); time-of-day class cross-check. | M729 shares |
| Seatbelts (front passenger, rear L/C/R, driver) | Proxy (load) | Latched-share groups as a load proxy and sensitivity grouping; code 2 is the latched state; coverage and co-occurrence kept; no kg estimate without a scale or known-trip validation. | M729 shares |
| GPS (lat, lon, heading, source code) | Direct (position), Proxy (route, grade) | Screened positions for parking anchors, route validation, map matching and DEM grade for regen and energy analysis; heading as a secondary cue; source code retained. Screen: valid pair, not zero, inside Ukraine, overspeed edges split. | M729 position screen; matching and grade later |
| Constant diagnostic codes (fuel low, oil switch, ESC/ABS, oil warning, brake fluid, MIL) | Coverage flags | Kept as observed codes; any change is an event marker. No analytic use while constant. | M729 constant-check |
| The 90 blank columns | None | Schema recorded; a future non-blank value raises a flag. | M729 schema check |

## 5. Pre-registered definitions (report-only)
- Drive window: `[start, end]` from the master, padded by 60 s.
- Cloud step: adjacent odometer samples at most 35 s apart, positive increment, implied speed at most 180 km/h.
- Cloud-only burst: samples separated by at most 120 s with at least two accepted steps with positive speed and at least 1 km of accepted distance, lying wholly outside all padded drive windows. Two definitions are reported: strict (burst rule) and crude (all accepted steps outside windows).
- Gap classes between consecutive master drives (hours between logs above 0, drive pairs by start time): stationary-consistent (detected movement below 0.1 km, both odometer anchors within 60 s and change at most 0.1 km, two screened positions within 60 s at most 75 m apart); driving observed (at least two steps totalling at least 1 km); odometer increase only; uncertain. A gap overlapping the 30 Jul 22:54 to 1 Aug 18:04 Kyiv export break is flagged before classification.
- Coverage counts per drive: speed samples, ambient samples in the window and after 180 s, coolant snapshot within 30 s before to 60 s after the end, four-corner tyre record within 60 s of the window, and shares of wiper, lamp and belt states over moving samples.

## 6. Gates (stop conditions)
1. `drive_master.csv` MD5 unchanged before and after; no tracked frozen or `summary_*.json` file modified.
2. Known-answer tests pass; re-importing the same ZIPs changes nothing (store hash identical).
3. Reproduction of the export facts from the three supplied ZIPs: 173 observed Kyiv dates of 194, 21 dates without rows, the 30 Jul to 1 Aug break with equal odometer on both sides, 39 populated study fields and 90 blank columns; row total reported against the handoff's 161,563 with the difference explained.
4. All counts are regenerated by script on the live corpus; none are copied from the handoff.
5. Language: "displayed/logged by the vehicle cloud", "estimated unlogged distance", "proxy"; never "measured" for cloud-derived quantities.

## 7. Follow-ups (not in M729)
Each needs its own spec: clock-offset study, thermal-forcing comparison (Q1-Q3, parked budget, winter freeze rules apply), map-matched route and DEM grade for regen, missing-period exposure with masked-drive validation, tyre-pressure scale validation, payload sensitivity from belt groups, ingestion-stage hook once the importer is accepted.
