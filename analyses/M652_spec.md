# M652 spec Rev 1: official-disclosure wording leftovers adjacent to M642 (gate L, wording only)

No number, estimator or payload key changes.

Changes
1. Dashboard card: "motor 150 kW rated vs 66 kW battery cap" becomes "vs 66 kW disclosed battery figure (at 80 % SoC)" (the sheet's figure at a stated condition; the logged peak exceeds it, so it is not a cap; both numbers come from `officialDisclosureCorrelation.power`).
2. Resistance paragraph: the end-of-life level 367.5 m-ohm is derived (new value x (1 + the sheet's maximum rise)), not a printed figure; it is now stated as "implied ... (derived: new value x (1 + rise), not a printed figure)".
3. `officialDisclosureCorrelation.basis` text "own measured / modeled figures" becomes "own logged and estimated figures": builder text in `compute_summary_arrays.py` and the same exact-string edit of the payload leaf (not rendered; the builder would write it at the next arrays build). Language rule `M652-official-disclosure-wording` carries the old wording.

Left unchanged, stated
- `capacityFadeAnchor.rows[1].measured: true` is a payload key and not rendered; payload keys are never renamed (language-gate standing rule).
- `usageRate.yearsToOfficialLifeKm` is null by the M114 policy (life-year conversions are nulled corpus-wide) while `usageRate.note` states the arithmetic mileage-clock "~9.0 years from new". Whether the mileage-clock arithmetic (190,000 km / km per year, not a battery-life estimate) may be shown is an owner decision, not made here.
