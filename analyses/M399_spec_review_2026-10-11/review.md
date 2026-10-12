# M399 spec review: design validity only (analytical-auditor, 2026-10-11)

Verdict: **revise**. The brief is in `review_brief.json`. Scope: design only. No estimation was rerun and no pipeline file was changed. Facts were checked read-only against `drive_master.csv`, `compute_drive_summary_v6.py`, `fuel_recon.py`, `recon_engine.py` and `summary_arrays.json`.

## Rationale (blocking)
1. **The eligibility rule is circular.** `f_domain` and `f_domain_2p` (and through `ens_invalid`, `ens_outlier_v2`) flag drives with |`energy_residual_kwh_corr`| > `RESIDUAL_MAX_KWH` = 0.35 kWh. That threshold is commented "1/6 pack", i.e. 2.1/6. The residual is built from dSoC x CAP_KWH and the global offset. So the canonical-clean population is defined on the legacy basis. Freeze/restore means the "0/16 ML diffs" gate passes by construction. The spec should pre-register a flip count: recompute the domain rules under the new basis and report the result without applying it.
2. **CV leakage and a confounded comparison.** The scale (4.89 Ah, 1.80 kWh) and the method range were fitted on all days. They are then used inside the day-blocked tests (b), (b2) and (c). Test (b) also compares "I2R at 1.80" against "global offset at 2.1", which mixes the scale and the offset model in one comparison. A 2x2 design ({offset, I2R} x {2.1, estimated scale}) with the scale fitted inside each training fold is needed.
3. **The constant does not match the primary estimator.** B gives 4.89 Ah x 358.9 V = 1.755 kWh. The 1.80 figure comes from M3e and the energy fits (1.788 to 1.797). The spec also does not say which voltage converts Ah to kWh: the 358.9 V median, or the effective E/Q of about 366 V. E_PER_SOC100_EST should come from the energy estimator and be written by a script.
4. **Gate (e) is undefined.** `I_offset_A_applied` feeds `recon_engine.py`, so it reaches the GTR headline and the M398 automatic re-pin. `fuel_recon.py` hard-codes `_CS_CAP_KWH = 2.1` for the charge-sustaining band. "Non-capacity key" therefore needs a transitive dependency trace, not a grep. Also, compare two fresh builds (HEAD code vs M399 code), not a fresh build against the HEAD file.

## Major
- **(a) cannot fail as written.** It runs the same estimator on the same data, and ±3 % is wider than the bootstrap CI. Its 4.89 Ah target also came from a set that includes the NaN-flag drives (552 eligible). The canonical-clean set is 540 drives over 108 days, and `ens_outlier_v2` is NaN for 12 drives.
- **The "4.58-5.43 forward/reverse bracket" is mislabelled.** It runs from A forward to B reverse, and the reverse fit is known to be biased high. A union of intervals simply equals the method range, so the bootstrap CI adds nothing. Adding the ±2 s timing range (1.70-1.89) makes the union grow further. Report the CI and the method range separately, computed from leaves, not typed.
- **(b) has weak and conflicting criteria.** "Offset CI contains 0" is absence of evidence: use TOST with a margin. The outcome is also already known: 0.02 A [-0.02, 0.07]. The 25 % limit on temperature strata conflicts with the physical temperature dependence of R. "Differs" and the strata are not defined. Offset (proportional to duration) and integral I^2 dt are collinear. No MDE is given.
- **(c) is predetermined.** Disjoint tercile CIs make a held-out gain above zero near-certain. A positive gain still cannot separate a nonlinear SoC scale from confounding. The tercile and linear forms are two tests, and no gain threshold is set.
- **(b2) and (g) cannot really fail, and both rely on typed numbers.** (b2) compares against legacy 2.1, which loses by construction. The external values (22/38 Wh, 1.70-1.89) are typed in. The chronological split also follows the season.

## Facts checked and found wrong
- **"The BMS does not allow SoC 85 %"** is contradicted by the corpus. Three clean drives reached a `soc_max` of 88.0, 85.5 and 85.0 (2026-07-19, 07-21, 07-25), and `soc_min` goes down to 42.5. The statement may have meant the dash gauge: display 85 % corresponds to about BMS 78 %.
- **The p0.1-p99.9 range (45-81.5 %) is attributed to 554 drives**, but it was computed on 540.
- **The engine trigger and stop bands are IQRs from driving and overlap** (trigger 54-66 %, stop 62-68 %). Nothing establishes stationary behaviour.
- **The protocol's stationary decline rate is too slow by about 3-15x.** 0.5 SoC point is about 0.0245 Ah, or 88 A·s. At 3-5 kW (8-14 A) that is 6-11 s per step, not 30-90 s. Legs of 5-12 points last minutes, not tens of minutes.

## Protocol
- **Most of Part A falls in the known slow-leg artefact regime.** Stationary 2-6 kW loads are mostly below 15 A, where the study found a selection artefact of 4.1-4.3 Ah. Define legs by engine on/off, never by SoC excursion.
- **The (g) band of 4.3-5.7 Ah per leg will raise false triggers.**
- **Two sessions cannot be bootstrapped by day.**
- **The steady-load assumption is weak.** Compressor duty cycles once the cabin has cooled. 12 V loads go through the DC-DC converter and are small.
- **Use the Director's 3 PIDs, not 8, for Part A.** Timing skew between current and SoC moves the scale by about 10 %.
- **Pre-READY readings are unverified.** With contactors open, the HV-voltage PID and the BMS may not answer in ACC.
- **Some hypotheses cannot be tested at all.** Current-sensor gain is unidentifiable. A gross 2.1 kWh with a buffer of 15 % or less cannot be tested from BMS-scale data. "Not supported by the data" must be scoped to the BMS-SoC scale.
- **Missing analysis.** The key-on SoC reset should be checked against the net Ah since the previous anchor. That is the only chemistry-tied check of the scale.
