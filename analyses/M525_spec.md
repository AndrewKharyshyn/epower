# M525 spec (Rev 1, DRAFT for Director review): refresh the OPT-band occupancy (rpmFinding) on the live corpus, with a day-clustered interval, as an ingestion stage

Status: PRE-REGISTERED DRAFT, 2026-10-27, written before any result exists. Owner: Andrii (chat, 2026-10-27: "continue"). Origin: M524 (rpmFinding is a one-off block on 397 of 410 drives, not refreshed, absent from `staleBlocks`; shown as 63.4 % in the best-point list item). Numbering: this is the former "M526"; the payload-string work (loadProxyBasis, tone check, raw 5 rpm recompute, motored-share interval) becomes M526.

## 1. Estimand

OPT-band occupancy = duration-weighted share of ENGINE-ON time (rpm >= 300, 1 Hz grid, the rpmDistribution convention) whose logged engine rpm lies in [1850, 2150] rpm (`model_constants.OPT_LO/HI`), pooled over the drives of the live corpus. Descriptive observed occupancy of a logged signal; NOT an efficiency, optimum-operation or BSFC claim (the optimum itself is an external OEM value).

## 2. Method (byte-faithful to the existing pass, plus a clustered interval)

1. Per drive, the 1 Hz grid exactly as `compute_summary_arrays._RawAccum.add` / `rpm_opt_pass.py` (resample 1 s mean, ffill limit 15) -> histogram on FINE_EDGES = RPM_HIST_EDGES with 1850 and 2150 inserted. Population = all `drive_master` drives with a readable raw file (same as rpmDistribution, 606).
2. FAITHFULNESS GATE (STOP if it fails): collapsing the fine bins back to RPM_HIST_EDGES reproduces the stored `rpmDistribution.pooledHours` (engine-on total and every bin) to rounding (stored values are rounded to 0.001 h): max abs difference <= 0.002 h per bin.
3. Primary estimate = direct raw ratio (the former "raw cross-check"): seconds in [1850, 2150] / engine-on seconds, pooled. The former "anchored" estimate (stored bin totals + sub-bin shares) is reported as a secondary and the difference is shown (method disagreement is reported, not tuned).
4. Interval: day-clustered percentile bootstrap, `numpy.random.default_rng(42)`, `integers(0, D, (B, D))`, B = 4000, ratio of sums inside every draw, calendar day = cluster; n reported as drives and days. Sensitivities (descriptive): per-drive median and IQR of the per-drive share; the same estimate with 1850/2150 moved +/-50 rpm (edge sensitivity: a band-definition range, not a CI).
5. Output: sibling top-level payload key `rpmOptBand` (+ stamp) written by `tools/rpm_opt_band.py` (read-only on raw; reuses the project raw loader and `XT_RAW_DIR`); the old `generatorTractionRecon.rpmFinding` stays unchanged and is labelled superseded for the numeric leaves (only `nissanClaimPct` and the OEM context keep being read). Ingestion stage `rpm_opt_band` after `rpm_distribution`-producing stages, stamp dependencies declared (inputs: the pooled rpmDistribution block, master hash, the spec), so the block can no longer go stale silently. Additive splice, deep-diff: only the new key + its stamp (+ the `staleBlocks` note for the superseded leaves) change.

## 3. Display (after the numbers exist; Director decides)

