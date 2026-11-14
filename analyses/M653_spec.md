# M653 spec Rev 1: show the mileage pace (owner decision, gate O)

Owner decision (Andrii, in chat, 2026-11-14, answering the open question of M652): "Yes, mileage pace can be shown. Continue with next items". Scope: `officialDisclosureCorrelation.usageRate.yearsToOfficialLifeKm` only.

Meaning: the disclosed mileage (190,000 km) divided by this study's logged km per year; plain arithmetic at the lifetime-average pace. It is NOT a battery-life, state-of-health or end-of-life estimate; every modelled year output (crossing years, spans, calendar-life ceiling, sensitivities) stays retracted (M114; `test_m632_official_fields`).

Changes: the builder no longer lists the leaf in `_LIFE_YR_LEAVES`; `tools/m653_mileage_pace.py` applies the same result to the carried payload (exact-leaf edit, deep-diff guarded, idempotent) and corrects the `_retractedLifeEol` note; the card label says "arithmetic, not a battery-life estimate"; `usageRate.note` already stated the same arithmetic. Binds to `S.officialDisclosureCorrelation.usageRate.yearsToOfficialLifeKm`.
