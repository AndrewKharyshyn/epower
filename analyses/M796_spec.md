# M796 spec: per-drive count histogram of stop-and-go cycles (audit Wave C item 3)

Rev 1. Committed BEFORE any result of this milestone exists. Owner plan 2026-11-28 ("#3 histogram"). Audit item 3, "How often stop-and-go repeats": "If the raw drive-level distribution becomes available, replace the cycle plot with a compact count histogram or add subtle dots." New per-drive payload, so: spec, Director review, implementation, blind audit, Director decision (skill `new-analysis`).

## 0. Verified state (read from the repository)
- `S.crawlStopGo` (M183, `compute_summary_arrays._crawl_stop_go`) holds `byDriveType.<type>.cyclesPerDrive` = {median, p25, p75, p95, n} (the box plot "Stop-and-go cycles per drive", `xtrail_summary.jsx` around the CrawlStopGo view), `nDrivesCovered` 712, `nStopGoCycles` 3252, `smallDenominatorDriveTypes` ['highway', 'mixed_highway']. Drive-type n: urban 615, mixed_highway 39, mixed 34, highway 23, unknown 1.
- The per-drive counts exist only transiently inside `_crawl_stop_go` (list `per`, field `nCycles`, from `_csg_grid` and `_csg_events(g)` with the default thresholds); no per-drive value is published.

## 1. Estimand and nature of the block
Descriptive display of values already computed, drive by drive: the number of stop-and-go cycles of each covered drive, under exactly the M183 definition and thresholds (`_csg_events` defaults, unchanged), and the drive's type (`drive_type` of the master). No new estimand, interval, test or verdict; the existing medians and intervals stay as they are. The histogram shows the shape of the per-drive distribution (many drives with few cycles, a long tail) that the box plot hides. Wording: "stop-and-go cycles per drive"; a count of cycles on a drive, not a rate and not a property of the car.

## 2. Population
The M183 population (drives for which `_csg_grid` and `_csg_events` return a result: 712 of 717 at the last run), by `drive_type`. No new exclusion. Cohort views (Warm / Shoulder / Cold / Compare) are not extended: the histogram is drawn only in the all-data view and says so.

## 3. Method
- New tool `tools/stopgo_per_drive.py` imports the existing private functions `_csg_grid`, `_csg_events` from `compute_summary_arrays` (the same code the box plot uses; nothing is reimplemented) and writes a tracked sidecar `stopgo_per_drive.csv` (columns: file, date, drive_type, raw_sha256, method_version, n_cycles, n_stops, starts_low_speed, low_speed_time_s, duration_s, has_iv) keyed by raw sha256 and a source hash of the two functions, full precision, incremental (only new or changed files), the only writer, `--check`, `--rebuild`, `--dry-run`, `encoding="utf-8"` on every open.
- Payload block `stopGoPerDrive` (additive splice with a stamp, allow-list `/stopGoPerDrive`): per drive type {nDrives, counts for integer cycle counts 0..20 and an overflow bin "21 or more", median, p25, p75, p95 recomputed from the sidecar, support flag n < 30}; reconciliation block; provenance (master MD5, sidecar sha256, source hash, spec Rev). No per-drive file names in the payload.
- Ingestion: stage `stopgo_per_drive` in `tools/ingest_stages.json` after the stage that refreshes `crawlStopGo`, with restamp policy `regen`, so the histogram follows the corpus; `release_check.py --check` run; `m513_replay` check entry.

## 4. Decision rules and gates (frozen before any result)
- G1 identity with the published box plot (STOP on a miss): sum of `n_cycles` equals `S.crawlStopGo.nStopGoCycles`; the covered drive count equals `nDrivesCovered`; for every drive type the n, median, p25, p75 and p95 recomputed from the sidecar equal `byDriveType.<type>.cyclesPerDrive` (the published two-decimal rounding), and the sum of counts over all bins equals the type's nDrives.
- G2 determinism: a second run of the tool is byte-identical (sidecar and block); an incremental run reproduces a `--rebuild`.
- G3 isolation: only `stopGoPerDrive` and its stamp change in `summary_arrays.json`.
- G4 known-answer test `tests/synthetic/test_stopgo_per_drive.py`: binning (0, 20, 21, overflow), median/percentile identity with `numpy` on a planted list, sidecar keying by sha256 and version, G1 against the live payload.
- G5 view test (`test_stopgo_histogram_view.js`): one panel per drive type with n >= 2 drives, bar counts equal the payload, panel n printed, small-n panels flagged, no cohort-view rendering, axes shared; language gate, semantic gate, `release_check.py`, CI list, `validate_jsdom.js`, `tools/engine_on_sites.py` and `tools/ci_local.py` run locally BEFORE the first push (lesson of M792/M795).
- Falsification of the display claim "most drives have only a few cycles and a few drives have many": the histogram prints the share of drives with 0-2 cycles and with 10 or more cycles from the payload; no sentence is typed as a claim, the sentence is generated from those two shares.

## 5. Display (implemented only after the Director decision and the blind audit)
- In the stop-and-go block, directly under the box plot "Stop-and-go cycles per drive": small multiples, one panel per drive type with at least 2 drives (the single "unknown" drive is listed in a note), shared x axis 0..20+ cycles, y = share of the type's drives (so 615 and 23 drives are comparable as shapes), the count printed on hover and the drive count in the panel title, small-n types (n < 30) marked "few drives", the median from the payload drawn as a thin marker and labelled, the existing box plot and its numbers untouched. Caption generated from the payload: n drives per type, the share with 0-2 cycles and with 10 or more.
- Not an article figure.

## 6. Out of scope
- Engine starts per 10 minutes per drive and pack energy per cycle (other panes of audit item 3); cohort extension; any change to M183.

## 7. Questions for the Director
- Q1 Is a display-only per-drive payload (counts by drive type, no new estimand) acceptable, with a blind audit limited to reproducing the per-drive counts from raw bytes by an independent implementation of the M183 definition (given in words) plus the master reconciliation?
- Q2 Bins 0..20 and "21 or more", y as share of drives, small-n flag at n < 30: acceptable?
- Q3 Should the page keep the existing "typically" style lead of the box plot, or should the lead sentence now be generated from the payload quantiles only?
- Q4 Wording rules (drive type, small n, no comparison between types as an effect).
