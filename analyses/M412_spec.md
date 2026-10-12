# M412 spec (Rev 1): dashboard binding of the M410 serial-dependence block (reporting-only)

Status: written before the final gates. Branch `claude/next-milestone` from `main` (b05a40c, M411). Reporting-only: no estimator, payload leaf, headline or TOST decision changes; `drive_master.csv` MD5 `64dfd0cbff3db404d9b83e180f777525` unchanged. Authority: Director ruling `analyses/M410_director_ruling_2026-10-12.md` (reading sentences, forbidden readings, disclosures; "binding = separate milestone"); owner direction "go as you recommend" (2026-10-12).

## What is added
`buildS` gets `serialDependence: A.serialDependence || null`. One panel (`data-serial-dependence="true"`) in the Health tab, directly after the M407 inference-sensitivity panel. Every figure and every sentence about the result binds to `S.serialDependence.*` (and the M406 rows in `S.dependenceSensitivity.*` for the combined reading); the panel types no number.

## Panel content (Director sentences, verbatim from the payload where the payload has them)
1. Per series: rho_1 with pairs and the week-resampling interval; the rule statement and the harness power disclosure from the payload ("not supported ... not evidence of absence ... moderate dependence is not excluded"); rho_2 and rho_3 as descriptive only with the multiplicity note; the original pooled statistic labelled "original statistic (Rev 1)" with agreement/disagreement; the forking-path note; the bootstrap-shift sentence with the bootstrap median.
2. Table of the five new rows in the fixed order (HAC 3/7/14 days with normal interval, SE and t(W-1) interval; moving block 7/14 days with blocks per draw and draw-size range) and the AR(1) GLS row marked "separate estimator, outside every rule".
3. Combined reading across the ten OLS-based rows: cell spread "procedure-dependent: k of 10 OLS-based rows exclude 0; the lower bound changes sign across procedures; the upper bound is similar" (k from `rowsRule`, similarity computed); resistance proxy: its classification verbatim ("every row includes zero").
4. Semivariogram (descriptive), AR(1) variance-inflation diagnostic with the attenuation caveat, the misspecification control with its descriptive sentences (no seasonal reading).
5. Harness table (rule support for both statistics and the CR1 / HAC 7 d / moving block 7 d coverage, rate +/- Monte Carlo error, four scenarios) with the harness note, and the limits.
6. The standing statement "trend not resolved; equivalence not established; no stability or SOH claim" is repeated per series and is unchanged.

## Wording
Forbidden readings (Director): no/absent serial dependence, days independent, CR1 adequate, HAC/block/GLS as corrected or primary, rho_2 as support or weekly cycle, rho drop read as seasonal, VIF read as "adds only x %", HAC L3 exclusion as tighter evidence; plus the M407 list. Language rule `M410-serialdep-readings` and the semantic-gate check enforce them on the rendered panel.

## Acceptance
`node build_html.js`, `validate_jsdom.js` (0 console errors), `dump_tabs.js`, `semantic_gate.py` (new A2 REQUIRED checks per Health mode), CI unit list, `release_check.py`, CHANGELOG `M412`, dashboard presented (SendUserFile render) and committed with its sources (`xtrail_summary.jsx`, `summary_arrays.json`, `cohort_arrays.json`).
