# M399 v2 re-review: design validity only (analytical-auditor, 2026-10-11)

Verdict: **approve_with_changes**. The brief is in `re_review_brief.json`. The three spec items listed under "Before code" must be fixed before any code is written. Protocol Part A must be rewritten before data collection.

## Blocking items from v1
1. **Eligibility (closed).** The spec now has shadow columns and a flip count, and eligibility is not changed. Still to add: the shadow `RESIDUAL_MAX_KWH` value (E/6, or 0.35 kept) and a one-pass rule (no iteration of scale and population).
2. **2x2 in-fold design (closed).** The condition-number limit of 30 for [duration, integral of I^2 dt] depends on units. Standardise the columns first, or use a VIF.
3. **Conversion voltage (partly closed).** `V_CONV` = E/Q does not say which energy (terminal or I2R-removed) or whose Q. If both come from the energy estimator, then E_PER_SOC100_EST is simply that estimator's output and the Q_SOC_EST x V_CONV product only mixes estimators.
4. **Control build (closed in design).** Two fresh builds with B compared against A is correct. But the trace seeds include `ens_*` and `net_draw_kwh_corr`, which feed most of the payload. The expected-changed set would then cover nearly every key, and e3 could not fail. Eligibility is unchanged in this milestone, so leave those seeds out of the primary set.

## Tests
- **The MDE rule has no direction.** It says an unpowered test "cannot gate". For (a) and (c) that means they can never escalate, which is a new way to make a test unable to fail. Unpowered must default to the conservative outcome: no I2R switch, escalate, or dual report.
- **The MDE needs data before the data are touched.** It is "simulated at observed noise ... before the real data are touched", which is contradictory. Fix the noise inputs from the audit files.
- **(b)(ii) has a known outcome.** Its margin of ±0.10 A was set after the result 0.02 [-0.02, 0.07] was known. Disclose that.
- **(c) adjusts for variables that SoC itself drives.** Engine state and cadence depend on SoC, so adjusting for them biases toward equivalence (a false negative). Report VIF and the MDE with and without that adjustment.
- **(a) is weak.** Interleaving odd and even weeks balances season, so it is a heterogeneity check, not a correctness check. It is acceptable only as that.
- **(h) is well chosen, but the reset weight is unknown.** The slope is w x (scale mismatch), so it does not give "Ah per point" directly. The direction of the last current (relaxation and hysteresis) confounds it.

## WINDOW_FRACTION f
- **The reference capacity uses the wrong base.** If f = BMS span / true capacity, the true reference is `Q_SOC_EST/f`, not `CAP_AH_RATED/f`. They match numerically only because Q is about 5.0.
- **f_min mixes energy and charge.** It uses a kWh ratio while f is a charge fraction, and the hidden ends of the window sit at different voltages.
- **The DoD scaling is correct.** True DoD = BMS DoD x f.
- **"Lower bound for the weakest cell" is only conditionally true.** Every series cell passes the same Ah, so the weakest cell's FCE is at least the pack value only if its capacity is at or below the reference. New cells often exceed rated capacity. Resistance plays no part in series Ah.

## Protocol v2
- **These figures check out:** 88 A·s per step, 8-14 A, 6-11 s; the drives at 85.0, 85.5 and 88.0 %; dash 85 % equals BMS about 78 %.
- **Part A cannot identify R.** At 8-15 A, I^2R is about 8-28 W against a 3-5 kW load, below the per-leg SoC noise. Only near-zero load (L0) helps, and only for the offset.
- **A shared-sensor offset cancels.** It disappears in SoC versus the current integral, just as gain does.
- **Part A is mapped to a test it cannot feed.** Four days fall under the 8-day threshold, so Part A is descriptive only, yet it is still mapped to test (b).
- **CAP-A and CAP-B have no temperature PID,** but (b) and (c) adjust for temperature.
- **The protocol contradicts itself on stationary charging.** Line 15 states the stop level as fact, and line 16 lists it as unverified.
- **The ~10 % timing-skew figure is the external value.** It has not been audited.
