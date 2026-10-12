> **STATUS (2026-10-12, owner decision, Andrii): DEFERRED.** The Ready-mode experiment will be conducted later, not now. Nothing in the repository, the pipeline, the dashboard or any milestone waits for it or requires it; the analyses that were to be informed by it (test (c) level dependence with fast legs, test (h) key-on reset and rest-voltage table, the near-zero-load offset check) are reported from the existing corpus and labelled as such.
> This file is the saved procedure protocol (v3). Its detailed description and test definitions are in `analyses/M399_spec.md` (the file names keep the historical number M399; the capacity work was implemented as M403/M404, see `analyses/M403_spec.md`). When the experiment is run: follow sections 0-8 as written, keep the files outside `raw/` (section 7), and treat the results as descriptive (section 6); nothing here changes any published number by itself.

# M399 experiment protocol v3: separating offset from resistive loss, SoC-level scan and rest-voltage table (X-Trail T33 e-POWER, Car Scanner ELM OBD2)

v3 = v2 revised after the auditor's re-review (`re_review.md`); v2 after the first review. Companion of `analyses/M399_spec.md` (v3), tests (h) and (i).

## 1. What this experiment can and cannot do
Can:
- **Part A (stationary, low current):** look at the duration-proportional term only. At 8-15 A the resistive loss is ~8-28 W against a 3-5 kW load, below the per-leg SoC noise, so Part A CANNOT identify R; resistive loss is identified from the corpus (currents > 100 A) in spec test (b). Only the near-zero-load legs (L0, L1) are informative about an offset, and a sensor offset shared by the BMS cancels in SoC-versus-integrated-current just like a gain error. Part A is descriptive and does not feed test (b).
- **Part B (driving, high current):** collect fast, clean legs (|I| >= 30 A) over the SoC range the car actually visits, to check level dependence (spec test (c)) with fast logging.
- **Part C (rest):** a resting-voltage-versus-SoC table and key-on reset statistics (spec test (h)).

Cannot (state these in any write-up):
- Identify the absolute current-sensor gain (BMS and logger read the same sensor).
- Test a gross 2.1 kWh with a hidden buffer of up to ~15 %.
- Say anything about state of health or fade.
- Reach SoC the car does not visit. Facts from the corpus: raw SoC extremes 42.5-88.0 %; p0.1-p99.9 = 45-81.5 % (540 drives); three drives reached 85.0, 85.5 and 88.0 % (regen/descents). You said you cannot deliberately raise SoC to 85 %: plausible for stationary operation (stationary stop level unverified), but descents can carry it there incidentally; the dash gauge reads 85 % at BMS SoC ~78 %. The "per 100 points" value stays an extrapolation.
- Assume that the engine start/stop levels while parked equal the driving values: the 54-66 % start and 62-68 % stop bands in the corpus are driving IQRs and overlap; the stationary stop level is UNVERIFIED and is one of the things this protocol observes.

Rates (corrected): 0.5 SoC point is about 0.0245 Ah = ~88 A.s. At a 3-5 kW load (~8-14 A) one step takes ~6-11 s; a 5-12 point leg lasts a few minutes, not tens of minutes. Currents below ~15 A are the regime where a selection artefact (4.1-4.3 Ah) appeared in the study, so Part A legs are NOT capacity pins; they are for the offset/I2R separation.

## 0. Safety and rules
- Stationary engine-on legs OUTDOORS in an open, ventilated place (never in a garage or enclosed space: carbon monoxide). P, parking brake, wheels chocked on a slope, someone present. No children or pets inside with climate on.
- Do not operate the phone/adapter while driving; a passenger starts/stops the log in Part B.
- Stop if any warning light appears. Do not modify `raw/`; save logs outside it (section 7).

## 1. Profiles and PIDs (names as in your CSV columns)
Fewer PIDs = faster polling; timing skew between current and SoC matters (an external review reported ~10 % for +/-2 s; unaudited here: measure the skew in the dry run from the paired timestamps). Each profile is a COPY of your normal profile with all other PIDs disabled; keep the normal profile untouched. Estimated interval with 5-6 PIDs: 0.2-0.5 s per channel (current ~1.28 s with ~35 PIDs); verify in the dry run.

