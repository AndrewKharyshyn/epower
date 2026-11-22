# M736 spec: map-matched route and DEM road grade from OBD and cloud GPS, validated against logged GPS altitude (report-only)

Rev 1. Committed BEFORE any tool is written or run. Author: main session (Sonnet). Next step: Director review (`research-director`), then tool, tests, blind audit, Director decision. Milestone number follows M735 (parallel winter session).

## 0. Why, and what is already known
- Owner decisions (2026-11-21): the MyNISSAN cloud export is auxiliary; cloud GPS may be used in full; all usable cloud data are used. Map matching and DEM grade were deferred by M729 section 7 to their own spec.
- Known before any result (read from files, not from a run of this milestone): the cloud `Geolocation` stream has latitude, longitude, heading, source code and validity, and NO altitude (`LastKnownlocationaltitude` is empty); about 41,000 rows, sample interval about 30 s. At 100 km/h a 30 s step is about 0.8 km, so a raw cloud track cannot resolve grade by itself. The OBD logger has GPS altitude, GPS speed and position at 1 Hz only in the 42-column logging generation, in bursts (`gpsAltitudeCoverage`: "grade-resolved coverage is real but NOT representative of the steepest driving"). Older drives have no position at all.
- Hence grade enters through an external digital elevation model (DEM) evaluated along a map-matched route. Whether that is good enough is an empirical question with a built-in validation set (OBD drives that have both logged GPS altitude and a cloud track), not an assumption.

## 1. Constraints
- Cloud and DEM derived quantities are "estimated / model-derived / proxy", never "measured". OBD stays primary; nothing replaces a logged channel.
- No published output changes: no `summary_arrays.json`, payload, dashboard, `seasonalFits`, regeneration payload key (`regenDisplayV2`) or `drive_master.csv` change (MD5 `d514d6009d6d9a0a168ad4fb09b9bb98`, 717 rows at spec time, asserted before and after). Results go to `analyses/M736_*.json/csv` only.
- Winter freeze (M726): no frozen winter file is read for writing or changed; no winter prediction is scored. The grade covariate is not added to any winter estimator.
- External inputs (DEM tiles, road network) are NOT in the repository and are not downloaded by this spec. Stage G0 below runs offline. Stages G1 to G3 need Andrii's explicit yes for the named downloads (section 2); until then the tool refuses to run them (exit 0, "external input absent", optional-stage pattern of M730 to M734).
- Cloud timestamps run about +16 s earlier than OBD (M730; no shift applied; a +-16 s sensitivity is reported wherever time alignment matters).
- Statistics: calendar day is the resampling cluster; day-clustered percentile bootstrap (seed 42, 4000 draws) for every interval; n (drives, days, metres) with every estimate.

## 2. Data and external inputs
Internal (read-only): `drive_master.csv` windows (date + time_start + duration_s, Europe/Kyiv, padded 60 s), raw drive CSVs (`XT_RAW_DIR`; columns GPS altitude, GPS speed, Latitude, Longtitude where present), M729 store `Geolocation`, `Odometer`, speed (`XT_CLOUD_STORE`).
External, each a separate approval request to Andrii before it is fetched, with file, source and size stated:
- E-DEM: Copernicus GLO-30 (30 m posting) tiles covering the bounding box of all screened positions; fallback SRTM 1 arc-second. Vertical accuracy is a few metres; the spec does not assume it is adequate for grade (section 5, rule R2).
- E-ROAD: OpenStreetMap road network (highway classes motorway to residential) for the same bounding box, for map matching. Without it G1 and G3 use straight-line interpolation between fixes only and are labelled "unmatched".

## 3. Stages (each stage has a stop gate)
- **G0 offline feasibility (no download).** (a) Cloud position screen of M729 (valid pair, not zero, inside Ukraine, source code kept). (b) For each drive in the OBD-GPS set (files with logged GPS position and altitude), resample the OBD track to the cloud timestamps and report the cloud-minus-OBD position difference (median, P90, by speed class), at shifts of -16, 0 and +16 s. (c) Cloud track geometry: samples per drive, spacing in metres by speed class, share of drive distance within 150 m of the OBD track (when available). (d) OBD-altitude grade quality alone: GPS altitude is logged at 1 Hz with its own noise; the along-route grade is the slope of a least-squares line of altitude on odometer distance over a window of L metres (L = 250, 500, 1000, primary 500), with the noise floor estimated from its disagreement between non-overlapping halves of a straight road section. Stop gate G0: if fewer than 20 OBD-GPS drives on 10 days have a cloud track, G1 to G3 are reported "not testable" and the milestone ends with G0.
- **G1 map matching (needs E-ROAD).** Hidden-Markov map matching of the cloud track (30 s fixes) to the road graph; route length reconciled with the cloud odometer step distance and, where available, the OBD distance. Output per drive: matched share, route-length ratio to odometer distance (median, P90), flag when the ratio is outside 0.85 to 1.15.
- **G2 DEM grade (needs E-DEM).** Elevation sampled along the matched route (or the straight track when unmatched), bilinear on the 30 m grid, smoothed to scale L (primary 500 m; 250 and 1000 as sensitivities); grade is the slope of the least-squares line over L. Validation set = OBD-GPS drives with a cloud track and a matched route.
- **G3 application (needs G2 accepted).** Report-only: (i) route grade class shares (below -3 %, -3 to -1 %, -1 to 1 %, 1 to 3 %, above 3 %) per drive and per cohort; (ii) for regeneration events of the published cadence-stratified view (read-only inputs of `regenDisplayV2` extraction, no payload write) the share of regeneration kinetic energy on grade classes, and the apparent KE recovery with and without a grade term `m g Delta h` (assumed mass, labelled); (iii) the nuisance question: does the regeneration recovery per SOC cell move when downhill events are excluded or the potential-energy term is added.

