# M536 spec (Rev 1, DRAFT for Director review): one project-wide definition of engine-on / engine-off (phase 1: inventory, threshold evidence, B1-B2 gap decomposition; the migration is phase 2)

Status: PRE-REGISTERED DRAFT, 2026-10-28, before any result. Owner: Andrii (chat, 2026-10-28: recompute the 2.325 h gap, "but the engine-on and engine-off concepts should be followed across the whole project (we should use a single definition)"). Origin: M521 mapped 23 engine-on lines to 7 bases (`analyses/M521_mapping.json`); the B1-B2 gap (2.325 h, 2.38 % of B2) could not be decomposed because the stored histogram has no 400 rpm edge (reconciliation INFEASIBLE from stored data).

## 1. Facts (from M521, not new results)
- B1 `rpmDistribution` / `engineOnBySpeed`: rpm >= 300 (stored edges 0, 300, 1400, 1475; wording in the code alternates between ">= 300" and "> 300"); 1 Hz grid, duration weighted. B2 `engineRuntime` (M512): RPM-supported intervals, eng_rpm > 400. B3: B2 share scaled by duration (imputed). B4 `rpmSyncPoint`: rpm > 400, moving. B5 turbo blocks: drives carrying boost and rpm PIDs. B6 `engineStartRate`: detector-defined ON runs. B7: generator-active (reconstructed Pgen > 0; M524 simultaneity / state machine wording). X: lines whose rule is not traced (`rpmFinding`, `simultaneity`, `engineStateMachine`). The regeneration programme uses a 300 rpm engine-off proxy by owner decision 2026-10-14 (g). The 300-1400 rpm bin holds 5.204 h (5.2 % of engine-on time on B1).
- Candidate canonical definitions are therefore at least: C300 (rpm >= 300), C400 (rpm > 400), a hysteresis detector (as in B6), and the generator-active state (B7) which is a different concept (power, not speed) and stays separate by name.

## 2. Phase 1 (this milestone): evidence, no payload change
1. Inventory of every producer and display line that tests or labels engine-on / engine-off (code grep of the thresholds 300 and 400, `engine_on`, `eng_rpm`, `rpm >`, plus the M521 rows): `analyses/M536_inventory.json`, one row per producer with its rule, time base, integration (1 Hz grid, interval, row count), denominator and the payload keys it feeds.
2. Threshold evidence from the raw 1 Hz rpm of the canonical-clean drives (read-only, staged `raw/`; per-drive compact counts keyed by raw SHA-256 in a tracked sidecar, pattern of `rpm_opt_band`): per-drive 1 Hz seconds in rpm bins fine enough to resolve 250-500 rpm and 1100-1500 rpm; the engine-on hours for thresholds {250, 300, 350, 400, 450, 500} on the SAME integration; the duration of excursions between thresholds (how many seconds sit in 300-400 rpm, and whether they are start-up / shut-down transients, by looking at neighbouring seconds only - descriptive).
3. B1-B2 gap decomposition on a common 1 Hz integration: (a) threshold term (300 vs 400 on the same grid), (b) denominator / support term (gridded vs RPM-supported time), (c) residual (integration and imputation). Accept: the three terms are listed with hours and sum to 2.325 h within 0.05 h, or the residual is reported as unexplained. No "closed" claim beyond that.
4. Day-clustered intervals (seed 42, 4000 draws) for the per-threshold engine-on share and for the (a) term; n drives and n days.
5. Output a Director brief: the proposed canonical definition(s) with the numerical consequence of each on every producer (hours and share changes), the producers that cannot follow the canonical rule (and why), and the producers that must stay separate by name (generator-active, detector ON runs, the 300 rpm regeneration proxy of the owner decision (g)).

## 3. Phase 2 (later milestones, only after the Director ruling and Andrii's decision)
Migration wave by wave (rpmDistribution / rpmOptBand / rpmModeCentres / motoredShare sidecars, engineOnBySpeed, engineRuntime, rpmSyncPoint, turbo blocks, the regeneration proxy): each wave its own spec, additive recompute or arrays-only splice with deep diff, language rule for the old wording, and a delta report. The regeneration proxy and the stored histogram edges are NOT touched in phase 1. Changing a published threshold changes published figures: escalate; no article figure without the Opus audit and Andrii's sign-off.

## 4. Acceptance, falsification, escalation
- A1 the per-threshold totals at 300 equal the stored B1 on-hours (99.867 h) within the sidecar rounding, and at 400 equal the B2 numerator logic only where the integration matches; otherwise the difference is reported.
- A2 the sidecar is reproducible from raw (per-drive SHA-256 keyed; sums equal the stored `rpmDistribution` bin hours where the bins coincide).
- A3 independent recomputation (analytical-auditor, blind: raw path and the threshold list only) of the hours at 300 and 400 for a drawn sample of drives.
- A4 escalate to the Director: any threshold changes the engine-on hours by more than 3 % of B1, the transient excursions (300-400 rpm) exceed 1 % of engine-on time, or the decomposition leaves a residual above 0.5 h.
- Stop: a producer whose rule cannot be identified from code is listed as unresolved, not guessed.

## 5. Language
"engine-on (rpm >= T on the 1 Hz grid)", "RPM-supported engine-on time", "generator-active (reconstructed Pgen > 0)" stay distinct names; no "fuelled" / "combustion" for rpm-only bases; rpm is logged, not measured by us.

## 6. Questions for the Director
Q1 Is the phase split right (evidence first, no figure changed)? Q2 Which candidate definitions must the evidence compare beyond C300 / C400 (e.g. hysteresis, minimum duration)? Q3 Does fixing one engine-on threshold require Andrii's explicit decision because it can revise published figures and touches owner decision (g)? Q4 Is the generator-active state kept as a separate named concept?

## 7. Gates
py_compile, script and sidecar tests (known-answer on a synthetic rpm trace), tracked sidecar + meta, release_check, CI unit list, CHANGELOG M536, PR with gated merge. Script `tools/engine_on_evidence.py` (sidecar `engine_on_evidence_sidecar.csv`).
