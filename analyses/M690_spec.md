# M690 spec (Rev 1): N-11 part, torque-register decoder validation (descriptive, payload only)

Status: pre-registered before any result of this analysis exists. Backlog item N-11 (decoder part). Background: `compute_drive_summary_v6.py` COL_MAP comments (M102): `[VCM] Motor Torque (N.m)` (the "actual" register) is logged at about 1/256 of the scale of `[VCM] Target Motor Torque (N.m)`; the `[VCM] Motor RPM` PID is rejected (a linear image of the torque register, not motor speed). The external audit (G) reported, on 645 drives, a median target/actual ratio of 259.8, 72 to 74 % of samples within 3 N.m of the x256 relation, and negative "motor rpm" in 25.4 % of samples above 20 km/h. Those figures are known-answer targets for the tool, never typed into the repo. The 1,214-row ledger and the M102 evidence are not re-opened; this milestone only checks, per drive and corpus, whether the actual register times 256 reproduces the target register and what the residual looks like.

## 1. Question and non-claims
Is `actual_register x 256` a usable reconstruction of the target torque (scale, tolerance share, sign, timing), and is the negative-"motor rpm" artefact the sign of the torque register (regeneration), not a speed? Non-claims: neither register is a measured shaft torque; both are logged / app-calculated PID values; no traction-energy, power or efficiency quantity is derived here; no change to any existing figure; no road-load coefficient is used or implied (road data do not exist and are not needed). A positive result licenses only the statement "the logged actual-torque register, multiplied by 256, tracks the logged target-torque register with the stated residual", never "measured torque".

## 2. Data and eligibility
Master `drive_master.csv` canonical-clean drives (`ens_outlier_v2` False), FWD corpus. Per drive from the raw CSV (read-only, cached by sha256 in `torque_decoder_cache/`): samples where both the actual and the target register and the vehicle speed are numeric. A drive is eligible when it has at least 200 such samples with |target| >= 20 N.m (the "active" samples). Drives without the actual register are counted and listed as missing, never imputed. Cadence stratum (fast / slow polling, `cadence_regime.csv`, fixed coding fast=1, slow=0) is carried for every estimate.

## 3. Quantities (per drive, then corpus)
D1 Scale: per drive, the median of target / actual over active samples with |actual| > 0 (ratio scale), and the through-origin L1 slope of target on actual (robust scale); corpus: median of the per-drive values with a day-clustered percentile bootstrap interval (calendar day cluster, seed 42, 4000 draws; every drive carries n samples, drives and days).
D2 Tolerance share: per drive, the share of active samples with |target - 256 x actual| <= 3 N.m (the external statistic), and also <= 10 N.m and <= 1 % of the active range; corpus median and day-clustered interval.
D3 Sign: per drive, the share of active samples whose target and 256 x actual have opposite signs; corpus median.
D4 Timing: per drive the sample lag in {-3..+3} that maximises the tolerance share (lag in samples, cadence stratum reported); the share of drives for which the best lag is not 0; tolerance share at lag 0 and at the best lag.
D5 Register grid: per drive the minimum positive step of the actual register (descriptive; the resolution of 256 x actual is that step times 256).
D6 Rpm artefact: per drive, among samples above 20 km/h, the share with negative `[VCM] Motor RPM` and the share with negative target torque, and the sample-level agreement of the two signs; corpus medians. Statement allowed only as agreement of signs, never as a speed.
D7 Residual by speed band and by |target| band (descriptive medians of the signed residual 256 x actual - target), to show whether the relation is band-dependent.

## 4. Decision rule (pre-registered; no tuning)
Status "decoder consistent with x256" requires all of: the D1 ratio-scale interval and the L1-slope interval both contain 256 or lie within [250, 262]; the corpus median D2 share at 3 N.m is at least 0.60; the corpus median D3 is at most 0.05. Status "scale consistent, tolerance weak" if D1 passes and D2 is below 0.60. Status "not consistent" if D1 fails. Whichever status is obtained is reported as it is; a disagreement with the external figures (ratio 259.8, 72 to 74 %, 25.4 %) is reported as a disagreement, not tuned away. The status carries the support ladder (not shown below 10 drives or 5 days; exploratory ESS < 10; supported otherwise) and a fast-versus-slow split with no contrast drawn.

