# M407 spec (Rev 1): dashboard binding of the M406 dependence sensitivities (reporting-only)

Status: written before the code. Branch `claude/next-milestone` from `main` (9a5290a, M406). Reporting-only: no estimator, payload leaf, headline or TOST decision changes; `drive_master.csv` MD5 `64dfd0cbff3db404d9b83e180f777525` unchanged. Authority: Director ruling `analyses/M406_director_ruling_2026-10-11.md` ("dashboard binding: GO after these items", rulings 1-5); owner direction "go as you recommend". Article-bound: nothing enters the article without an Opus audit and Andrii's CHANGELOG sign-off.

## What is added
`buildS` gets `dependenceSensitivity: A.dependenceSensitivity || null`. One panel (`data-dependence-sensitivity="true"`) in the Health tab, section "Cell-Spread Health Indicators", directly after the M19 cross-check box. Every number binds to `S.dependenceSensitivity.*`; the panel types no figure. The standing statements ("trend not resolved; equivalence not established; no stability or SOH claim") and the old `powerFade.mde*` half-width leaves are not touched (their relabelling is a separate wording step).

## Panel content (Director rulings 1-5)
1. **Trend slopes (cell spread, mV/month; resistance proxy, mOhm/month)**: one table per series in the payload's fixed order, identical format, no primary interval and no envelope: CR1 (released interval, the reference), CR2 (Satterthwaite t, df), wild cluster bootstrap-t (null-imposed p shown as "about p (seed range lo-hi)"), day-cluster pairs bootstrap, week-block pairs bootstrap (labelled "dependence-conservative"; "fewer than 10 blocks" flag when `fewBlocks`).
2. **Sign sentence computed from the data**: when the lower bounds of the five procedures do not all lie on one side of zero: "lower bound changes sign across procedures"; the upper-bound sentence ("upper bound similar" only when the spread of the upper bounds is at most a quarter of the released interval width, otherwise "upper bound also varies"). Otherwise "all lower bounds lie on the same side of zero".
3. **Minimum effect with 80 % power** (CR2 value, CR1 beside it) with the Director label "slope a two-sided 5 % test flags with 80 % probability at the observed SE (design-conditional)", shown beside the zero-slope statement only. The equivalence statement carries the TOST re-run under CR2 (p, verdict, same frozen bound) as a sensitivity and no minimum-effect figure.
4. **Logging regimes**: fast and slow rows, label "imprecise; not a regime comparison; subgroup, not a finding".
5. **Thesis KPIs K1-K5**: estimate, day-cluster interval, week-block interval, width ratio; K2 corrected and raw both shown; throughput "integrated from logged current, estimated"; raw label "raw/ = sha256-verified originals (M366)"; intervals described as precision ("consistent with", never "demonstrates"; they do not test the thesis); the ratio ranges for drive medians and corpus ratios come from `kpiWidthRatioWeekOverDay`.
6. Limits list from `limits`; `reading` and `reportingRule` quoted.

## Wording constraints
Never: significant, confirmed, stable (stability only inside the standing sentence), robust (only inside "cluster-robust" already used elsewhere; not used here), detected, MDE, detectable, rules out, observed power, post hoc power, powered to detect (rules `W3-mde`, `W3-power80` unchanged). Estimated/reconstructed/model-derived; no "measured".

## Acceptance
`node build_html.js`, `validate_jsdom.js` (0 console errors), `dump_tabs.js`, `semantic_gate.py` (new A2 REQUIRED checks: the panel is in the Health All/Warm/Shoulder dumps with the five procedure labels, the computed sign sentence matches the payload, the minimum-effect label appears beside the zero-slope statement and not in the equivalence row, regime label, K2 corrected and raw, no forbidden word), CI unit list, `release_check.py`, CHANGELOG `M407`, dashboard presented in-session (SendUserFile render) and committed with its sources.
