# M547 spec Rev 1 (2026-10-31, before any edit): audit 2026-10-29 wording wave A

Status: Rev 1, for Director review. Nothing implemented. Origin: `epower_audit_2026-10-29.html` findings F02 F03 F04 F06 F07 F08 F09 F10 F11 F12 F13 F14 F16 F18 F19 F21 and the section-9 wording list; triage in `analyses/audit_2026-10-29_triage.md`.
Branch base: `main` at M546 (`cc59f74`). Ledger id prefix: `AUD29-Fnn`.
Scope: WORDING ONLY. No estimator, eligibility, number or payload-key rename. Every sentence that cites a number gets it from `S.*` (literals on touched lines go to zero). Rows needing a new payload key or builder label are tagged DATA and listed separately.
Out of scope: F01, F05 (number changes, own milestones), F15/F20 (M548), F17, N01-N13, section-9 UI options B and C, the Ukrainian article.

## Mechanism
Same as M326: each replaced string is added as an OLD-wording `Rule` in `language_gate.py` (RULES) with its ledger id; matching is NFKC-normalised, plural-safe, with known-answer fixtures including hedged correct forms. Added REQUIRED checks where a replacement is mandatory. A regression test that every existing rule still fires.
Positive/negative/zero-spanning/unavailable interval fixtures for F03/F04 (the audit's acceptance test): title, status and caveat are generated from one result object.

## Row list (current location at M546 -> old -> new)
Line numbers are `xtrail_summary.jsx` at `cc59f74`; the implementation re-greps before editing.

| Id | Loc | Old wording | New wording (numbers from S.*) |
|---|---|---|---|
| F02 | 7506 | "does not significantly predict the SoC ceiling itself" | Report the weak association with its nominal, unadjusted p from `lowSpeedDissipation.relief.altVsSocMax` (rho, p), then: coarse pressure resolution, repeated trips and confounding prevent a causal terrain conclusion. Generated from the payload so sign/size cannot disagree. Builder verdict string (`compute_summary_arrays.py` near the altitude verdict) is DATA-text: same sentence. |
| F03 | 12865 | "the interval can only exclude resistance growth faster than its CI half-width" | "the conditional 95% slope interval extends up to {S.powerFade.ci95MohmPerMo[1]} mOhm/month; the trend is unresolved". Half-width stays as "precision" only. "MDE" label (2589-2692, `mdeMohmPerMo`) shown as "95% CI half-width (precision)"; the key `mdeMohmPerMo` is NOT renamed (rule: a wave never renames keys). |
| F04 | 12857 title, 12953, 5005, 12679 | "A cell-voltage-spread trend is not established in this window" (static) | Title/status/caveat selected from `degradationTrends.cellSpread.clusterRobustOLS` by interval sign: positive excludes zero -> "Loaded cell-voltage spread rises under the published adjustment ({slope} mV/month, 95% [{lo}, {hi}]); battery ageing is not identified"; zero-spanning -> "unresolved"; unavailable -> "not available". A zero-spanning caveat is never attached to a positive interval. 12953 combined cell-spread/resistance sentence split by component. |
| F06 | 12343 | "independently corroborating ... two unrelated sensors agreeing" | "Calculated boost is consistent with the logged manifold-pressure channel; the two are related (app-derived), so this is an internal consistency check, not an independent sensor validation. Gauge conversion subtracts a stated 1 bar approximation." |
| F07 | 11992 | "therefore cadence-immune by construction" | "evaluated on a common 1 Hz grid; residual native-cadence sensitivity (missed transients, asynchronous pairing) is not removed and is assessed separately". |
| F08 | 7472, 7475, 7517 | "independent lower bound", "lower bound on total ceiling-defence dissipation", negative control "dissipates nothing" | The pumping/friction and reference-deceleration outputs are separate unvalidated model scenarios; the interval is a scenario range, not a physical bound; remove diverted-energy attribution; negative control is "a comparison group with the same motoring signature, not a validated zero". Observed pack energy and the event signature stay. |
| F09 | 6137, 6139, 12122 | "classify fuel state directly ... strictly boost-verified, no proxy"; "engine spun unfuelled"; "fuelled generation" | "fuelled-proxy" / "motoring-candidate"; rotation (RPM) is stated as observed, combustion as inferred from boost/load and app-calculated fuel; no injector/fuel-cut ground truth. Touches RPM-occupancy views (rules shared with the M545/M546 engine-on wording: re-check the engine-on rules in `language_gate.py` first). |
| F10 | 3734, 3756, 3759 | "BMS SoC - actual (hidden from driver)"; "flatters"; "reassuring"; design intent | "Reported BMS SoC (%)" and "driver-display SoC"; "the two channels use different nonlinear percentage scales and cross near {S...crossoverBmsPct}%; this does not establish true physical SoC or design intent". |
| F11 | 11952, 11953 | "the generator always has ample headroom"; "statistically identical" | "the observed battery-discharge pattern is consistent with SoC steering and transient buffering; no event meets the declared saturation screen ({S.saturTotalS} s, {S.saturDrivesN} drives); generator output and reserve are not metered". Equivalence is not claimed (no margin test). |
| F12 | 12320, 12823 | "Comfortably within typical limits"; finite maximum as evidence against unbounded rise | "Highest recorded probe temperature {x} C; highest pack-mean maximum {y} C (observed exposure). No pack-specific thermal margin is established." Equilibrium sentence: "later supported trajectory segments often flatten; trip support changes with elapsed time". |
| F13 | 12686 | "-200.25 A, outside sensor's valid range ... corrupted" | Remove the sensor-range assertion; state the single current validity policy of record (`records` contract) or leave the example as "excluded under the artifact rule of that time" with the actual evidence. |
| F14 | 13368 | "All aggregate statistics in this dashboard filter on ens_outlier_v2" | "Each metric family declares its own eligible drives, days and distance; exposure totals, quality-filtered summaries and frozen model fits use different populations (see the eligibility table)". |
| F16 | 2891, 11712 | tab "Capacity fade - scenarios" | "Exposure scenarios" (GTC per year under assumed mixes; reference named). |
| F18 | 3853, 3854, 3862 | "COLD RISK", "plating zone", "OPTIMAL {lo}-{hi} C" | "Cooler / intermediate / warmer recorded probe temperatures"; legend note "generic reference boundaries, not validated Nissan limits or evidence of plating". Zone object keys unchanged. |
| F19 | 11845, torque record | "Full-Cell Array Worked Examples"; "Peak motor torque" described as output ceiling | "Selected cell-channel snapshots" with cell count and age spread shown; "Peak commanded motor torque" (record label is a display string; the `records` metric key is NOT renamed, label mapped in jsx). |
| F21 | 12806, 12936 | `regenCaptureMeta` plateau/crawl headline unqualified | Label "Legacy extraction reference (50-110 km/h plateau, 0-30 km/h; selection rule ...)" beside the active displayed estimator; never an unqualified old headline when `regenDisplayV2` is displayed; a short method-bridge line names estimator, bin, population, weighting and mass convention for both. |

## Section-9 list
The 26 proposed rewrites in the audit's section 9 are mapped row-by-row to the above or added as separate rows in a Rev 1 addendum if not covered (resolved with the Director). Rows touching "Generator always has headroom", the BMS mapping, the cell-spread finding and the dissipation range are covered by F11/F10/F04/F08. Remaining ones (terrain, standby, fuel agreement, engine-off travel, cross-vehicle, regeneration finding, risk summary) are listed in the addendum with exact strings before edit.

## Pre-registered tests
1. Isolation: `drive_master.csv` MD5 `5556a0c6c8bcde0f6c64b8b9655208ed`, `raw/`, `raw_manifest.json` byte-identical; `summary_arrays.json` deep-diff limited to DATA string leaves declared in the addendum (empty for pure jsx rows); no number changes (jsdom text diff shows only declared sentences).
2. Language gate: every OLD string added as a RULE; gate fails if one reappears in a tab/mode dump, jsx source or payload string; hedged correct forms pass.
3. Binding: replacement numbers are `S.*` bound; hardcoded-literal count on touched lines is zero.
4. Interval-text fixtures (F03/F04): positive, negative, zero-spanning, unavailable.
5. `dump_tabs.js` 0 console errors; `release_check.py` green; CI unit list run locally before push.
6. Director reviews the old -> new JSON brief (not raw prose). No article figure is introduced, so no Opus article audit; the thesis wording rows (F08, F11) also need Andrii's sign-off before merge.
7. Dashboard rule: present `xtrail_dashboard.html` (SendUserFile render) with a one-line change note, commit jsx + summary_arrays + cohort_arrays + html together; the agent opens the PR.

## Risks
- Shared files `xtrail_summary.jsx` / `language_gate.py` / engine-on rules (M539-M546): rebase on `main` only; F07/F09/F11 sit in engine-on prose.
- Over-broad regexes failing correct hedged text (fixtures).
- Local CI unit list rewrites tracked files (restore before commit; stage explicit paths).

---
# Rev 2 (2026-10-31): Director review of Rev 1 incorporated, before any code
Director verdict on Rev 1: REVISE (row changes below; section-9 strings now exact; gate additions; sign-off list). Rev 2 is sent back for a short confirmation review; no edit starts before it.
Where Rev 2 and the Rev 1 table differ, Rev 2 governs.

## Row changes
- F02: also generate the 7505 altitude-vs-motored line from the payload; drop the 7509 sentence "mechanism is solid". Builder verdict string `compute_summary_arrays.py:9007` ("does NOT significantly predict") gets the same generated sentence (DATA-text leaf).
- F03: also fix the title near 12863 ("No resistance-proxy trend is detectable") and "shows no trend". Text comes from `trendLabel(ci)` over `S.powerFade.ci95MohmPerMo`, not a static "unresolved"; show [lo, hi]. No annualised endpoint percentage (that would be DATA; deferred).
- F04: title/status/caveat are selected from the interval sign AND the M477 `rowsRule` (procedure dependence): positive primary interval but procedure-dependent lower bound says so; status badge is not "notEstablished" when the primary interval excludes zero. The Rev 1 location 5005 is the RESISTANCE sentence; cell-spread locations are 12857 (title), 12953, 13187, 13341, 13368. `cell_spread_trend_violations` in `language_gate.py` is extended (null phrases + `rowsRule`).
- F06: before editing, verify in the code whether the gauge conversion really subtracts a fixed 1 bar; wording follows the code.
- F07: also replace "saturation-gate null" with "no event meets the declared saturation screen".
- F08: do NOT show a single "scenario range" (still implies bracketing). Show the pumping/friction and reference-deceleration outputs side by side as separate model scenarios; "Bias-corrected" -> "excess over the comparison group"; relabel the "Diverted" row; rewrite the 7517 lower-bound logic. Andrii sign-off.
- F09: proceed only after re-checking the engine-on rules (M539-M546) in `language_gate.py`; drop the purpose clause "to dump surplus regen".
- F10: include 3756 "Design intent" and "wider than the pack physically uses".
- F11: state the actual load-test result ("calculated engine load in discharge seconds is not distinguishable from charging seconds; equivalence was not tested"), replace "reserve measured above" (12030) and the status "measured" (12847): the reserve is derived from app-calculated load. Andrii sign-off.
- F13: SPLIT. Text: remove the sensor-range and "corrupted" / "not a real cell event" assertions. Re-running the example under the current validity policy is DATA and is deferred (own item).
- F18: bind the 4953 literals to `S.*`/zone object.
- F19: "Peak motor torque" is a payload metric value (`S.records` match at 12090), so the rename is display-only in jsx; the gate rule is scoped to the DOM/rendered text, not to payload strings.
- F21: no between-version or between-stratum contrast (M446 rule). Label the legacy block; bridge fields are DATA if absent and are then deferred.

## Section-9 addendum (exact strings, located in source at `cc59f74`)
Of the audit's 26 rewrites, the "current framing" quote was located in source for only the rows below. The other quotes are the auditor's paraphrases of text that is already hedged or worded differently; no old-wording gate rule is added for a phrase that does not exist in source (it could only block legitimate text). Each such row is recorded "not located, no action".
Adopt (in M547): header reference (11546 "2.1 kWh HV battery (nominal, verified:false)" -> "Battery energy reference: 2.1 kWh, assumed; turnover and C-rate use the separately stated 5 Ah reference", after verifying the 5 Ah claim on the payload); standby (12353 label "Car OFF standby" -> "Parked SoC-drift equivalent"; the value cell already says SoC drift); cell arrays (covered by F19; 7583 and builder 14320 already hedged); EV share (10998 "Pure-electric traction support" -> "Engine-off travel share", citing the `engineStateMachineRule` threshold); thermal curve (12320 already says "not an established equilibrium": no action).
Defer: temperature ranking (to M549, F01); start impulse title 12723 "Each engine restart is buffered by a brief, bounded battery impulse" and the median engine-start diagram (to the engine-on programme follow-up).
Not located, no action: battery-branch energy, turnover ("987.4 cycles accumulated": any rewrite must name ONE EFC quantity, GTC / FCE / Rainflow-EFC, and needs Andrii), heating state, terrain, fuel agreement, cross-vehicle, regeneration finding ("no 'differs' unless tested"), risk summary. If a later grep finds the string in a payload or builder leaf, the row returns as a Rev 3 addendum item, not silently.

## Gate additions
Fixtures that the NEW wording does not fire any rule (including hedged forms); extend the F03/F04 interval fixtures with `rowsRule`; a fact check that a CI half-width is never called a bound; REQUIRED checks per row in all modes; rule scopes for key-equal strings (rendered-text scope for "Peak motor torque").

## Sign-off (Andrii) required before merge
F08, F11, F04, F10, the turnover/EFC row (if ever located), F21.

## Rev 2.1 (Director confirmation: GO, 4 conditions recorded before the first edit)
1. The audit has 28 "Current framing" entries (not 26). The row-by-row map covers all 28: 5 located and adopted/deferred as above, 1 more located (terrain), 22 not located.
2. Terrain ("Altitude does not significantly predict the SoC ceiling") IS located: it is F02 (jsx 7506, builder `compute_summary_arrays.py:9007`). Reclassified as covered by F02, not "not located".
3. EV-share: "Pure-electric traction" is rendered at jsx 10998 (KPI title), 11847 (Section title) and 7205 (ColdNoData chart label). All rendered occurrences are replaced (or the rule is scoped to rendered text) before the gate rule is added. Code comments (v6 16/1393/1418, builder 1228, jsx 7173) are WARN only.
4. F04: if the cellSpread status badge reads a payload status value, that is DATA and is declared in test 1 (deep-diff allow-list); otherwise the mapping is jsx-only.
