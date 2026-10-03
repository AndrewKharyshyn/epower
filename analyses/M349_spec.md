# M349 spec (rev 1): NaN battery-current offset in fuel_recon.py (published GTR rows)

Status: work in progress, Director review pending; needs Andrii's sign-off before merge (moves the published GTR headline).

## 1. Defect (verified on disk)
`fuel_recon.py` (main, `--all`): `off = float(master[f].get('I_offset_A_applied', 0.0) or 0.0)`. `NaN or 0.0` is NaN, so the battery power is NaN, drops out of the traction sum, and f_gen = 1 by construction. Two PUBLISHED rows are affected: 20260813_145651 (2.2 km) and 20260813_150341 (4.6 km): gen->traction == traction gross, batt->traction = 0, f_gen = 1.0. 14 master rows have a NaN offset; only these two have a published fuel_recon row (20260512_195020 has none).
Fact found this session (`analyses/M349_effect.json`, script `tools/m349_nan_offset_effect.py`): the applied offset is ONE corpus constant: 475 calibrated drives, 1 distinct value (-0.3858 A). The two drives are simply not stamped; they are valid (ens_invalid False, ens_outlier_v2 False).
Same `or 0.0` pattern exists in `speed_split.py`, `crossval_gtr.py`, `sensitivity_gtr.py`, `simultaneity_gtr.py`, `tools/gtr_closure_diag.py` (the last skips NaN-offset drives explicitly). Out of scope except for the audit list in section 5.

## 2. Pre-registered effect table (script-written, control reproduces the stored `generatorTractionRecon.corpus` exactly)
Corpus (distance-weighted, `wire_gtr_seasonal.aggregate`): variants published / exclude / offset = corpus constant / offset = 0 in `analyses/M349_effect.json`. Headline fGen 0.467 -> 0.466 (any repair), gen->traction 8.64 -> 8.61/8.62, batt->traction 9.85 -> 9.88/9.89; the two rows go f_gen 1.0 -> 0.575 and 0.363 (constant offset) or 0.580/0.369 (zero offset).

## 3. Proposed repair (decision for the Director)
Primary: a drive whose master offset is NaN takes the corpus-applied constant (the single value shared by all calibrated drives), resolved by an explicit helper `resolve_offset(master_row, corpus_const)`; the helper raises if the calibrated offsets are not a single value (then the drive is excluded and counted). The count of drives that used the constant is logged and written to `analyses/M349_result.json`. Sensitivities reported, not tuned: exclude (n -2) and offset 0.
Rationale: same estimator as the other 475 drives; exclusion discards valid drives; zero is a different, unstated offset.
Not changed: any other script; `drive_master.csv`; raw; ML16.

## 4. Build (control, no new drive)
1. Known-answer test `tests/synthetic/test_fuel_recon_offset.py`: NaN offset with a synthetic constant-current drive -> battery power equals the constant-offset result (not NaN, not f_gen = 1); a NaN offset with non-single-valued calibrated offsets -> excluded and counted; calibrated drives unchanged byte-for-byte.
2. Rerun `fuel_recon.py` for the two files only (upsert) from `raw_only/`; deep-diff `fuel_recon_master.csv`: only those 2 rows may change (allow-list), every other cell identical. `tools/normalize_eol.py` after.
3. Rerun `refresh_gtr_headline.py` (headline + Warm/Shoulder splits), `tools/fuel_contract.py`, `tools/gtr_closure_block.py` (closure uses fuel-PID subset with non-NaN offset: expected unchanged; control verifies), and any consumer of the corpus GTR values; deep-diff `summary_arrays.json` against an allow-list of leaf paths (generatorTractionRecon corpus/flows/driveTypeSplit/productionCheck, seasonalCharts.GeneratorTractionRecon all/warm/shoulder, fuelContract numbers that cite them). Anything else moving aborts.
4. Post-step idempotence (`apply_m284_post.sh`, `normalize_eol.py`, twice, `cmp`).
5. Dashboard rebuild, gates, jsdom, semantic gate, release_check.
Wording: the displayed GTR f_gen figure changes by 0.001; text citing "0.467" is bound to payload, not typed (verify by gate). CHANGELOG states: defect repair; two published rows were f_gen = 1 by construction; sensitivity table.

## 5. Process
Director review (this spec) -> implement -> blind audit (analytical-auditor, Sonnet, high; give claim + data path: recompute the two rows and the corpus headline from raw with the constant offset; no author code) -> Director decision on the audited result -> CHANGELOG -> release_check -> PR (draft until Andrii signs off the headline change; NOT merged without his explicit sign-off).
Follow-up list (not in this milestone): the five other scripts with `or 0.0`.
