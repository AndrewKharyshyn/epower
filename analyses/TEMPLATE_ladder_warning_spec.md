# M### pre-registered spec (rev 1): response to an M321 ladder-monitor warning (TEMPLATE; copy to analyses/M###_spec.md, fill every <...>, delete this line)

Status: written BEFORE any M### result exists (<date>; master <N> drives, MD5 <md5>; main at <commit>, tag <M###>). Origin: the M321 monitor (`socHysteresisV2.tempLadderMonitor`) reported status `<warn-newspec | warn-refit>` on this ingestion. Needs a Director review of this spec before implementation (CLAUDE.md: method change -> blind audit and Director decision).
Wording: model-derived and associational (pack temperature is confounded with season, date and pack age), never measured; fitted on `raw/` (F03): not M299-reproducible; dashboard-only unless a figure is proposed for the article (then Opus audit and Andrii's sign-off).

## Trigger (copy from the monitor block; script-written numbers only)
- `warningSetHash` <hash>, `warningCodes` <W2:start:-7.5, W3:stop, ...>, status <...>, basis <N> drives, current corpus <M> drives (<k> new).
- Observed vs fit-basis pack-temperature range per side; W2 candidate level(s) with events, event days, early-support flag (< 20 event days), boundary-dependence; W1 quantile shifts; W4 levels that lost support; F03 flag (changed raw hashes of basis drives, reported separately, not drift).
- Season/date confounding: the cold drives are also the newest drives. State what cannot be separated.

## Question (one only)
<e.g. "Does the V2 hazard model remain adequate below the fit-basis minimum, and can a cold ladder level be supported?">

## Options (the Director ranks; tick the one the spec pre-registers, state why the others are out of scope)
1. Report only: acknowledge the warning (no method change); the ladder and surfaces stay on the fit basis; the dashboard keeps the "ladder basis N drives" stamp and the amber banner.
2. Explicit V2 refit on the extended corpus (`recompute_m119v2`, about 25 min) and a re-derived ladder (`tools/m318_run.py tables` -> `tools/m320_ladder.py run/apply` -> `tools/m321_ladder_monitor.py rebase/update`); the gate enforces the chain. Needs a no-new-drive control (refit on the basis drives with today's code and raw) so deltas split into code, provenance drift and new data.
3. A colder fourth level (W2): a method change; needs knot sensitivity first (the new level lies beyond the boundary knots, the spline is linear there).
4. Model extension for cold regimes (cabin-heat or warm-up starts, pack power limits; coolant / ambient covariates that CORE5 lacks): a new analysis with its own spec.

## Pre-registered design (fill for the chosen option; copy rules from analyses/M320_spec.md and M321_spec.md, do not re-tune)
- Population and eligibility (complete-case rule, canonical exclusion, day key `_day_key`), resampling unit (calendar day), bootstrap 4000 draws seed 42, CI type, delta for distinctiveness (log 1.25) and gate thresholds (100 events on >= 10 event days; imported from `tools/m320_ladder.py`).
- Primary vs sensitivity analyses; method-disagreement reporting (seconds- vs day-weighted quantiles, secondary cells).
- Accept / reject: validity checks (known-answer test, isolation diff, exact blind-audit reproduction of counts and levels, no out-of-range cell rendered, no literals in the JSX, release gate, master MD5 unchanged, LF endings) vs scientific outcomes (reported and escalated, never tuned).
- Falsification: <what result would show the premise is wrong, stated before any result>.

## Procedure after the decision
1. Commit this spec and the Director's edits before any result.
2. Implement; run the validation chain (py_compile, isolation diff, `release_check.py` with `PYTHONUTF8=1`, `node validate_jsdom.js`).
3. Blind audit (claim + data path only), then Director decision; record deviations.
4. Acknowledge the warning set ONLY after the decision: `python tools/m321_ladder_monitor.py` is not used for this; run `python tools/m321_acknowledge.py --ref "M### <title>" --note "<one line>"`. The record carries the warning-set hash and the current basis identity, so it cannot clear a recurring set after a refit or rebase.
5. CHANGELOG entry (`python tools/changelog_draft.py ...`, numbers script-written), dashboard change rule (render the dashboard, commit with sources), PR, merge on green CI.
