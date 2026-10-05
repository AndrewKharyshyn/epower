# M377b: written definitions of the generator/traction reconstruction (for a blind re-derivation; values-free, code-free)

Purpose: the first blind audit of M377b could not derive the sensitivity BASE, the speed-binned f_gen and the simultaneity shares because the allowed definitions did not specify the reconstruction. This document states it in prose so that an independent implementation can reproduce the quantities. It contains NO published or computed result and NO code. Constants are named; their values are read from `model_constants.py` (constants only). Everything here describes the method as implemented in the repository (it is a description of the existing, unchanged producers, not a new method). Generator and traction power are MODEL-DERIVED reconstructions (never measured).

## 1. Inputs and drive set
- Raw files: `raw_only/<master key>` (CSV, header row, first column `time`, values parsed as numbers; non-numeric -> missing). Master: `drive_master.csv` (one row per drive; columns used: `file`, `distance_km`, `drive_type`, `date`, `I_offset_A_applied`, `gross_discharge_kwh`, `gross_charge_kwh`, `ens_outlier_v2`, `ens_invalid`).
- Channels (exact header text): HV current `[BMS] HV Battery Current (A)` (charge-positive); HV voltage `[BMS] HV Battery voltage (V)`; engine speed `Оберти двигуна (rpm)`; fuel rate `Витрати палива (L/h)`; coolant `Температура охолодної рідини (℃)`; engine oil `Температура олії у двигуні (℃)`; calculated boost `Розрахунковий наддув (bar)`; vehicle speed `Швидкість автомобіля (km/h)`; plus SoC, odometer-type and fuel-used columns that are loaded but do not enter any formula below.
- A drive is FUEL-INSTRUMENTED when its raw header contains a column whose name contains the fuel-rate header text (case-insensitive).
- Drives that enter the reconstruction: fuel-instrumented, `distance_km > 0` (master), and with at least 10 non-missing fuel-rate samples. Canonical-clean restriction: drop a drive when `ens_outlier_v2` or `ens_invalid` is explicitly True; a missing flag for a drive that otherwise enters the reconstruction is an error (the two fuel-PID files without a master flag and without a reconstruction row never enter). The block-level set "clean" additionally requires the drive's f_gen (section 5) to be defined (not NaN). Report the n drives, n calendar days (distinct master `date`) and km (master `distance_km`) of each set you use.

## 2. Per-drive frame
- Each channel is converted to a time series of its non-missing numeric samples, sorted by time. The FRAME ROWS are the fuel-rate samples. Every other channel is attached to each row by nearest-in-time sample within 1.5 s (missing when none).
- `dt` (s) = time difference to the previous frame row, clipped to at most 5.0 s; the first row has dt = 0.
- Current offset (A): the drive's `I_offset_A_applied` when present; when it is missing, the single corpus constant = the unique value of `I_offset_A_applied` over the master (rounded to 4 decimals; it is single-valued by construction).
- Battery power (kW, discharge-positive): `Pbatt = V * (-I_raw - offset) / 1000` (raw current is charge-positive; the offset is subtracted in the discharge-positive frame). Rows where V or I is missing: Pbatt is treated as 0 in every sum below.
- Engine ON: `rpm > 400` (missing rpm = off). A row is a FUEL row when ON and fuel rate > 0 (`on` in the formulas below means this combined condition). Fuel volume per row `vol_L = fuel_rate_L_per_h / 3600 * dt`.
- Distance used for per-100-km values is the master `distance_km` of the drive.

## 3. Regimes, cold gate and engine power
- Regime per row from rpm (constants `SEC_LO`, `OPT_LO`, `OPT_HI`, `NEAR_HI`, `BOOST_HIGH_BAR` in `model_constants.py`): rpm < SEC_LO -> LOW; SEC_LO <= rpm < OPT_LO -> SEC; OPT_LO <= rpm <= OPT_HI -> OPT; OPT_HI < rpm <= NEAR_HI -> NEAR; rpm > NEAR_HI -> HIGH; then any row with calculated boost > BOOST_HIGH_BAR (missing boost = 0) is HIGH. Rows that are not `on` have no regime (they carry no fuel energy).
- Cold gate per row: when the oil temperature is present the row is cold iff oil < `COLD_OIL_T_C`; when it is missing the row is cold iff coolant < `COLD_T_C` (missing coolant is taken as 90 deg C). Time since engine start is not used.
- Brake specific fuel consumption per regime r (g/kWh): `b_r = max(BSFC[r][central] * s, BSFC_FLOOR)` where s is the scenario scalar from `SCEN` (central = 1.00); cold rows use `max(b_r * COLD_MULT[central], BSFC_FLOOR)`.
- Engine power per fuel row (kW) = (fuel_rate_L_per_h * RHO_G_PER_L[central] / 3600) / b(row) * 3600, i.e. (g/s) / (g/kWh) * 3600. Generator-bus power `Pgen = Peng * ETA_GEN[central] * ETA_PE[central]`. Rows that are not fuel rows have Pgen = 0.
- Engine brake energy `E_eng` = sum over regimes and cold/warm of (fuel volume of those rows * RHO / b), in kWh (g divided by g/kWh). `E_gen = E_eng * ETA_GEN * ETA_PE`. `E_fuel = (sum of vol_L over fuel rows) * RHO * LHV_MJ_PER_KG[central] / 3.6 / 1000` (kWh). `eta_fuel_bus = E_gen / E_fuel`.

