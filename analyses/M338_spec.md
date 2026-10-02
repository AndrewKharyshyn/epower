# M338 single E10 fuel-energy basis for the SoC-balanced scenario (audit C05): pre-registered spec rev 1 (work in progress: Director review pending)

Origin: audit v3 C05 (`_HF_LHV = 8.9` kWh/L in `compute_summary_arrays.py:11558` vs the E10 constants in `model_constants.py`: 751 g/L x 41.15 MJ/kg = 8.58435 kWh/L); M334 `fuelContract` discloses the two unharmonised bases (`lhvStatus`). The audit estimates the stored fleet correction moves by about -0.00776 L/100 km. Actual fuel composition remains unmeasured; E10 is an assumption, not a measurement.

## Scope (moves a stored figure: own spec, blind audit, Director decision)
1. Single source: the SoC-balanced builder takes its LHV from `model_constants` (RHO_G_PER_L[0] x LHV_MJ_PER_KG[0] / 3.6 / 1000 kWh/L) instead of the literal 8.9. The `methodology` string states the value from the same constant (no typed literal).
2. Only the key `socBalancedFuel` is recomputed (additive leaf-splice pattern: compute only the changed key, deep-diff, splice changed leaves). `run_pipeline()` and the compute_summary_v6 CLI are NOT run.
3. `fuelContract` (script-written) is rebuilt by `tools/fuel_contract.py`: `lhvStatus` becomes "harmonised (M338): one E10 basis" when the two constants are equal within 1e-6, the banner sentence "not harmonised (audit C05)" is rendered only while they differ (bound to the payload, not hand-edited).
4. Not in scope: CAP_KWH (stays 2.1, verified:false; the 5 Ah OEM-rated lead is untouched), the eta sweep {0.25,0.30,0.35}, the GTR block (already E10), any other key, the article.

## Verification plan (pre-registered)
- C0 control (before any change): re-run `_soc_balanced_fuel` UNCHANGED (LHV 8.9) from the staged raw (`raw_only/`) and the live master; the result must equal the stored `socBalancedFuel` leaf-for-leaf. If it does not, STOP (the stored block is stale or not reproducible; report the leaf differences, no change applied).
- C1 change: recompute with the E10 LHV. Expected structure (known-answer): every `dfuel = dE/(eta*LHV)` scales by 8.9/8.58435 = 1.03678, so fleet SoC-balanced L/100 km, `fleetDelta`, per-trip correction statistics and the bootstrap CI move; raw fleet L/100 km, litres, km, dSoC, the regression (fuel ~ dist + dE) coefficients except the dE coefficient (not used), `nDrives`, `nDays`, `dateSpan` do not. Any leaf outside {lhvKwhPerL, byEta[*], socBalancedFleetL100, socBalancedFleetDelta, socBalancedFleetBoot, methodology, regression leaves that depend on a rescaled regressor} changing is a STOP.
- C2 independent check: `analytical-auditor` blind reproduction of the new socBalancedFleetL100, delta and bootstrap CI from raw + master using only the definitions (accumulator delta, speed-integral distance, dSoC end-start, CAP 2.1, eta 0.30, LHV = 751 g/L x 41.15 MJ/kg), seed 42, 4000 draws, calendar-day clusters.
- C3 magnitude check against the audit's -0.00776 L/100 km: reported as a difference to a reference, not tuned to.
- Wording/gates: the Fuel banner and SoC-balanced scenario text bind to the payload (lhvKwhPerL); language gate unchanged; release_check, semantic gate, jsdom green; CHANGELOG states the old and new stored values (before/after table from the script).

## Decision rules
- If the new fleet correction lies outside the previous 95% bootstrap CI of the balanced fleet L/100 km, escalate to the Director (KPI outside its previous CI trigger). No article figure; no new headline.
- The three-way "EFC" and the verified:false CAP/20,000 GTC flags are untouched.
