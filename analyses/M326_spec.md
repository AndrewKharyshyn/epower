# M326 spec rev 1 (pre-registered 2026-10-02, before any edit): audit-v3 wording sweep - wave plan and language gate
Status: DRAFT for Director spec review. Origin: ledger rows with milestone label M322 in analyses/audit_v3_triage/ledger_all.tsv (250 rows: 239 FIX-NOW, 10 INFO, 1 STALE), wave assignment in analyses/M326_wave_plan.tsv (keyword heuristic, refined per wave). Milestone number is a proposal (M325 merged).
Scope: WORDING ONLY. No estimand, estimator, number or eligibility changes. Everything the sweep needs that is NOT a pure text edit is tagged DATA (a new/renamed payload key, a builder label, a config string) and handled in its own step with an isolation diff.

## Problem
The dashboard and payload strings overstate what the data supports (examples verified in the ledger): fuel/generator quantities called "measured" or "tank-to-traction"; "no Cold" / "0 drives" where 2 drives / 1 date exist; "Season" for what are ambient cohorts; "direct SOH"/"measured power fade"; hand-typed literals contradicting the payload (e.g. "No sub-15 C", "410/410"); "great majority has no fuel-flow PID" (263/489 headers have it). 239 rows is too many for one reviewable change.

## Design: 6 waves, one PR each, risk order (thesis-critical first)
W1 GTR / fuel / generator language (70 rows): f_gen is a sensitivity index, battery-to-traction a model residual, BSFC/etas assumed; no "battery majority", "measured fuel", "tank-to-traction", "two-thirds lost as heat"; Pearson r reported as association only (ratio offset), not validation. F04 stays open (M329): wording must not imply the branches close.
W2 Thermal cohort / Cold counts / ambient (39 rows; includes DATA: cohortCounts observed vs eligible, refresh_seasonal_kpis.py wording, ColdNoData reads observed 2 drives / 1 date).
W3 Health / degradation / proxy labels (58 rows; DATA: rename mdeMohmPerMo -> CI half-width in builder + jsx together; no "direct SOH", "measured power fade", plating inference).
W4 Records / EFC / GTC / throughput labels (29 rows; three EFC quantities kept distinct).
W5 Overview / Methods / limits box / docs (19 rows; generated docs counts via tools/state.py).
W6 Remaining chart/caption rows by tab (35 rows).
Each wave is its own milestone number, spec addendum (row list, exact replaced strings, DATA items), release gate and dashboard presentation.

## Mechanism (the lasting part): extend the existing language gate
semantic_gate.py already holds FORBIDDEN phrases checked on the jsdom tab dumps and payload strings. Each wave:
 1. lists the OLD strings it removes and adds them to `FORBIDDEN` (with reason and ledger id) so they can never return;
 2. adds `REQUIRED` checks where a replacement is mandatory (e.g. the Cold slot shows the observed count from the payload; footer counts equal f03_provenance);
 3. replaces literals by S.* bindings; any number in a replacement string must come from the payload (the gate recomputes it, as rule B of the gate does).
Canonical glossary (applied by all waves, from the ledger): "measured" is reserved for logged channels; fuel rate/counter = "logged / app-calculated (Car Scanner)"; fuel energy = logged volume x assumed E10 LHV; generator/traction/battery-to-traction = "estimated / reconstructed / model-derived"; "Season" -> "Thermal cohort" (ambient classes); Cold = observed count, below support, no inference; spread/V-regression = proxies, never direct SOH; MDE field = CI half-width; "no degradation" never ("trend not resolved; equivalence not established").

## Pre-registered rules and tests (per wave)
1. Isolation: drive_master.csv, raw/, raw_manifest.json byte-identical; summary_arrays.json deep-diff limited to the DATA keys declared in the wave addendum (empty for pure-text waves); no number in any figure changes (jsdom text diff before/after limited to replaced strings).
2. Language gate: every removed string added to FORBIDDEN; gate fails if a removed string reappears in any tab/mode dump, jsx source or payload string; word-bounded and plural-safe matching (lesson M325: 're-serialization' vs 're-serializations').
3. Binding gate: each replacement that cites a number/date/count is bound to S.* (no new literals); the existing jsx hardcoded-literal WARN does not increase.
4. Render: dump_tabs.js 0 console errors, all 36 dumps produced; release_check green.
5. Director reviews each wave's JSON brief of changed strings (old -> new -> ledger id), not raw prose; a wave touching the thesis wording (W1) also needs Andrii's explicit sign-off before merge (battery-vs-generator share language).
6. Dashboard rule per wave (present the dashboard, commit jsx + arrays + cohort_arrays + html together).
Out of scope: re-estimating anything (F04/F20 GTR repair = M329), fuel contract (M328), moving/adding tabs, the Ukrainian article.
