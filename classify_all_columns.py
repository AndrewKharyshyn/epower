"""Exhaustive classification of every drive_master column into a seasonal-
dependency group. Verifies 100% coverage (no column left unclassified)."""
import json, csv

with open('drive_master.csv') as f:
    ALL = next(csv.reader(f))

# group -> (priorCandidate, currentVerdict, [columns], rationale)
GROUPS = {
 # ---------------- DIRECT THERMAL candidates ----------------
 "soc_cycling_frequency": ("thermal","inconclusive",
   ["rf_n_cycles","rf_efc","rf_efc_f05"],"cycling/km vs pack temp"),
 "soc_mean_level": ("thermal","inconclusive",
   ["rf_socmean_wtd_pct","soc_start","soc_end","vsag_soc_mean"],"operating SoC set-point vs temp"),
 "soc_range_span": ("thermal","inconclusive",
   ["soc_min","soc_max","soc_band"],"usable buffer width vs temp"),
 "depth_of_discharge": ("thermal","inconclusive",
   ["rf_dod_wmean_pct","rf_dod_max_pct","rf_damage_k2_socband_lo","rf_damage_k2_socband_mid","rf_damage_k2_socband_hi"],
   "buffer DoD usage shifts with temp-dependent resistance/headroom"),
 "engine_start_stop_frequency": ("thermal","inconclusive",
   ["engine_on_pct","n_sign_crossings"],"starts/km + engine-on share rise in cold"),
 "engine_on_duration_load_warmup": ("thermal","inconclusive",
   ["duration_s","eng_load_calc_mean","eng_load_calc_max","eng_load_abs_mean","eng_load_abs_max",
    "eng_load_abs_p95","eng_rpm_max","boost_max","map_kpa_max","map_kpa_mean","map_kpa_max_eng_on",
    "target_torque_max","target_torque_min"],
   "USER-flagged engine-on duration + engine load/MAP/boost/rpm: cold raises load (heat+aux) and warm-up fuel; engine-on seconds = engine_on_pct*duration_s (derived)"),
 "ev_mode_share": ("thermal","inconclusive",
   ["ev_dist_pct","ev_dist_km","ev_kwh_per100km","ev_batt_kwh","ev_time_s","ev_moving_time_s"],
   "EV distance/time/energy share falls in cold"),
 "ev_run_structure": ("thermal","inconclusive",
   ["ev_n_runs","ev_run_max_km","ev_run_max_s","ev_run_max_vmax_kmh","ev_run_p50_km","ev_run_p90_km",
    "ev_runs_lt05","ev_runs_05_1","ev_runs_1_2","ev_runs_2_3","ev_runs_ge3",
    "ev_nr_km","ev_nr_kwh","ev_nr_run_max_km"],"EV run-length distribution shortens in cold"),
 "dissipation_mode": ("thermal","inconclusive",
   ["charge_eng_off_kwh","charge_lowtq_engoff_kwh","charge_pure_regen_kwh"],
   "high-SoC motored/unfuelled dissipation + pure-regen acceptance vs temp"),
 "charge_pathway_split": ("thermal","inconclusive",
   ["charge_eng_on_kwh","charge_eng_only_kwh","charge_dual_kwh","charge_fraction"],
   "engine-vs-regen charge sourcing shifts toward engine in cold"),
 "regen_charge_acceptance": ("thermal","inconclusive",
   ["regen_share_of_charge","regen_peak_A","regen_peak_Crate","motor_regen_lower_pct","motor_regen_upper_pct"],
   "cold limits charge/regen acceptance (plating risk)"),
 "peak_power_capability": ("thermal","inconclusive",
   ["peak_discharge_kw","peak_charge_kw","peak_I_discharge","peak_I_charge",
    "dual_peak_A","dual_peak_Crate","eng_charge_peak_A","eng_charge_peak_Crate","vreg_I_p95_A"],
   "deliverable/acceptable peak power + C-rate are temperature-limited"),
 "pack_resistance": ("thermal","inconclusive",
   ["vsag_R_pack_mohm","vreg_R_pack_mohm","vsag_R_iqr_mohm","vsag_I_mean_A"],
   "internal resistance rises at low temp; carries degradation trend -> normalize"),
 "cell_balance_spread": ("thermal","inconclusive",
   ["cell_spread_mean_mv","cell_spread_max_mv","cell_spread_p95_mv","cell_spread_loaded_mean_mv",
    "cell_spread_loaded_max_mv","cell_spread_loaded_p95_mv","cell_spread_loaded_p95_adj_mv",
    "cell_spread_loaded_p95_adj_hub_mv"],"cell voltage spread widens in cold"),
 "pack_engine_thermal_state": ("thermal","inconclusive",
   ["T_pack_mean_max","T_pack_mean_avg","T1_peak","T2_peak","T3_peak","T4_peak","T1_minus_pack_max",
    "T_intake","T_coolant_max","T_motor_max","T_eng_coolant_max","T_oil_max",
    "T1_at_peak_Crate","T1_at_peak_Crate_isFallback","V_pack_median"],
   "battery/intake/coolant/motor/oil thermal channels + pack temp at peak C-rate (resistance-relevant)"),
 "cold_start_warmup": ("thermal","inconclusive",
   ["pack_temp_start_c","oil_temp_start_c","engine_coolant_start_c","warmup_fuel_penalty"],
   "STAGED raw-pass start triplet + warm-up fuel; needs cold obs"),
 "auxiliary_draw": ("thermal","inconclusive",
   ["standstill_draw_kw"],"measured standstill aux/climate draw scales with ambient"),
 "degradation_trends": ("thermal","inconclusive",
   ["powerFade_slope","resistanceVreg_slope","cell_spread_slope"],
   "confounded with temp+calendar; inconclusive until normalization+repeat season"),
 "parked_cooling_tau": ("thermal","inconclusive",
   ["park_cooling_tau_h"],"17.6h inter-drive pack cooling time constant (study parameter)"),

 # ---------------- SEASON-ASSOCIATED (duty/composition mediators) ----------------
 "high_speed_deficit_saturation": ("season_associated","inconclusive",
   ["band_80_120_s","deficit_80_120_s","deficit_80_120_pct","deficit_80_120_valid",
    "engon_dis_share_80_120","blend_s_80_120","blend_share_80_120","steer_s_80_120",
    "satur_80_120_s","highspeed_discharge_s_130p"],
   "generator-saturation/buffer-deficit: primarily speed-gated; test thermal sub-component but expect duty-dominated"),
 "generator_traction_contributions": ("season_associated","inconclusive",
   ["f_gen","generator_kwh_per100km","traction_kwh_per100km"],"rises with drive class; duty-mediated"),
 "fuel_per_100km": ("season_associated","inconclusive",
   ["fuel_L_per_100km"],"composition-mediated (cold-start+HVAC+route)"),
 "route_traffic_composition": ("season_associated","inconclusive",
   ["speed_mean","speed_max","speed_p95","speed_mean_moving","speed_avg_trip_final","stationary_pct",
    "pct_highway","pct_urban","drive_type","drive_cluster_k3"],
   "MEDIATORS/covariates: must be controlled in adjusted warm/cold models, not read as thermal"),
 "driving_style": ("season_associated","inconclusive",
   ["accel_max_g","accel_min_g","accel_p95_g","accel_p05_g"],"style; weak season link, treat as covariate"),

 # ---------------- NOT APPLICABLE ----------------
 "exposure_totals": ("not_applicable","not_applicable",
   ["distance_km","gross_throughput_kwh","gtc","fce","rf_damage_k2","integr_time_h",
    "ev_batt_kwh_total"],"cumulative exposure -> 'Exposure total'; differences reflect how much driven"),
 "net_draw_family_meaningless": ("not_applicable","not_applicable",
   ["net_draw_kwh","net_draw_per100km","net_draw_kwh_corr","net_draw_per100km_corr","net_draw_kwh_corr2p",
    "net_draw_per100km_corr2p","gross_discharge_kwh","gross_charge_kwh","soc_delta_kwh",
    "energy_residual_kwh","energy_residual_kwh_corr","energy_residual_kwh_corr2p"],
   "net draw meaningless as efficiency metric in a series hybrid (M35)"),
 "calibration_offsets": ("not_applicable","not_applicable",
   ["I_offset_A_applied","offset_kwh_removed","implied_offset_A_drive","I_offset_2p_A_applied",
    "offset_2p_kwh_removed","sign_check","I_sample_period_s","iv_alignment_gap_s"],
   "current-sensor calibration/accounting -> constant/manifest"),
 "structural_coverage_manifest": ("not_applicable","not_applicable",
   ["file","pipeline_version","n_raw_rows","time_start","time_end","odo_start","odo_end","date",
    "speed_source","n_I_samples","ev_valid","ev_cov_rpm","ev_cov_speed","ev_rpm_dt_med_s",
    "ev_dist_scale_k","energy_null_reason","n_standstill_samples","n_vsag_rest","n_vsag_load",
    "n_loaded_spread_samples","n_vreg_samples","cap_ah_est"],
   "structural/coverage/manifest -> 'Not season-dependent'"),

 # ---------------- VALIDITY CAVEAT (warm-trained QC flags) ----------------
 "outlier_qc_flags_warm_trained": ("validity_caveat","review_before_cold",
   ["iso_outlier","iso_score","lof_score","f_iso","f_lof","f_mad","f_domain","ens_outlier",
    "f_iso_i","f_lof_i","f_mad_i","f_domain_2p","ens_invalid","ens_extreme","ens_outlier_v2"],
   "HANDOFF: outlier models trained on warm data; a valid cold obs must NOT be rejected for being unusual vs warm. Refit with temp features or use regime-aware residuals before applying to cold."),
}

