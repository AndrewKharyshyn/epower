# M418 Director ruling (research-director, Opus), 2026-10-12: wording of the thermal support lines

Decision: **revise** (the proposed sentences S1-S5 were returned with required changes; all were implemented before any dashboard text was bound). No Andrii sign-off needed (reporting-only counts, no article figure).

Scientific meaning (Director): the ledger shows what each thermal estimator was computed on (370 cold starts, 165 reached 80 C coolant, 205 right-censored, 55%). It describes support only. Because more than half of the 80 C cold starts are censored, the reachers-only median does not identify the cohort median and cannot be read as a typical warm-up time.

Required changes and where they were implemented
1. hvcEngine80C counts are per class; name the class; show coldStartAndReached / coldStartNotReached -> `ThermalSupport part="curve"` (one sentence per class with n > 0, warm restarts counted inside the reached figure, cold-start split).
2. Fuel counts must sum to the candidates (the Director's brief omitted `fewerThan60ValidCoolantSeconds`; the payload has it: 226 + 1 + 88 + 117 + 1 + 121 = 554) -> partition checks for all four estimators in the ledger reconciliation (12 checks over all / warm / shoulder) and in `semantic_gate.py`.
3. Each sentence states its own warm-start definition (lag and fuel: first valid coolant >= 60 C; curve: > 50 C; hvc: no gate, warm restarts counted as reached at about 0 min).
4. Oil start is not gated (an oil start at or above the threshold is counted as time 0): oil sentences state `atOrAboveAtStart`.
5. Days beside drives: `coldStartDays`, `candidateDays`, per-class `nDays`, `acceptedDays` (fuel, curve) added to the ledger.
6. Limits: single vehicle, one driver, May-October, ambient 3-38 C; censoring may be informative -> in the note under every support line.
7. Language: no "penalty" in display text (M339); no "failed to warm up" / "survival" even negated -> the payload reading text was rewritten ("time-to-event estimate"); rule `M418-thermal-censoring` in `language_gate.py` (forbids failed/did not/never warmed up, "engine warms up in", "typical warm-up time", "median warm-up time" without "reachers", survival curve/estimate/function/probability/analysis, Kaplan-Meier, "winter warm-up", "measured fuel").
8. Median label: wherever a pooled time-to-threshold median is discussed the support line says "Median of reachers only (r of cold); censored drives excluded, so it understates the time for all cold starts" and, when fewer than half of the cold starts reached the threshold (coolant 80 C), "cohort median not identifiable from these data" (gate: the count of that sentence equals the number of thresholds with share reached < 0.5).
Follow-ups listed by the Director: article use requires an Opus audit and Andrii's sign-off; the old hvc string "% of drives (n=" without a class is not changed here (no language rule; the payload string is existing published text).