The best-point list item binds to `rpmOptBand` (pct, interval, drives, days, engine-on hours) and drops the "computed once on 397 of 410 drives and not refreshed" disclosure when `corpusWideDrives` equals the live count. The parenthetical "(steady cruise / generator-charging load)" (`empiricalLoad`) is not derivable from an rpm histogram and is removed from the display (or kept only as the OEM's own wording, labelled). The Nissan claim ">80 % at best point" stays as external context, "not the source". Language: "observed occupancy of logged rpm", never "efficiency", "optimum operation achieved" or "measured".

## 4. Acceptance and falsification

- A1 faithfulness gate (above) passes; known-answer test on a synthetic drive set (hand-computed fine-bin counts, a drive with no engine-on seconds, a day with one drive, duplicates in `time`).
- A2 the new pooled engine-on total equals `sum(rpmDistribution.pooledHours[1:]) * 3600` within 1 s per bin rounding; the old 63.4 % is reproduced when the pass is restricted to the 410-drive corpus file list (if the list is recoverable; else reported as not reproducible, not a STOP).
- A3 a blind `analytical-auditor` reproduces the pooled share, the interval and n from raw (claim + data path only).
- A4 escalate to the Director if the live estimate leaves [previous 63.4 % +/- 2 pp] or the interval half-width exceeds 3 pp, or the anchored and direct estimates differ by more than 0.5 pp.
- Stop: faithfulness failure; any change to an existing payload value or key; the per-drive pass exceeding the ingestion time budget (+120 s).

## 5. Gates and process

py_compile, `node build_html.js`, `node validate_jsdom.js`, `node dump_tabs.js` THEN `semantic_gate.py`, new tests in CI, `release_check.py`, full CI unit list locally (background), CHANGELOG M525 (spec SHA-256 before the first run; first output kept; run-once lock), blind audit, Director decision. Display edit is a separate step after the Director sees the numbers. No article figure; any use in the article needs the Opus audit and Andrii's sign-off.

## 6. Questions for the Director

Q1 Sibling key `rpmOptBand` (recommended, M520 precedent) vs in-place update of `rpmFinding` leaves (changes the `generatorTractionRecon` stamp). Q2 Direct raw ratio as the primary, anchored as secondary: agree? Q3 Edge sensitivity +/-50 rpm: right size, or declare it differently? Q4 Is an ingestion stage (extra raw pass) justified, or run on demand with a declared-dependency stamp that fails the release gate when stale? Q5 Remove `empiricalLoad` text from the display?

## 7. Rev 2 (2026-10-27): Director review (verdict "revise, minor"); incorporated, no re-review needed

- **Rulings.** Q1: sibling key `rpmOptBand`; `rpmFinding` numeric leaves stay byte-unchanged and get a superseded label (the only allowed change to an existing value is the `staleBlocks`/superseded note). Q2: direct raw ratio primary, anchored secondary; once the faithfulness gate passes they must agree closely: the A4 disagreement trigger is tightened from 0.5 pp to 0.1 pp. Q3: edge sensitivity +/-50 rpm AND +/-100 rpm (1900-2100, 1800-2200, 1750-2250; the M375/sensitivity_gtr precedent); extra fine edges pre-registered: 1750, 1800, 1900, 2100, 2200, 2250; a band-definition range, never a CI. Q4: ingestion stage with declared-dependency stamps, within the +120 s budget (a tracked per-drive sidecar `rpm_opt_band_sidecar.csv` keyed by the raw-file SHA-256 means only new or changed drives are re-parsed); if over budget, on demand with `release_check` failing on a stale stamp. Q5: `empiricalLoad` parenthetical removed from the display (only as quoted OEM wording, labelled).
- **Gate and tests.** Faithfulness gate unchanged (collapsed fine bins reproduce the stored `rpmDistribution.pooledHours`, max abs difference <= 0.002 h per bin) plus an engine-on drive-count check against `rpmDistribution.coverage.nDrives`. Known-answer additions: rpm exactly at 1850 and 2150 (the estimand is the CLOSED band [1850, 2150]; the histogram is half-open, so the tool adds the count of samples equal to 2150), ffill gaps of 15 vs 16 s, the 300 rpm engine-on threshold.
- **A2.** Failure to reproduce the 410-drive list is labelled provenance sensitivity, not a STOP.
- **Uncertainty additions.** Per-drive median/IQR and n_days; descriptive cadence-stratified sensitivity (slow vs fast logger regime from `cadence_regime.csv`; ffill-15 may bias occupancy; B6 precedent); `ens_outlier_v2`-excluded sensitivity (the canonical exclusion). Limits stated: serial day correlation is not captured by the day bootstrap; rpm is ECU-reported via the app, resampled to 1 s means; band edges come from external OEM context.
- **Language.** "observed occupancy of logged rpm"; never efficiency, optimum operation achieved, measured, corrected; not comparable to the Nissan > 80 % claim (context, not the source).
- **Process.** The new tool imports `model_constants` for OPT_LO/OPT_HI (no hard-coded copy); the spec is hashed before the first run (CHANGELOG); the first output is kept (run-once lock); display step ordering: numbers, blind audit, Director, then a separate display edit (update `test_m524_xlines.py`; drop the disclosure only when coverage equals the live engine-on drive count). No Andrii sign-off required.