## 5. Validity and tests
V1 each cached per-drive record carries its sha256, sample counts and the extractor version; V2 determinism; V3 a known-answer test `tests/synthetic/test_m690_torque_decoder.py`: planted scale 256 with noise (ratio, tolerance share, sign, lag recovered), a planted lag of two samples, a planted scale of 128 (status "not consistent"), a drive without the actual register (listed missing), a drive with fewer than 200 active samples (excluded and counted), the rpm-sign agreement on a constructed set. Stage `torque_decoder` (verified:false), payload block `torqueDecoder` + stamp, tool `tools/torque_decoder.py`, language rule `M690-torque-decoder-wording`: forbidden "measured torque", "true torque", "validated torque" (the decoder is "consistent with"); allowed "logged actual-torque register x 256".

## 6. Outputs and next steps
Descriptive payload block only; no display here; no article figure; no change of any existing block (isolation guard). Blind audit (independent reproduction of D1 to D3 and D6 on a drive subset and the corpus medians) before the Director's decision on the result.

## 7. Risks
R1 the actual register may be signed or offset differently in regeneration (D3 and D7 show it). R2 timing: a lag between the registers lowers D2 at lag 0 (D4). R3 the actual register grid may be coarse after the x256 scaling (D5). R4 samples are not independent within a drive; the cluster for intervals is the calendar day. R5 the rpm PID may be a different quantity in a later firmware (the per-drive D6 is shown by date month).

## 8. Director review (2026-11-16, verdict revise; no change of question) and how each is applied (Rev 1.1)
These override the matching text above.
1. D1 passes only if the interval lies ENTIRELY within [250, 262]; whether it contains 256 is a separate reported field (a wide interval containing 256 must not pass).
2. D2 passes only if the lower bound of its day-clustered interval is >= 0.60; D3 gets a day-clustered interval too and passes only if its upper bound is <= 0.05. A point value that passes with a failing bound gives the status "tolerance not established".
3. A row is formed from the same timestamp of both registers: no forward-fill and no interpolation of either register. The share of rows with both registers is reported.
4. D5 is computed first; if 256 x step > 3 N.m, D2 at 3 N.m is labelled "resolution-limited" and the share expected from quantisation alone is reported.
5. D1 also reports the count and share of active samples with actual = 0 (dropping them biases the ratio).
6. "1 % of the active range" is 1 % of the per-drive (p99 - p1) of |target|.
7. Sign when actual = 0: excluded from D3 and counted.
8. The status uses lag 0 only; the best lag (D4) is descriptive, with the lag also in seconds per cadence stratum.
9. ESS uses the repo definition (`n02_seasonal_fits.ess_days`: 1 / sum of squared normalised per-day weights, weight = active samples per day). The bootstrap statistic is the median over all drives in the resampled days.
10. The question reads "agrees in sign with the target-torque register" (not "is the sign of regeneration"). D6 reads the rejected rpm PID inside the tool only: no column is created and the M102 rejection stays unchanged.
11. The thresholds were set with the external figures known; the SHA-256 of this spec is recorded in the CHANGELOG before the first run.
Missing-over-read items added: the result holds only for |target| >= 20 N.m (low-load behaviour is not shown); D7 and R5 also split by the logger PID-configuration class (`pidEpoch`) and the battery software update date (2026-08-25), not only by month; V3 adds a quantised actual grid, actual = 0 samples and a wide interval containing 256 that must fail; an isolation test shows the payload deep-diff adds only `torqueDecoder` and its stamp; the language rule also forbids "calibrated", "corrected torque" and "motor speed" (for D6); follow-up in a separate tooling change: the COL_MAP comment at `compute_drive_summary_v6.py:338` says "measured ... true N.m", which breaks the wording rule.