## 4. Estimands (pre-registered)
- **P1 position agreement (G0).** Median and P90 of cloud-minus-OBD position error (m) over matched timestamps, by speed class (below 30, 30 to 80, above 80 km/h), at shifts -16, 0, +16 s; n (drives, days, fixes). Descriptive.
- **P2 grade agreement (G2, headline).** On the validation set, per 500 m segment: difference DEM grade minus OBD-altitude grade (percentage points). Reported: bias (median), median absolute difference, P90 absolute difference, Pearson and Spearman correlation, Lin concordance, each with a day-clustered bootstrap interval; also by speed class and by matched/unmatched. Segments need at least 400 m of consecutive OBD altitude with no gap above 5 s.
- **P3 grade-class agreement (G2).** Three-class agreement (downhill below -2 %, flat, uphill above 2 %) as a confusion matrix and Cohen kappa, day-clustered interval.
- **P4 downstream sensitivity (G3).** Change of the displayed-view apparent KE recovery per SOC cell between baseline and grade-aware versions, with the day-clustered interval; and the share of regeneration KE on downhill segments.

## 5. Decision rules (frozen before any result)
- R1 (G0 gate): as stated in section 3.
- R2 (DEM accepted for grade use): all of (a) |bias| of P2 at most 0.5 percentage points with its upper interval bound at most 1.0; (b) median absolute difference at most 1.5 percentage points; (c) Spearman correlation at least 0.7 with the lower interval bound at least 0.6; (d) three-class kappa at least 0.5 with the lower bound at least 0.4, on at least 30 days and 100 km of validation route. Otherwise "DEM grade not accepted at this precision": G3 is not run, and the result states which criterion failed. The thresholds are chosen so that a grade of about 3 % carries a typical error of at most half its size; they are not tuned after the data are seen.
- R3 (grade-aware regeneration): (i) the P4 shift is reported with its interval; (ii) a cell counts as "grade-sensitive" only if the interval of the difference excludes zero and the absolute shift exceeds the resolution bracket `b_nat` of the displayed cell; (iii) no payload or displayed figure changes in this milestone, whatever the outcome; an outcome that moves a displayed cell escalates to the Director and to Andrii (separate decision, new milestone).
- R4 (no pooling, no contrast): fast-polled and slow-polled strata are never pooled or contrasted (M451 ruling); the B6 cadence-invariance check stays failed and shown.
- R5 (selection): the validation set is the OBD-GPS drives with a cloud track; if it is not representative of the full route mix (grade class shares of the OBD altitude track on those drives against all OBD-GPS drives), this is stated as a limitation, because the steepest driving falls in logging gaps.
- Falsification: the claim "a DEM along a map-matched cloud track recovers road grade usable for the regeneration analysis" is falsified when R2 fails; the claim "grade explains part of the regeneration-recovery spread" is falsified when no cell is grade-sensitive under R3(ii).

## 6. Gates
1. `drive_master.csv` MD5 unchanged; no tracked frozen, summary or payload file modified.
2. Known-answer tests: planted track on a synthetic DEM (plane, sine hill) recovers the planted grade within 0.1 pp; planted position offset recovered by P1; trapezoid smoothing and segment rules on constructed inputs; HMM matching on a three-road toy graph; tool skips cleanly without the external inputs.
3. Every figure regenerated by script from the live corpus; none copied from this spec.
4. Language: "estimated / model-derived / proxy", "DEM grade", never "measured grade", never a mass claim (assumed mass, labelled), no "temperature effect" or wording from the language gate list.
5. Blind audit (`analytical-auditor`, claim and data paths only) reproduces P1 and P2 (and P4 if run); Director decision on the result; CHANGELOG entry with this spec's sha256.

## 7. Out of scope
Any dashboard or payload binding; map-matched route as a covariate in winter work; ERA5 or weather forcing; rolling-resistance or road-load modelling (no road-load data exist); route classification as urban/non-urban replacement of the published split; payload (belt) sensitivity; the ingestion-stage hook.

## 8. Questions for the Director
(a) Is the OBD-GPS-versus-cloud validation set a sound design for P2, given its selection (bursts, not the steepest driving), or should P2 also carry a stratum by logged-altitude range? (b) Are the R2 thresholds defensible against a 30 m DEM with several metres of vertical error at L = 500 m? (c) Should G3 regeneration use the potential-energy term at all, given the assumed mass, or only grade-class stratification? (d) Is the unmatched fallback acceptable as a labelled sensitivity?
