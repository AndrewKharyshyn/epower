# M307 results (F1, F1b, F2, F4, F3, F5) - computed 2026-09-30 by tools/f03_followups.py and tools/f03_f3_inspect.py
Spec: analyses/M307_f03_cellspread_spec.md incl. Amendment 1 (commit 925ffb6, dated before any F1-F3 run). Decision estimator: cluster-robust OLS t(G-1),
no day-bootstrap. Raw outputs: f1_f2_f4_results.json, f3_results.json, f3_features.csv. All "wording" rules of the spec apply.

## F1 - subset where published and fresh values coincide (n = 347 of 446; descriptive, selected on the outcome difference)
Slope +0.1165 mV/mo, CI95 [-0.256, +0.489]: contains the published slope (+0.0115), overlaps 0, does NOT contain the A-full slope (-1.62). Outcome: "not contradicted".
Per month (drives/days): May 18/6, Jun 39/17, Jul 55/18, Aug 75/23, Sep 137/22.
## F1b - outcome-blind subset S' (hash-verified OR zero drift on the 12 fixed non-cell-voltage columns; n = 168, subset of F1)
Slope -0.466, CI [-3.63, +2.70]: contains both the published slope and the A-full slope -> UNINFORMATIVE. Composition: Aug 15 drives/3 days, Sep 137/22 only.
Every May-Jul drive drifts on >=1 of the 12 non-cell-voltage columns: today's early raw copies differ broadly, not only in cell voltage.
## F2 - leave-one-month-out and May-Jun exclusion (fit vs published slope; influence = max|slope_LOMO - full| / SE_full)
- P: 6/6 subset CIs contain the published slope; LOMO slopes -0.35..+0.13; exclude May-Jun -0.178 [-0.927,+0.571]; max influence 2.37 SE (Sep).
- A (P-excl / own-excl) and B: full -1.62 / -1.67; only 2/6 subset CIs contain the published slope; LOMO -2.4..-0.68; exclude May-Jun -0.56 [-1.59,+0.46] (contains 0 and the published slope); max influence 1.69 SE.
- Month is confounded with hash status (no hash-verified drives May-Jul): date effect and alteration effect are not separable.
## F4 - hash-verified only: nObs 109, nDays 25, OLS SE 1.71 mV/mo, MDE(80%) 5.0 mV/mo. No trend claim.
## F3 - raw-file property separating D (99 altered) from matched C (99 hash-failing, identical spread, same months) - 12 pre-listed features
Best AUC 0.591 (quantisation step), permutation null (max AUC over 12 features, 1000 perms, seed 42) p = 0.123, null 95th pct 0.606 -> NOT explained by any pre-listed feature (falsification rule met: AUC < 0.9).
Hash-verified drives (H, n=109) reported separately (medians in f3_results.json).
### Exploratory observations (NOT pre-registered; hypotheses only)
- In 6 of the 99 altered drives the cell-voltage columns are quantised at 0.1 V and contain a physically impossible value (Vmax = Vmin = 53.0 V); the fresh p95 loaded spread is then exactly 100.0 mV (published max is 53.5 mV; no published value is 100.0). The other 93 shifts are small (85 drives < 30 mV).
- peak_I_discharge differs in 244 drives by ~0.5 A steps (e.g. 138.5 vs 138.0): consistent with reduced numeric precision (rounding) in today's copies. Candidate mechanism (hypothesis): reduced numeric precision / digit changes during transfer; controls share it, which is why F3 does not separate D from C.
- The fresh spread variance is 112.8 vs 19.0 published (driven by the 100.0 values).
## F5 - why the mixed-effects fit becomes singular in the fresh data
P: nObs 423, nDays 92, groupVar 1.35, converged. A (P-exclusion): LinAlgError('Singular matrix'); persists when the published spread is restored on the 99 altered drives => caused by the altered covariate peak_I_discharge (244 drives differ) and/or the altered spread inputs jointly, not by spread alone. The gate (tools/ingest_core.estimator_gate, tests/synthetic/test_estimator_gate.py) now aborts on a changed primary estimator or degenerate flag unless acknowledged; release_check WARNs on degenerate mixed fits.