| Profile | PIDs | Used in |
|---|---|---|
| **CAP-A** (5) | `[BMS] HV Battery Current (A)`; `[BMS] HV Battery voltage (V)`; `[BMS] HV State of charge (%)`; `Оберти двигуна (rpm)` (engine RPM, needed to class legs by engine state); `[BMS] HV Battery Temperature Sensor 1 (℃)` (the analysis adjusts for temperature) | Part A |
| **CAP-B** (6) | CAP-A + `[VCM] Vehicle Speed (km/h)` | Part B |
| **CAP-C** (6) | `[BMS] HV Battery Current (A)`; `[BMS] HV Battery voltage (V)`; `[BMS] HV State of charge (%)`; `[BMS] Max Cell Voltage (V)`; `[BMS] Min Cell Voltage (V)`; `[BMS] HV Battery Temperature Sensor 1 (℃)` | Part C (static, so more PIDs are affordable) |

Optional extra in the very first session only: `[BMS] HV Battery Current (High) (A)`, to settle the relation between the two current columns. Remove afterwards.
Do NOT enable: `[BMS] HV Battery Current (Low) (A)` (-1600 fill), `[VCM] Motor Torque`, `[VCM] Target Motor Torque`, `[VCM] Motor RPM` (mis-decoded/rejected), engine load, boost, MAP/MAF, oil/coolant temperatures, accelerometer. The `[VCM] HV Battery Available Charge Display (%)` (dash gauge) is optional in CAP-C only if the interval stays acceptable. Keep your usual CSV format (`time` HH:MM:SS.mmm; date in the file name).

## 2. Preparation
1. Build the three profiles; phone on charger, battery saver off, app auto-sleep off, location on, free storage > 500 MB.
2. **Dry run (10 min each profile), outdoors:** check the columns, the median interval of the current channel (target < 0.5 s; if > 0.8 s remove optional PIDs), millisecond `time`, plausible current (small, not -1600). **Also test accessory mode:** ignition ON without the brake for 60 s with CAP-C. The HV voltage and BMS PIDs may not answer with the contactors open (unverified); if they do not, drop the ACC step and read the resting values in the first minute after READY instead (spec test (h) then uses that).
3. Notebook for EVERY run: date, start/end clock, ambient temperature, odometer, dash SoC at start/end, HVAC/lights settings and every change, engine start/stop times (as noticed), weather, passengers/load.
4. Ambient 15-25 °C for the first campaign; repeat in another season later.

## 3. Part A: stationary legs for the offset vs I2R question (profile CAP-A)
Rationale (limited): with the engine off the pack current is any duration-proportional offset plus the load current. L0 (no load) and L1 show whether a residual current persists; L2/L3 document the loads. They do not identify resistance (see section 1), and a sensor offset shared by the BMS cancels in the SoC-versus-integral relation.
1. Outdoors, level ground, P, brake, doors closed, driver present, engine warm. Start CAP-A with the key OFF, then READY (brake + start). Wait 60 s with no load (note whether the engine starts for warm-up; let it finish).
2. **Load levels (one level per leg; do not change settings within a leg):** L0 no loads; L1 fan on a low fixed step; L2 fan mid + A/C on; L3 A/C + fan high + headlights + rear defroster. The A/C compressor cycles once the cabin is cool, so the current will not be constant: write the settings and rely on the logged current, not on the nominal load. 12 V loads go through the DC-DC converter and are small.
3. Run each level until the engine starts by itself (engine RPM channel). That is one "discharge leg" (engine off). Then let the engine run until it stops itself ("charge leg", engine on) and note the clock times. A leg is a few minutes; a full level takes about 10-20 minutes including the charge leg.
4. Repeat L0-L3 in randomised order on at least 4 different days (so that sessions are different clusters). Per day: all four levels once, at least twice for L1 and L3 if time allows.
5. End of session: 60 s READY at minimum load, key OFF, wait 30 s, stop the log.
Outputs used by the analysis: engine-off discharge legs classed by engine state (never selected by SoC excursion), mean current and its SD per leg, duration, SoC steps, temperature. Four days are fewer than the 8-day threshold in section 6, so the result is descriptive.

