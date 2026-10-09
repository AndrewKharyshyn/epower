# M392 spec (pre-registered before the code): one consistent, calibrated drift rule for the recalibration gate

Follows the M388 follow-ups (Director: "one consistent hard-flag rule", "replace the block-null test"). Scope: `tools/recal_gate.py` flags only. No estimator, master or payload value changes.
Evidence (script output, analyses/M392_calibration.py and M392_calibration_spread.py, real history replayed batch by batch against the corpus preceding it, seed 42, 4000 draws):

## Findings on the current rules
| rule | what it tests | fires on historical batches |
|---|---|---|
| H1 pooled (old+batch) estimate outside the old 95% CI | all quantities | 0% at every batch length (a batch much smaller than the corpus cannot move the pooled value): never fires |
| H2 batch-only estimate outside the old 95% CI | offsets only | 50-71% (k = 2..10 days): a k-day estimate compared with a CI built for a ~100-day pooled mean; a false-alarm generator (it fired at M376 and M388 on ordinary batches) |
| block-null with the min-drives condition = batch drives | spread | computable on only 43-64% of historical batches (windows must contain at least as many drives as the batch); `p is None` was counted as a HARD flag |
| C1 window null (rank of the batch deviation among ALL contiguous k-day windows of the old corpus) | offsets | 0-5% for k = 2..7, 12.5% at k = 10 (1 of 8 batches); calibrated |
| C2 two-sample day-clustered percentile bootstrap, CI of (batch - old) excludes 0 | offsets | 34% (k=2), 20% (k=4), 9-12% (k>=7): few clusters under-cover; rejected as a hard rule |
Power: the minimum detectable shift (95th percentile of window deviations) of an offset test is about 0.39 A (k=2), 0.24 A (k=4), 0.14 A (k=7), 0.11 A (k=10) against an offset of about 0.38 A. A 4-day batch cannot see a shift below about 60% of the offset. A passing test is therefore never "no shift".

## Rule (fixed, not tuned)
For every tested quantity (offset pass 1, offset pass 2, spread OLS, spread Huber) with k = number of observed days of the new batch in that quantity's eligible set:
1. HARD (stops for audit + Director unless acknowledged), any of:
   a. pooled (old+batch) estimate outside the old 95% CI (unchanged; weak but free);
   b. window-null drift test: p <= 0.01, with p = (1 + #{windows with |deviation| >= observed}) / (n_windows + 1) over ALL contiguous k-day windows of the old corpus, and only if n_windows >= 99 (else capped to soft, as for the existing joint test).
   Offsets: deviation = window ratio-of-sums minus the old pooled estimate. Spread: the existing joint Mahalanobis statistic over the identifiable coefficients (unchanged), with window validity = at least 8 drives with complete spread data (the gate's own "new-only n >= 8"), NOT "at least the batch's drive count".
2. SOFT (reported, acknowledged in the CHANGELOG, no stop): window-null p < 0.05; pooled shift > 0.25 of the old CI half-width (unchanged); a test that cannot be evaluated (fewer than 10 valid windows or batch under 8 drives): `not_evaluable`, never hard.
3. Always reported per quantity: `mdd95` (minimum detectable shift for a batch of this length) and the sentence "a pass means no shift above mdd95 was detected; smaller shifts are not excluded".
4. The old batch-only-outside-CI comparison is kept as the informational field `new_only_outside_old_ci` (not a flag).
Wording: "drift test not established / not evaluable", never "stable" or "no drift"; corrected energies stay estimated / offset-corrected.

## Gates
Known-answer tests (tests/synthetic/test_recal_gate.py): window-null rank with a known null; a batch beyond all windows gives p = 1/(n+1) and is hard only with >= 99 windows; not-evaluable is soft; the old H2 key is informational.
Back-test: the new rules on the real M376 and M388 ingestions (old = master before, new = the batch) and on the retro-replay: report which flags the new rule raises (script output). A blind audit reproduces the window-null p-values independently.
Apply: release_check green; the gate output stays a superset (existing keys kept; new keys window_null, mdd95, not_evaluable).

## Director ruling (M392: accept) and conditions implemented
The hard rule stays as pre-registered (p <= 0.01 with >= 99 windows, plus pooled-outside-CI); no n_windows/k condition (it would leave hard almost dead at k >= 5). Each quantity reports `n_eff = n_windows / k` and `nominal_vs_effective`
(nominal 1%, effective about 1/(n_eff+1)). Disclosed soft caps: fewer than 99 windows; batch with fewer than 8 spread drives. `not_evaluable` records its reason and `carry_forward = true`
(the flag only records it; pooling a carried batch into the next test is a follow-up). Reviewer action on a soft / not_evaluable flag: the CHANGELOG ack names the quantity, k, drives, p or reason and mdd95 and states
"drift test not established for this batch". Wording: never "stable" or "no drift". The M376 / M388 acknowledgements (raised by the superseded batch-only rule) stand unedited; under M392 they replay as no hard flag.
Follow-ups: simulated-shift power study; trailing-window / detrended null variant reported beside the rule; carry-forward pooling; null weighted by batch denominator and calendar gaps; re-check the realised false-alarm rate once more than 30 replay batches exist.
Blind audit (pass): reproduced the gate's M388 p, window count and mdd95 exactly; independent replay: batch-only-outside-CI 60-74% (k = 4, 7), pooled 0%, window-null p <= 0.05 on 5-10%.
