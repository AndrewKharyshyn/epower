# M408 spec (Rev 1): wording of the power-fade (resistance proxy) null result; the old `mde*` half-width leaves stay labelled as precision

Status: written before the edits. Wording step only (no estimator, number, payload key or headline changes). Branch `claude/next-milestone` from `main` (198cb47, M407). `drive_master.csv` MD5 `64dfd0cbff3db404d9b83e180f777525` unchanged. Origin: deep audit 2026-10-11 (F22/D-16: `mdeRisePctPerYr` is a bootstrap CI half-width, not a minimum-detectable-effect calculation), Director ruling `analyses/M406_director_ruling_2026-10-11.md` ("keep W3-mde unchanged"; relabelling of the old leaves is a separate wording step); owner direction "go as you recommend".

## Facts read from disk (2026-10-12)
- The dashboard already labels `powerFade.mdeMohmPerMo` / `mdeRisePctPerYr` as "95% CI half-width ... precision, not a power calculation" (xtrail_summary.jsx, power-fade view, HealthStatusCard, conclusions metric). Payload keys keep their historical names (the language wave never renames payload keys, M326).
- What is still inconsistent with the language discipline are payload and JSX strings that call the resistance-proxy trend "measured" or "statistically detectable / indistinguishable / detectable": `powerFade.note` (= `fadeModes.power.trend.note`), `fadeModes.power.whyNotProjected`, `officialDisclosureCorrelation.{resistance,rows[2]}.note` ("measured TREND"), `_retractedLifeEol` ("no degradation trend is detectable"), and the JSX "The measured interval straddles zero / excludes zero" plus one code comment.

## Changes (strings only)
1. Producers in `compute_summary_arrays.py` (four sentences): "a trend is not resolved in this window"; "the estimated trend is not resolved from zero in this window"; "the estimated TREND"; "no degradation trend is resolved in this window".
2. JSX: "The estimated interval ..." (two places) and the comment.
3. `tools/m408_splice.py` (allow-listed leaf splice, exact leaf counts, numeric-change guard, round-trip guard): the six payload leaves above.
4. `language_gate.py`: rule `M408-powerfade-wording` holds the OLD wording. `W3-mde` and `W3-power80` unchanged. Test `tests/synthetic/test_m408_wording.py` (in CI).

## Not changed (and why)
The `detectionHorizon` ladder and its "window needed / resolvable / not yet" table are already described as a planning figure at ~50 % power with the slope equal to the CI half-width; the M406 80 %-power minimum effect is shown beside the zero-slope statement in the Health panel. Other uses of "detectable/detected" in the payload (regime-transition persistence verdicts, daily-fingerprint verdict, stop-go methodology) concern different quantities and are outside this step.

## Acceptance
Splice changes exactly the six leaves; rebuild, jsdom, `dump_tabs`, `semantic_gate` (language gate passes with the new rule), CI unit list, `release_check.py`; CHANGELOG `M408`; dashboard presented (Dashboard change rule) and committed with its sources.