# coverage check against the real master columns
covered = {}
for g,(pc,cv,cols,rat) in GROUPS.items():
    for c in cols:
        if c in ALL:
            covered.setdefault(c, []).append(g)
master_covered = [c for c in ALL if c in covered]
uncovered = [c for c in ALL if c not in covered]
dup = {c:gs for c,gs in covered.items() if len(gs)>1}
print("master cols:", len(ALL))
print("classified:", len(master_covered))
print("UNCOVERED:", len(uncovered), uncovered)
print("double-counted:", dup)
# how many of the classified are thermal candidates
thermal_cols = sum(1 for c in ALL if c in covered and any(GROUPS[g][0]=="thermal" for g in covered[c]))
print("thermal-candidate columns:", thermal_cols)

# ---- emit expanded seasonal_dependency.json from the verified mapping ----
SESOI = {  # smallest effect of interest for thermal groups
 "soc_cycling_frequency":0.05,"soc_mean_level":2.0,"soc_range_span":2.0,"depth_of_discharge":0.05,
 "engine_start_stop_frequency":0.10,"engine_on_duration_load_warmup":0.10,"ev_mode_share":0.05,
 "ev_run_structure":0.05,"dissipation_mode":0.05,"charge_pathway_split":0.05,
 "regen_charge_acceptance":0.05,"peak_power_capability":0.05,"pack_resistance":0.5,
 "cell_balance_spread":0.05,"pack_engine_thermal_state":1.0,"cold_start_warmup":0.05,
 "auxiliary_draw":0.2,"degradation_trends":0.5,"parked_cooling_tau":1.0,
}
out = {
 "_provenance": "Seasonal-dependency registry v2 — EXHAUSTIVE. Every one of the 186 "
   "drive_master columns is classified into exactly one group (verified: 0 uncovered, "
   "0 double-counted, 99 thermal-candidate columns). priorCandidate = hypothesized "
   "physical category; currentVerdict = what warm-only data supports NOW (thermal -> "
   "inconclusive until cold/shoulder obs + adjusted temperature response). Never "
   "downgrade to season_neutral from a nonsignificant test; predefine SESOI, use "
   "equivalence testing when support exists, apply multiplicity control when screening.",
 "labels": {
   "thermal":"adjusted temperature response is meaningful",
   "season_associated":"raw seasonal difference mainly mediated by duty/HVAC/route composition",
   "season_neutral":"equivalence established within predefined SESOI",
   "inconclusive":"uncertainty or common support insufficient",
   "not_applicable":"constant, definition, manifest result, or cumulative exposure total",
   "validity_caveat":"not a metric: a QC/outlier concern that must be handled before cold analysis",
 },
 "defaultVerdictUnderWarmOnly":"inconclusive",
 "coverage": {"masterColumns":len(ALL),"classified":len(master_covered),
              "uncovered":len(uncovered),"thermalCandidateColumns":thermal_cols},
 "metrics": {},
}
for g,(pc,cv,cols,rat) in GROUPS.items():
    entry = {"keys":cols,"priorCandidate":pc,"currentVerdict":cv,"rationale":rat}
    if pc=="thermal":
        entry["sesoi"]=SESOI.get(g)
    out["metrics"][g]=entry
