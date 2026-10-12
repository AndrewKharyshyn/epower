# M413 step-0 inventory: where the legacy reference CAP_KWH = 2.1 kWh and the exposure columns reach the outputs (static trace)

Provenance: read-only static trace by an Explore subagent (2026-10-12), brief in the M413 spec; the main session spot-checked the anchor lines against the code (`compute_drive_summary_v6.py:245` CAP_KWH = 2.1; `:692-693` gtc = thr/CAP_KWH, fce = thr/(2*CAP_KWH); `:705` cap_ah = CAP_KWH*1000/v_nom; `:753` dual_peak_Crate; `:889` rf_efc; `compute_summary_arrays.py:57`, `:143` SCENARIO_THRESHOLD_GTC = 20000, `:771` gtcSum, `:1154` Crate loop; sidecar columns `ah_throughput.csv` incl. `kwh_per_ah_throughput`). This is a static trace, not the transitive control-build diff: items under "unknowns" are open and the control build (spec M413, gate (e)) is the authority for the final expected-changed set. Line numbers were valid at HEAD 1eb4bed.

```json
{"seeds":[
 {"id":"CAP_KWH=2.1 (one constant serves BOTH exposure and SoC bookkeeping in compute_drive_summary_v6 and compute_summary_arrays)",
  "defs":["V6:245","CSA:57","CSA:160-190 (CONSTANT_PROVENANCE; CAP_AH_RATED 5.0 at 181)","CSA:143 SCENARIO_THRESHOLD_GTC=20000","energy_uncertainty_mc.py:59-60,171-172,205-206,315-320","energy_mc_precompute.py:63,161,326","sustained_current_peaks.py:44,80","c1_joint_temp_crate.py:31,118,134","fuel_recon.py:55,83-84","build_assumptions_registry.py:74-79,172-176","ingest_e4orce.py:85-96,147,161,170","crosscheck_vehicles.py:70,176-180","tools/capacity_tests.py:24,62-102","tools/capacity_basis.py:535"],
  "feeds":[
   {"output":"master gtc, fce (V6:692-693); cap_ah_est (V6:705-707)","kind":"a"},
   {"output":"master soc_delta_kwh, energy_residual_kwh (V6:869-871)","kind":"b (SoC bookkeeping)"},
   {"output":"cycleBySpeed[].rate + seasonalCharts.CycleBySpeed (CSA:4369; raw pass accumulates |I*V| kWh, no Ah accumulator)","kind":"a"},
   {"output":"metricConvention.{gtc,fce,efcStandard,gtcOverStandardEfc,fceOverStandardEfc,capKwh} (CSA:15579-15591)","kind":"a"},
   {"output":"energyUncertaintyMC.grossThroughputMC.{gtc,fce}, capacityNote (kWh Monte Carlo draws / 2.1; precompute holds kWh curves only, NOT rescalable to Ah)","kind":"a"},
   {"output":"energyUncertaintyMC.independentIntegrationCheck.coulombCrossCheck.* (Ah to SoC pp via 2.1 and V)","kind":"b"},
   {"output":"evTraction.bufferLimit.{usableKwh,rangeKm,budgetFractionPct} (CSA:1870); mountainPattern.descentBudget (CSA:8407)","kind":"b"},
   {"output":"socBalancedFuel (_HF_CAP_KWH CSA:11892,11945); carOffStandby (CSA:15239); offsetUncertainty.capacitySensitivity (CSA:16001-16019)","kind":"b"},
   {"output":"bufferImpulse.{capKwhAssumed,capacityMultiple} (CSA:6191,6252) + crossVehicle.eventDetectors.bufferImpulse.primary","kind":"c (energy of start events / 2.1 kWh)"},
   {"output":"officialDisclosureCorrelation.chemistry.{capacityKwhEst,powerEnergyRatioC} (CSA:2779-2780)","kind":"c"},
   {"output":"assumptionsRegistry.entries[cap_kwh], constantProvenance.CAP_KWH text","kind":"c"},
   {"output":"fuel_recon charge-sustaining fallback (dormant); sustained_current_peaks.csv (standalone probe); c1 probe (ported into V6 767-811)","kind":"b/c"},
   {"output":"e4orce_master.csv gtc,fce,cap_ah_est,*_Crate (ingest_e4orce loads V6 unmodified) -> crossVehicle","kind":"a"}]},
 {"id":"gtc, fce, efc_per100km (legacy ML feature = gtc/dist*100)",
  "defs":["V6:692-693","V6:1735 (efc_per100km)","V6:1140-1141,1160"],
  "feeds":[
   {"output":"meta.gtcSum, fceSum (CSA:771-772; sums all 554 rows)","kind":"a"},
   {"output":"cycleByType (CSA:1041-1042); cycleCumulative (CSA:1096)","kind":"a"},
   {"output":"cycleLife.{intensityGtcPerKm,highwayBlendedIntensity,projections[],cycleAtOdo} (CSA:2192-2231)","kind":"a"},
   {"output":"seasonalLife.{intensityGtcPerKm,rate,accumulated,annualCyclesPerKm,selectedConstant,observedConstant,hotTail,monthly} (CSA:3124-3133,3322,3347,3402)","kind":"a"},
   {"output":"fadeModes.capacity.rows[], officialDisclosureCorrelation.capacityFadeAnchor, observedMix (CSA:2600-2617, 2894-2910, 15956-15970)","kind":"a (compared against the fixed 20000-GTC threshold)"},
   {"output":"riskColdEngineBattery.compare.gtcPer100km (rank test); dailyFingerprints gtcMean (k-means feature); interDriveCarryover followingGtc; crossVehicle...kwhThroughputFraming","kind":"a (rank/z-score: uniform scale invariant, per-drive V_eff change not)"},
   {"output":"kLadderScenarios.corpus.fceSum; ledgerCrossCheck.*.fce; seasonal_drive_master.csv gtc","kind":"a"},
   {"output":"ens_extreme (V6:1769) and v5 flags via efc_per100km -> meta.exclExtreme","kind":"c (diagnostic; ens_outlier_v2 unaffected)"},
   {"output":"summary_config.json: 74 sessionGroups + 82 sessions notes with GTC/FCE numbers; tools/m368_ledger_round.py; tools/extend_session_ledgers.py","kind":"a (text literals)"}]},
 {"id":"*Crate columns, cap_ah_est (T1_at_peak_Crate is a temperature: independent)",
  "defs":["V6:707","V6:753","V6:759","V6:763"],
  "feeds":[
   {"output":"cRatePoints, cRatePointsAK, cRateAxes, cRateRefLines(AK) (CSA:1154-1166, 7931-8090)","kind":"a (cPerA becomes constant 0.2)"},
   {"output":"records[].value strings 'N A (x.xC)' (CSA:1336,1392-1400,1477-1514)","kind":"a"},
   {"output":"seasonalLife.cRateObserved; riskColdEngineBattery.coldPackChargeCrate*; crossVehicle.cRate.dualPeakCrate","kind":"a"},
   {"output":"cohort_arrays.json charts.RegenChart.metrics.regen_peak_Crate","kind":"a"},
   {"output":"officialDisclosureCorrelation.rows[0].ours (cap_ah_est median vs the official 5.0 Ah becomes a tautology), fadeModes.capacity.whyNoObservable text","kind":"c"}]},
 {"id":"rf_efc (V6:889): independent of CAP_KWH (SoC-only rainflow)",
  "feeds":[{"output":"meta.rfEfcSum, rfCycleCumulative, kLadderScenarios denominator, capacityBasis.exposure.socRainflowEFC, loggerCadence","kind":"independent"},
          {"output":"ledgerCrossCheck.{matchedAll,matchedClean}.{ratio,biasPerDrive,maePerDrive,excessPct} compare rf_efc to fce","kind":"a via the fce comparator"}]},
 {"id":"eligibility: RESIDUAL_MAX_KWH, f_domain, energy_residual_kwh_corr",
  "feeds":[{"output":"ens_invalid == ens_outlier_v2 == f_domain_2p -> canonical-clean for every pool","kind":"b"}]}],
"top_level_payload_keys_dependent_on_exposure_normalisation":["meta(gtcSum,fceSum,exclExtreme)","cycleByType","cycleCumulative","cycleBySpeed","cycleBySpeedMeta","cycleLife","seasonalLife","fadeModes","officialDisclosureCorrelation","observedMix","metricConvention","riskColdEngineBattery","cRatePoints","cRatePointsAK","cRateRefLines","cRateRefLinesAK","cRateAxes","records","energyUncertaintyMC","ledgerCrossCheck","kLadderScenarios(corpus.fceSum)","dailyFingerprints","crossVehicle","seasonalCharts(CycleByType,CycleBySpeed)","assumptionsRegistry","constantProvenance(text)","capacityBasis(additive; already holds rated_5.0Ah: gtc-analog 865.58, fce-analog 432.79 vs legacy 747.03 / 373.51, rf 395.18, n=538)"],
"keys_with_retracted_or_scenario_semantics":["_retractedLifeEol (CSA:18113-18153) nulls year leaves in cycleLife, fadeModes, seasonalLife, officialDisclosureCorrelation, observedMix, realisticBlend","kLadderScenarios (flatCrossingYr, byK[].yr, plausibilityCeilingYr null; m(k) kept)","cycleLife.scenarioThresholdGtc/thresholdSensitivity (20000 GTC, verified:false, scenario, not rebased)","fadeModes.capacity (MODELED ONLY)","seasonalLife (model extrapolation)","energyUncertaintyMC.capacityNote (2.1 vs 1.8 scenarios)","capacityBasis (dual report, automaticSwitch False)","offsetUncertainty.capacitySensitivity","socBalancedFuel (scenario correction)","constantProvenance.CAP_KWH/CAP_AH_RATED"],
"per_drive_vs_aggregate_notes":["Ah-throughput/5.0 vs kWh/2.1 is NOT a uniform constant: per-drive factor = 2100/(5*V_eff), V_eff = kwh/Ah (median 360.4 V, ah_throughput.csv col kwh_per_ah_throughput); ratio-of-sums (class intensities, per-100km) change by class-specific factors; aggregate ratio 1.1587 (capacityBasis n=538)","cap_ah_est is per-drive 2100/V_pack_median; the rated basis makes it constant 5.0; per-drive C maxima / argmax drives can change; records pchg_c uses the corpus-median cap (CSA:1336) while the others use per-drive","Ah sidecar ah_throughput.csv (540 drives, raw-current integral, offset-uncorrected like gtc) exists; master has 554 rows, 14 no-pair rows NaN gtc","meta.gtcSum sums all 554; cycleLife/observedMix use ens_outlier_v2-clean distance-weighted ratio-of-sums; capacityBasis n=538; ledgerCrossCheck n=540","master gtc is rounded to 4 dp per drive"],
"risks":["V6:245 and CSA:57 must be split (exposure Cref vs SoC kWh/pp); a global change flips eligibility (RESIDUAL_MAX_KWH 0.35 = 2.1/6) and offsets","rf_efc/fce ratio flips (matched 1.0605 -> about 0.91): ledgerCrossCheck interpretation/note and a hard-coded JSX sentence ('rainflow above FCE')","rf_efc wrongly labelled CAP-dependent in tools/m368_fmt.py:4, crosscheck_vehicles.py:41, ingest_e4orce.py:170, config notes","hard-coded JSX text at 617-619,1156,2083,2845 ('2.1kWh basis'),3520,10882; gates pin 2.1 text: semantic_gate.py:119,232-236,458,531-534; language_gate.py:274,301-302; tests test_capacity_basis / test_capacity_tests / test_m399_wording / test_m404_wording / test_crate_axes.py,.js / test_schema_contract.py","the 20000-GTC threshold is not rebased: rate/threshold comparisons change meaning","energy MC and cycleBySpeed need new Ah inputs (not rescalable)","ens_extreme/exclExtreme and v5 flags may flip (non-canonical); ML columns restored from archive per V6:1647-1663","tools/m358_splice.py:28-39 asserts C == A/cap_ah_est; test_crate_axes uses cPerA/secondaryAxisMode"],
"unknowns":["restore-from-archive implementation (tools/ingest_core.py) not traced","masterRefitAudit / determinism / MD5 gates: column scope not verified","dailyFingerprints and bufferImpulse JSX use not verified","tools/cadence_* use of fce","regen_seasonal_raw CycleBySpeed path not traced","other hard-coded GTC/C numbers in the JSX beyond the lines listed"]}
```
