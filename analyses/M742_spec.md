# M742 spec: blind reproduction of the M739 U2 representativeness estimates (verification only, report-only)

Rev 1. Committed BEFORE the audit is dispatched. Author: main session (Sonnet). Verification milestone: no new estimator, no new figure, no published output changes.

## 0. Why
The M739 blind audit (`analyses/M739_audit.json`) reproduced C1 to C4 (units, recall, V1 distance error, U3 km partition). It did NOT independently verify the U2 block: the per-class signed differences, their day-clustered bootstrap intervals, the minimum detectable differences, the within-day permutation p of the total-variation summary, and the time-weighted sensitivity. Its own note: "day-bootstrap intervals not independently verified". U2 is the part of M739 that says how the unlogged driving differs from the logged driving, so it needs the same independent check.

## 1. Claims to reproduce (targets, held by the main session, NOT given to the auditor)
From `analyses/M739_unlogged_exposure.json`, block `U2_representativeness`:
- K1: km-weighted signed differences (unlogged minus logged cloud-reconstructed) for 8 classes: speed-class time shares below30 / 30to80 / above80, length terciles t1/t2/t3, weekend, night, with their day-clustered 95 % intervals.
- K2: the same for the time-weighted sensitivity.
- K3: the 80 %-power minimum detectable difference per class.
- K4: observed total-variation distance of the km-weighted mean shares and its within-day label-permutation p.
- K5: n: 641 logged cloud vectors, 328 in-support unlogged units, 166 days.

## 2. Procedure
1. The auditor (`analytical-auditor`, blind) receives only: the claim wording (what is compared), the definitions in `analyses/M739_spec.md` Rev 2 and section 9 (Rev 2.1), and the data paths (cloud store, `drive_master.csv`, raw OBD directory). It does NOT receive the tool, the tests, the result JSON or the numbers above.
2. It reproduces the unit construction independently as far as U2 needs it, then K1 to K5 with its own bootstrap (seed 42, 4000 draws, calendar day as cluster) and its own permutation (within-day labels).
3. The main session compares after the audit returns.

## 3. Acceptance rule (fixed now)
- Point estimates (K1, K2): reproduced when each agrees within 0.005 absolute (shares) or 0.01 (tercile mix); a larger gap is a finding, reported with the cause if the auditor finds one.
- Intervals (K1, K2): reproduced when both bounds agree within 0.03 absolute (bootstrap Monte Carlo error plus resample-implementation differences; a different RNG stream cannot give identical draws). A class whose interval sign (excludes zero or not) differs between auditor and tool is a finding regardless of size.
- K3: within 20 % relative. K4: observed TV within 0.005; permutation p within 0.02 absolute and on the same side of 0.05. K5: exact.
- Outcome wording: "reproduced", "reproduced with disclosed differences" or "not reproduced"; no threshold is changed after seeing the auditor numbers. A "not reproduced" class is withdrawn from the M739 reading (not edited silently) and the Director decides.

## 4. Falsification
The claim "U2 differences are reproducible" is falsified per class when the point estimate or the sign of the interval cannot be matched under the rule above. Absence of a match is reported with the auditor's own value.

## 5. Constraints
Report-only. `drive_master.csv` MD5 `d514d6009d6d9a0a168ad4fb09b9bb98` asserted before and after. No payload, dashboard or winter file change (M726). Outputs: `analyses/M742_u2_blind_comparison.json` (aggregates only; public repository). Language: "estimated / reconstructed", differences descriptive, not an effect, not a correction of any KPI.