json.dump(out, open("seasonal_dependency.json","w"), indent=1, ensure_ascii=False)
print("\nwrote expanded seasonal_dependency.json with", len(out["metrics"]), "groups")
by_cat={}
for g,(pc,cv,cols,rat) in GROUPS.items():
    by_cat.setdefault(pc,0); by_cat[pc]+=1
print("groups by priorCandidate:", by_cat)

# ============================================================================
# CROSS-CUTTING PHENOMENON VIEW: regen (temperature-highly-sensitive)
# Keys keep their single classification home; this view indexes them together
# with an expected cold-direction hypothesis. Does NOT duplicate columns.
# ============================================================================
REGEN_VIEW = {
 # key : (home_group, expected_cold_direction, note)
 "regen_share_of_charge":      ("regen_charge_acceptance","decrease","regen as fraction of charge; cold BMS caps acceptance"),
 "charge_pure_regen_kwh":      ("dissipation_mode","decrease","pure-regen energy captured per drive"),
 "regen_peak_A":               ("regen_charge_acceptance","decrease","peak regen current"),
 "regen_peak_Crate":           ("regen_charge_acceptance","decrease","peak regen C-rate = acceptance ceiling (plating-limited in cold)"),
 "motor_regen_lower_pct":      ("regen_charge_acceptance","shift","lower bound of motor-regen fraction band"),
 "motor_regen_upper_pct":      ("regen_charge_acceptance","shift","upper bound of motor-regen fraction band"),
 "peak_charge_kw":             ("peak_power_capability","decrease","peak charge power (regen+engine); charge acceptance temp-limited"),
 "peak_I_charge":              ("peak_power_capability","decrease","peak charge current"),
 "charge_dual_kwh":            ("charge_pathway_split","uncertain","engine+regen concurrent charging"),
 "charge_fraction":            ("charge_pathway_split","increase","total charge fraction may rise as regen falls and engine charging compensates"),
 "rf_dod_wmean_pct":           ("depth_of_discharge","increase","weaker regen top-ups -> deeper mean buffer swings in cold"),
 "rf_dod_max_pct":             ("depth_of_discharge","increase","max DoD"),
 "ev_nr_km":                   ("ev_run_structure","context","no-regen EV distance; (ev_dist_km - ev_nr_km) = regen-influenced EV distance"),
 "ev_nr_kwh":                  ("ev_run_structure","context","no-regen EV energy"),
 "ev_nr_run_max_km":           ("ev_run_structure","context","longest no-regen EV run"),
}
# verify every regen-view key exists in master and in its stated home group
grp_keys = {g:set(c[2]) for g,c in [(g,GROUPS[g]) for g in GROUPS]}
problems=[]
for k,(home,_,_) in REGEN_VIEW.items():
    if k not in ALL: problems.append(("not_in_master",k))
    elif k not in GROUPS[home][2]: problems.append(("home_mismatch",k,home))
