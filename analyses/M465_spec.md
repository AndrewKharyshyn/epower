# M465 spec: Cold cohort wherever the dashboard showed only Warm and Shoulder

Status: implemented with this milestone. Scope: display and additive payload extensions only; no new estimator, no change of any existing figure, no change of the regen, GTR-family or M119-v2 blocks.

Rules (existing, reused): Cold opens at >= 10 drives and >= 3 days (`cohortMeta.cold.inferenceAvailable`, 13 drives on 5 days). A cell with fewer than 5 calendar days (the regeneration floor, >= 10 drives on >= 5 days) is exploratory: point estimate only, no interval, no difference, marked "~" / "exploratory". Pointwise warm-up CIs keep the existing rule (>= 10 trips on >= 7 days). Cold is a display band: no statement of a temperature or season effect.

Changes
1. `ComparisonCube` Compare mode and the default Compare selection include Cold when available (the cube payload already holds the cold rows; cube cells with < 5 days are drawn without interval).
2. Urban contrast: `comparisonCube.urbanContrast.bands[].cold` and `descriptive.cold`, written by `m297_comparison_cube.py` (ratio of sums over clean urban cold drives; `ci95: null`; no difference). Cold has no urban trips >= 3 km, so bands 3-10 and >= 10 km are null (not observed).
3. Fuel warm-up trajectory: `fuelWarmup.groups["cold|<band>"]` written by `tools/fuel_analytics2.py` (same pointwise rule; points only below it), shown in Compare.
4. GTR accounting difference table: a Cold column (values of `seasonalCharts.GeneratorTractionRecon.data.cold`, no difference). The GTR-family block itself is untouched (carried by decision).
5. Ratio guard in the drive-class cycle tiles (a missing class gave "NaN x vs highway" in the Cold view).
6. `dump_tabs.js` renders mode `cold`; `semantic_gate.py` checks C M465 (cold dumps exist, Compare/urban Cold wording, no interval in the payload). The language gate then runs on the Cold dumps.

Not built in this milestone (stated, not silent; each is a new or pre-registered analysis): `thermalSupportLedger.timeToThreshold` for Cold (M435 spec cohorts all/warm/shoulder, with reconciliation gates), `loggerCadence.stratified` Cold by regime (M380), `generatorTractionRecon.eligibilityAlignment` (frozen M375 record), `ThermalFuelPenalty` Cold view (`support_met_view_not_built`: needs the raw-pass builder plus audit).

Gates: deep-diff allow-list `tools/m465_diff_check.py` (only added cold keys, the urban caveat string and the fuelStates/fuelWarmup stamps may differ); known-answer test `tests/synthetic/test_m465_cold_extension.py`.
