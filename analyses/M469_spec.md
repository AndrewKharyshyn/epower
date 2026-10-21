# M469 spec: bind typed calendar-aging literals; state the denominator families (audit 2026-10-21, hardcoded-literal table and dashboard table)

Scope (Opus triage "do now for literals with a computed key"): no estimator, producer, master or payload value changes; JSX text and the language gate only.

1. Methodology "Assumptions & scenarios" paragraph (xtrail_summary.jsx):
   - "Arrhenius (~50 kJ/mol)" -> `S.seasonalLife.assumptions.arrhenius.EaEv` eV (0.5 eV; the typed Q10=2 reading is dropped, Q10 depends on temperature at a fixed Ea).
   - "parked annual rate factor 0.40" -> `S.seasonalLife.calendarAnnualFactor` (0.399, equals mean of the 12 monthly factors).
   - "rising to 0.44 with observed driving heat (~1.5% of hours at ~40 C pack)" removed: no duty-weighted producer exists (audit: remove the driving-heat conclusion). Not to be confused with `hotTail.packThermalMeasured.driveTimeShareGeC` (a drive-time share, a different quantity).
   - "Winter quarter factor 0.145 ... ~7x" -> mean of `S.seasonalLife.monthly[Dec,Jan,Feb].calendarFactor` (0.143) and its inverse (7x). The typed 0.145 was already stale against the payload.
2. Overview "Counts by basis": adds the rainflow SoC-trace count (`S.rfDodHistogram.nFilesUsed`, 604) and states that the `S.eligibility.families` headline minus current-integral difference (14 drives) have missing, not zero, energy.
3. `language_gate.py` rule `M469-calendar-literals` (old wording: Q10=2, rising to 0.44, 1.5% of hours at 40 C, winter quarter factor 0.145).

Not in M469 (left open, needs the Director or a producer): the literature constants (Q10 vs Arrhenius presentation elsewhere, BSFC 217-290 glossary, climate 27/35-year limits and 15-year anchor), the historical 446/489/82-drive text (to a dated history panel), per-figure weighting-type labels (sample/time/drive/distance), thin fuel/highway marks.
Acceptance: rendered tab dumps show the bound values (0.399, 0.143, 14, 604) and none of the old strings; `release_check.py` green; 0 console errors in all tabs and cohort modes.