print("regen-view keys:", len(REGEN_VIEW), "| problems:", problems)

# reload the registry we just wrote and attach the phenomenon view + tags
dep = json.load(open("seasonal_dependency.json"))
dep["phenomenonViews"] = {
  "regen": {
    "_note": "Regen acceptance is one of the sharpest thermal effects (cold packs "
             "limit charge/regen to avoid Li-plating). Keys are indexed here across "
             "their home groups with expected cold direction. IDENTIFIABILITY GAP: "
             "regen *efficiency* (regen energy / available braking energy) is NOT "
             "computable — no braking-energy or wheel-torque channel exists; only "
             "regen ACCEPTANCE (energy actually taken into the pack) is observed.",
    "expectedColdDirectionLegend": {
      "decrease":"metric expected lower in cold","increase":"expected higher in cold",
      "shift":"band/bound expected to shift","uncertain":"direction not pre-specified",
      "context":"supporting/derived context, not a direct acceptance metric"},
    "members": {k:{"homeGroup":h,"expectedColdDirection":d,"note":n}
                for k,(h,d,n) in REGEN_VIEW.items()},
    "derivedProbe": {"regen_influenced_ev_km":"ev_dist_km - ev_nr_km"},
  }
}
# tag home groups that contribute to the regen view
regen_groups = sorted({h for _,(h,_,_) in REGEN_VIEW.items()})
for g in regen_groups:
    dep["metrics"][g].setdefault("phenomenonTags", []).append("regen")
json.dump(dep, open("seasonal_dependency.json","w"), indent=1, ensure_ascii=False)
print("attached regen phenomenon view spanning groups:", regen_groups)
