# Director ruling on the M410 serial-dependence results (2026-10-12)

Source: `research-director` (Opus), inputs `analyses/M410_results.json` (script-written block), `analyses/M409_spec.md` (Rev 0-3a), `analyses/M410_harness/harness_results.json`, the blind audit `analyses/M410_audit/` (independent reproduction of every rho_g, pair count, semivariogram bin, HAC SE L=3/7/14, GLS rho/slope/SE and the rho_1 bootstrap CI; agreement to the printed precision, bootstrap endpoints within 0.005 across seeds; audit did not cover the moving-block, VIF and control H quantities, on which the classification does not hinge). Saved in substance by the main session.

```json
{"decision":"revise",
 "reading_sentences":["Serial dependence between neighbouring days (rho_1, calendar distance 1 d) is not supported by these data at this precision for either slope; this is not evidence of absence: the rule has 67 % power at phi=0.3, so moderate dependence is not excluded.",
  "Cell-spread slope: procedure-dependent. The lower bound changes sign across procedures (4 of 10 OLS-based rows exclude 0); the upper bound is similar.",
  "Resistance proxy: every row includes 0.",
  "GLS on day means is a separate estimator, shown beside the rows and outside the classification.",
  "Unchanged: trend not resolved; equivalence not established; no stability or SOH claim; TOST decision and released estimators unchanged."],
 "forbidden_readings":["no/absent serial dependence; days independent; CR1 adequate","HAC/block/GLS as corrected, dependence-robust or primary; any envelope","rho_2 (or the bin-2 variogram dip) as support or as a weekly cycle","rho_pre-rho_post drop read as seasonal","VIF 1.11 as 'dependence adds only 5 %'","HAC L3 exclusion, or resistance HAC SE shrinking with L, as tighter evidence","significant/robust/detected/confirmed/measured"],
 "disclosures":["Rule switched rho_{1-3} -> rho_1 after harness power (forking path); pooled statistic beside, agrees","rho_2=0.25 (CI excludes 0) not pre-specified, no multiplicity adjustment; self-audit ~0.25 not reproduced at distance 1; not reconciled by lag choice","Rev 1 10 % criterion FAILED at phi=0.3, not re-scoped","rho_1 percentile CI shifted (median < point)","Harness: HAC L14 under-covers under null; all rows under-cover at phi=0.6; moving block L14 has few blocks and a wide draw-size range","Smooth drift collinear with months invisible to residual tests; one vehicle, May-Oct"],
 "required_changes":["_provenance must cite Rev 0-3a (rule = Rev 3)","state that H is reported descriptively although B is 'not supported' (Rev 1 had conditioned it)","label the pooled statistic 'original statistic (Rev 1)'","add the forbidden readings to language_gate RULES before binding","CHANGELOG: audit verdict + this ruling; binding = separate milestone; then merge additive, no further Director round"],
 "needs_andrii_signoff":false}
```

Applied in M410: all five required changes (provenance string, `descriptiveNote`, pooled-statistic label, language rule `M410-serialdep-readings`, CHANGELOG record). Dashboard binding is a separate milestone.
