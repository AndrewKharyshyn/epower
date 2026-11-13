# M638 pre-registered spec (Rev 0): sample-resolved pack-temperature occupancy beside the drive-average hot-tail share (self-audit W1-08 part 2, owner decision D-03)

Status: Rev 0, written BEFORE any M638 result exists (2026-11-13; master 665 drives, MD5 77bbe275f8c22eaf62d8636867764af3). Gate NA: spec, blind audit (`analytical-auditor`), Director (`research-director`) before any payload, dashboard or tooling change. M637 (merged) only labelled the existing drive-average estimand.
Wording: pack temperatures are logged BMS sensor readings (Car Scanner ELM OBD2 logger), occupancy is "logged-time share", never "measured exposure"; no CI is a coverage claim beyond the day-clustered bootstrap stated here.

## 0. Rev 1 (Director review 2026-11-13, research-director; supersedes any conflicting clause below)
Verdict: revise. Answers: (a) E2 accepted with the 3-of-4 / 45 s / 2 s rule fixed, written as a ratio of pooled sums; (b) the hottest-probe variant stays a declared sensitivity, not a second headline (probe readings are quantized, so the >= 40 C tail is sensitive); (c) the per-regime split is deferred, only n drives and days per regime go in the block; (d) wording: "share of logged drive time with mean pack-probe reading >= t C (sample-resolved)" and "share of drive time in drives whose drive-average pack temperature >= t C (drive-average)"; forbidden: "the hot-tail share", "measured exposure", "true", "corrected", "E2 supersedes E1".
Required changes (all adopted):
- R1 Two-mode known-answer. (i) audit-emulation mode: ALL master rows at MD5 77bbe275f8c22eaf62d8636867764af3 (the self-audit scan summed all 665 rows, not the 651 canonical-clean) must reproduce 0.3897 / 0.1045 / 237.5 h within 0.2 percentage points and 1 h; (ii) the canonical-clean production value is reported with its delta from (i), attributed to eligibility and to the loader (the audit scan used its own CSV reader, production uses `drive_raw_cache`). The KA is pinned to that MD5 and runs before the next ingestion.
- R2 Bootstrap: resample calendar days, recompute the ratio of sums; give n drives, n days, n clusters.
- R3 Coverage: `coverageShare` (supported hours / drive hours), `nExcludedDrives` with reason (fewer than 3 probe channels), the exact probe header list used.
- R4 E1 has no CI today: either add a sibling leaf `driveTimeShareGeCci95` (leaving `driveTimeShareGeC` byte-unchanged) or state that E1 has no interval. Decision: state it (E1 stays as published; the block says "no interval for the drive-average share"), so the existing payload is untouched.
- R5 The key `packThermalMeasured` is kept (never renamed); the meaning text says "logged BMS sensor readings, not measured exposure"; language-gate rule for the forbidden wordings in (d).
- R6 Report the >= convention (a reading equal to t counts) and the probe resolution (quantisation step).
- R7 Extra unit tests: a hold that expires mid-gap (a gap longer than 45 s is unsupported), and a case with exactly 2 of 4 probes present (unsupported).

## 1. Question and estimands
Owner decision D-03: show BOTH hot-tail estimands, each labelled.
- E1 (exists, M85/M637): `driveTimeShareGeC[t]` = duration-weighted share of drive time spent in drives whose drive-average pack temperature (`T_pack_mean_avg`) is at or above t, t in {30, 35, 40}.
- E2 (new): sample-resolved logged-time occupancy `sampleOccupancy[t]` = (seconds with pack temperature at or above t) / (seconds with a supported pack temperature), pooled over all canonical-clean drives, t in {30, 35, 40}. Supported second = a 2 s midpoint-grid time at which at least 3 of the 4 pack probe channels (T1..T4, header-selected) have a reading no older than 45 s (sample-and-hold); pack temperature at that time = mean of the available probes.
Why both: they answer different questions (how many drives ran hot on average versus how much logged time was spent hot); the external audit reported 10.45 % at 40 C (E2) against the published 6.6 % (E1) and both are right for their estimand.

## 2. Method (pre-registered)
- Eligibility: canonical-clean drives (`ens_outlier_v2` false), drives with at least 3 pack probes; reads raw via the repository loader (`drive_raw_cache`), never edits raw.
- Grid: 2 s midpoints `np.arange(t0 + 1, t_end, 2.0)`, hold age 45 s, supported if at least 3 of 4 probes finite. Rule fixed now; no variation after seeing results except the stated sensitivities.
- Estimates per threshold: pooled share (point), day-clustered percentile bootstrap (calendar day = cluster, seed 42, 4000 draws) 95 % CI, n drives, n days, supported hours.
- Sensitivities (declared, reported beside, not tuned): hold age 30 s and 60 s; grid 1 s; requiring all 4 probes; the maximum rather than the mean of probes (hottest-probe occupancy).
- Output keys (additive, written by a script, one new block, no existing leaf touched): `seasonalLife.hotTail.packThermalMeasured.sampleOccupancy` with `{thresholdsC, share, ci95, nDrives, nDays, supportedHours, rule, sensitivities, meaning}`; the meaning text names the estimand and states it is not E1.
- Dashboard: one sentence beside the E1 sentence in the seasonal-life text, bound to the new keys; both labelled; language rule that forbids presenting either as "the" hot-tail share.

## 3. Known-answer and acceptance
- The self-audit values (38.97 % at >= 35 C, 10.45 % at >= 40 C on 237.5 h; G scan `analyses/self_audit_2026-11-11/G/g2_agg.json`) are known-answer targets, never typed into the repo: the script must reproduce them within 0.2 percentage points and 1 h before the block is written; a larger gap blocks the milestone and is reported, not tuned.
- Unit test: a synthetic drive with known temperature steps gives the exact occupancy, the 45 s hold, the 3-of-4 rule, and the day-clustered CI is deterministic with the seed.
- Isolation: the payload deep-diff shows only the new `sampleOccupancy` leaves (and any stamp the stage legitimately refreshes); `driveTimeShareGeC` unchanged.

## 4. Ingestion
Recomputed on every ingestion (new stage or part of the arrays build), keyed to raw-file SHA-256 through the drive cache; cost to be measured and recorded; the stage is added to `tools/ingest_stages.json` with `verified:false` until its first full run.

## 5. Decisions requested
Director: (a) is E2 with the 3-of-4 / 45 s / 2 s rule acceptable as the sample-resolved estimand; (b) is the hottest-probe sensitivity needed or noise; (c) is a per-regime (Warm/Shoulder/Cold) split of E2 required now or deferred; (d) wording ladder for the dashboard sentence.