## 4. Part B: driving legs over the SoC range (profile CAP-B)
A passenger runs the phone; drive normally and safely; do not drive unusually for the test.
- **Upper SoC:** a long descent of 5-10 km with moderate speed (regen, engine off). Start the log at the top, stop at the bottom. Note SoC at start/end (dash and log).
- **Lower SoC:** a sustained climb or constant high-speed cruise where legal and safe (e.g. 10-20 min), until SoC falls below ~55 %. Once or twice.
- **Ordinary drives:** 6-10 drives with CAP-B, at least 2 hilly and 2 highway. Decide beforehand which days you sacrifice from the normal corpus profile; do not mix profiles within a drive.
- For each drive: route type, ambient temperature, odometer, start/end dash SoC.
Analysis (planned): engine-state-defined legs with |I| >= 30 A; apparent Ah/100 vs segment-centre SoC (spec test (c)).

## 5. Part C: resting voltage (profile CAP-C)
1. End a part A or B session at a chosen SoC (examples: end of a discharge leg; end of a charge leg; end of a long descent; end of a hard drive). Note the dash SoC and the BMS SoC at switch-off.
2. Key OFF, doors closed, no charging, no accessories, no key-on. Rest >= 2 h (6-12 h overnight after a hard drive), note ambient temperature.
3. Start CAP-C: if the ACC test (section 2) succeeded, record 2 min in ACC without READY, then 2 min in READY; otherwise record 2 min in READY. Stop the log. The first values are the resting cell voltages; the SoC step between switch-off and key-on is the reset (spec test (h)).
4. Aim at 4-6 SoC levels, 2 repeats where possible (8-12 sessions over 1-2 weeks, using normal parking).

## 6. What goes into which spec test
- Part A -> descriptive check of a residual current at near-zero load; NOT an input to test (b) (R and offset are identified from the corpus).
- Part B -> test (c): level dependence with fast legs, under the engine-state definition.
- Part C -> test (h): key-on reset and OCV table.
- None of it identifies sensor gain, a hidden buffer, or health.
Analysis plan (pre-registered with the spec): clustering by DAY where there are enough days (Part C, natural drives); with fewer than ~8 distinct days (Part A, Part B special drives) the result is DESCRIPTIVE, cluster = session, no inferential claim; no pass/fail band on a single leg.

## 7. Data handling
1. Copy each CSV to `<Investigation>/experiments_capacity_2026/` (outside the repo and outside `raw/`). Name: `YYYY-MM-DD_HH-MM-SS_<A|B|C>_<load-or-note>.csv`.
2. sha256 of every file in `SHA256.txt` plus an off-chat backup (same rule as ingestions).
3. Keep the notes (photo or text) with the same prefix. Mark anything that went wrong (app crash, adapter drop, a changed load); do not delete the file.
4. Never place these files in `raw/` and never run the routine ingestion on them (different PID set, mostly empty channels).

## 8. Checklist
- [ ] Profiles CAP-A (5), CAP-B (6), CAP-C (6); dry runs; current interval < 0.5 s
- [ ] ACC-mode test done (or dropped)
- [ ] Part A: L0-L3 on >= 4 different days, randomised order
- [ ] Part B: 1-2 descents, 1-2 sustained-load drives, 6-10 ordinary drives
- [ ] Part C: 8-12 rest sessions at 4-6 SoC levels
- [ ] Notes sheet, files outside `raw/`, sha256, backup

Unverified assumptions (check first, stop and note if they fail): the achievable polling interval; Car Scanner menu names and fast-polling options; whether PIDs answer in ACC mode; the engine's stationary start/stop SoC; whether the engine runs for cabin heat in your climate; availability of any SoC-hold mode in your market (use only if documented, and note it).