## 4. Battery anchoring and traction power
- `dis = max(Pbatt, 0)`, `chg = max(-Pbatt, 0)`; `E_dis_raw = sum(dis*dt)/3600`, `E_chg_raw = sum(chg*dt)/3600` (kWh, over ALL frame rows).
- Scale factors: `kd = gross_discharge_kwh / E_dis_raw` when E_dis_raw > 1e-6 and the master value is present and > 0, else 1; `kc = gross_charge_kwh / E_chg_raw` by the same rule with `gross_charge_kwh`. Anchored battery power `Pbatt_anch = dis*kd - chg*kc` (kW, +discharge).
- Traction bus power `Ptrac = Pgen + Pbatt_anch - P_AUX_KW[central]` (kW).
- `E_trac_gross = sum(max(Ptrac,0)*dt)/3600`; `E_gen_to_trac = sum(min(Pgen, max(Ptrac,0))*dt)/3600` (kWh); per-drive `f_gen = E_gen_to_trac / E_trac_gross` (NaN when E_trac_gross is not > 0).
- Check that holds in the implementation (you may use it as a self-test): summing the per-row arrays reproduces these drive aggregates.

## 5. Corpus aggregation (sensitivity table)
- Per drive, with dist = master `distance_km`: gen100 = E_gen/dist*100, trac100 = E_trac_gross/dist*100, g2t100 = E_gen_to_trac/dist*100, plus eta_fuel_bus and f_gen. Keep drives with f_gen defined ("clean").
- Corpus values (distance-weighted): `gen100 = sum(gen100_i*dist_i)/sum(dist_i)`, `trac100` likewise, `etaBus` likewise (a drive with missing eta contributes 0 to the numerator and its distance to the denominator); `fgen = sum(g2t100_i*dist_i) / sum(trac100_i*dist_i)`. Rounding for display: gen100 and trac100 to 2 decimals, fgen and etaBus to 3 decimals.
- Axes (each changes exactly one constant or the scenario scalar, all else central): BASE (central); BSFC optimistic (scenario scalar 0.94); BSFC conservative (1.09); eta_gen low (ETA_GEN central = 0.90); eta_gen high (0.97); P_aux low (0.2 kW); P_aux high (1.2 kW); cold penalty off (COLD_MULT = 1.00); cold penalty heavy (1.45); OPT band wide (OPT_LO = 1750, OPT_HI = 2250 rpm; regimes re-classified).

## 6. Simultaneity (per drive type)
- Uses the per-row `Pgen`, `Ptrac`, `Pbatt_anch`, `dt` of section 4 on the drives with f_gen defined; drive type = master `drive_type` in {urban, mixed, mixed_highway, highway} (other types are skipped).
- Engine-on second: `Pgen > 0`. Among engine-on rows: if `Ptrac < 0.5` kW -> fullyBanked; else if `Pbatt_anch > 0.5` kW -> genPlusBattDischarge; else if `Pbatt_anch < -0.5` kW -> chargesAndDrives; else (|Pbatt_anch| <= 0.5) -> genAloneNeutral.
- Per drive type: shares = (sum of dt over the rows of each state) / (sum of dt over all engine-on rows) * 100, rounded to 1 decimal; engine-on hours = sum(dt)/3600 rounded to 1 decimal; n drives = drives of that type having at least one engine-on row. The four shares partition 100 %.

## 7. Speed-binned traction supply split
- Drives: those that enter the reconstruction (section 1) and are canonical-clean (this block does NOT additionally require f_gen to be defined).
- Vehicle speed attached by the nearest-sample rule of section 2. Per row: `g2t = min(Pgen, max(Ptrac,0))` (kW), `b2t = max(Ptrac,0) - g2t`, distance `speed_kmh/3600*dt` (km; missing speed = 0). A row belongs to a bin when speed is finite, `lo <= speed < hi` and `dt > 0`; bins (km/h): 0-20, 20-60, 60-90, 90-120, 120+ (upper edge 999).
- Per bin: `gen_kWh = sum(g2t*dt)/3600`, `batt_kWh = sum(b2t*dt)/3600`, `km` = sum of row distances (unrounded), nDrives = drives with at least one row in the bin. `generator = gen_kWh/km*100` and `battery = batt_kWh/km*100` (2 decimals), `fGen = gen_kWh/(gen_kWh+batt_kWh)` (4 decimals), `distKm` = km rounded to 1 decimal.

## 8. What to deliver
For the live corpus (524 master rows, `raw_only/`): the drive sets (section 1) with n drives / n days / km and the excluded IDs; the BASE row and one more axis of section 5 (state which); the simultaneity rows for urban and highway (section 6); the f_gen, generator, battery, km and nDrives of the 20-60 and 90-120 bins (section 7). Report where your implementation required a choice this document does not fix (for example missing-value handling), with the effect of the alternatives if you can state it. Do not look at the repository's reconstruction code, the payload or any author output.
