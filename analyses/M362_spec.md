# M362 spec (Rev 1): Engine ON/OFF cycling chart (starts / 100 km by drive class): distribution summary instead of min-max, short-trip denominator disclosed

Status: work in progress, Director review pending. Owner request (Andrii, 2026-10-03): the urban bar reaches 500 starts/100 km; is it real?

## 1. Finding (recomputed this session with the pipeline's own detector, `tools/engine_start_rate.build_hz/onsets`: RPM > 300, 1 Hz grid, runs >= 2 s)
- 500 = one drive (2026-09-27_17-49-23): 1.2 km, 6 RPM-onset starts in ~7.7 min. Real under the detector, but a small-denominator figure. Next: 454 (0.44 km, 2 starts), 375, 357, 333 per 100 km, all on drives of 0.4-1.4 km.
- Urban: 408 drives, 118 under 2 km, median distance 2.5 km, 25 drives above 200 per 100 km (all short). Per-drive mean 105, median 93, pooled (sum starts / sum km) ~100. Highway 47, mixed 71, mixed-highway 77.
- The chart's range bar is the per-drive MIN-MAX (`engineStartsByType[].lo/hi`) and the dot the unweighted mean of per-drive rates (`avg`): the bar reports a tiny-denominator extreme as if it were the span of urban driving. The axis caption says "cold-starts", but the counts are detector-defined RPM onsets (all starts, not only cold).

## 2. Change
- New additive fields on every class entry of `engineStartsByType` and its cohort copies (`seasonalCharts.charts.EngineStartsByType.data.{all,warm,shoulder}`): `n` (drives), `nDays`, `p10`, `p25`, `median`, `p75`, `p90`, `pooled` (ratio of sums, starts per 100 km), `nShort` (drives with distance < 2 km), `shortKm` (2.0 km threshold constant), `maxDrive` (file of the maximum) and `maxKm` (its distance). `lo`, `hi`, `avg`, `color`, `label`, `classKey` and every other key are unchanged (byte-identical).
- Computed by new `tools/m362_splice.py` from the pipeline frame cache with the SAME detector (known answer: per-drive rates reproduce the stored `lo`/`hi`/`avg` and the M343 pooled values `engineStartRate.byClass[*].est` within rounding; mismatch STOPS), additive leaf-level splice, deep-diff allow-list, never writes the master.
- Chart (`EngineCyclingChart` starts view): thick bar = P25-P75, whisker = P10-P90, dot = median (value printed), diamond = pooled rate; text per row: "n drives, k under 2 km"; the min-max and its file/distance move to the hover title ("max 500 = 1.2 km drive") and a footnote. Axis caption: "Engine starts (RPM onsets) per 100 km - dot = median, bar = IQR, whisker = P10-P90, diamond = pooled (sum starts / sum km)". Footnote: per-100-km rates on drives under 2 km are denominator-unstable (one or two starts on a 1 km crawl reads as hundreds); the extremes are real detector counts, not measured ignition events; basis raw/, provenance-sensitive (F03).
- Compare (`CMP_BARS.EngineStartsByType`): value = median, whisker = P10-P90 where present, title adjusted ("median of per-drive rates; whisker P10-P90"); `avg`-based wording removed.
- Cohort support: classes below a minimum of 5 drives in a cohort show the median only with "n=k (below 5: no spread shown)" (Shoulder mixed has 1 drive).

## 3. Controls / tests
- Control: existing `lo`/`hi`/`avg` byte-identical; top-level keys other than `engineStartsByType` and `seasonalCharts` unchanged; new fields recomputed twice (determinism).
- `tests/synthetic/test_starts_summary.py` known answer on scripted per-drive rates and km (quantiles, pooled, short count, max drive); `test_starts_view.js` on the extracted view model (axis bound from p90 not max, short drives counted, n<5 handling).
- Gates: semantic gate A2 REQUIRED (caption wording, footnote, n and nShort bound to the payload); language gate RULES M362 for "cold-starts" in this caption ("Engine cold-starts per 100 km") and "per-drive range"; jsdom 0 errors; release_check.

## 4. Out of scope
No change to the detector, to `engineStartRate` (M343), to the 2 s run rule or to the class taxonomy. Dropping short drives from any published figure is NOT done (they stay in all statistics; only the chart no longer headlines the extreme).

## 5. Questions for the Director
1. Median dot + pooled diamond: acceptable pair, or one marker only? 2. P10-P90 whisker and the n >= 5 rule? 3. Any wording constraint on "real detector counts, not measured ignition events"?
