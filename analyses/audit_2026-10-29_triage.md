# External audit 2026-10-29: triage and backlog

Source: `epower_audit_2026-10-29.html` (snapshot M533, 606 drives, score 6.70/10, post hoc and exploratory).
Triage: Opus research-director brief plus greps at M545 (2026-10-31). Effort figures are estimates.
Status: PLANNING ONLY. No implementation starts before M546 merges (`xtrail_summary.jsx`, `language_gate.py`,
`compute_summary_arrays.py` `_RawAccum` are being edited by the M545/M546 session).

Rules for use of the audit's numbers: known-answer targets and external corroboration only; never typed into the repo.
Anything entering the article still needs the Opus audit and Andrii's sign-off.

Tiers: A = wording/label fix (language_gate rule with ledger id for the OLD wording, sentences generated from payload);
B = code fix that changes numbers (spec, blind audit); C = new analysis (spec, blind audit, Director); D = parked.

## Milestone sequence (proposed numbers; renumber from the CHANGELOG head)

| Milestone | Scope | Tier | Days |
|---|---|---|---|
| M547 | Wording wave A: F02 F03 F04 F06 F07 F08 F09 F10 F11 F12 F13 F14 F16 F18 F19 F21 plus the 26 section-9 rewrites | A | 4-5 |
| M548 | F20 (`docs/overview.md:27` stale; generate state sentences), F15 (deprecate `sustained_current_peaks.py`, no other reference found) | A / D | 0.5 |
| M549 | F01 hottest/coldest tie policy: unique, tied and fractional time, elapsed-time weights, freshness; known-answer test (4 equal probes: unique 0, tied 100 %, fractional 25 % each) | B | 1.5 |
| M550 | F05 + N07: temperature and freshness at the native power-peak timestamp; peak-current temperature kept for A / C-rate views | B | 3.5 |
| M551 | N01 energy-packet size and boundary censoring; N02 5/10/30/60/120 s power-duration profile. Stratify by logger cadence (B6 still failed). Known-answer check against the audit's p95 table and 0.479 % sub-1 Wh energy share | C | 4.5 |
| M552 | N13 direct thesis test (see below) | C | 2-3 |
| M553 | N06 common-support estimator bridge, F17 (2 drives recoverable under alternative alignment, as a named sensitivity, published estimator unchanged), N12 block-secant SoC scale as sensitivity (CAP_KWH unchanged) | C | 4 |
| M554 | N05 signal-validity registry (all-zero BMS 12 V = unavailable, raw zeros preserved) | A/B | 0.5 |
| M555 | After the engine-on migration ends: F08/F09 follow-ups, N03 orthogonal thermal-demand state, N08 channel-dependency graph | C | 5.5 |

## Findings (F01-F21), validity and repo locations at M545

F01 agree, `compute_summary_arrays.py:4242-4243` argmax/argmin | F02 agree, jsx:7506 | F03 agree, jsx:~12863 (CI half-width as bound)
F04 agree, jsx:~12855 | F05 agree, jsx:~3828 admits not co-timed | F06 agree, jsx:12341 | F07 agree, jsx:11990
F08 agree, jsx:~7475 | F09 agree, jsx:~6139, ~12120 | F10 agree, jsx:~3734, 3759 | F11 agree, jsx:11951
F12 agree, jsx:12823 | F13 agree, jsx:~12684 | F14 agree, jsx:~12882, ~13366 | F15 agree, deprecate
F16 agree, jsx:2891 | F17 partly (2 drives, ~1.8 kWh; null reasons not checked) | F18 agree, jsx:3854, 3862
F19 agree, jsx:~12030 | F20 partly (STATE.md current, overview.md stale) | F21 agree, jsx:~12804

## New items

Adopt: N01, N02, N05, N06, N07, N08, N12, N03 (last, high merge risk with the engine-on migration).
Parked (low thesis value, nothing blocked): N04 (rail tracking), N09 (unlogged-trip sensitivity), N10 (tail concentration).
N11 (claim ledger): register retired M301; needs Andrii. Proposal: short frozen list of primary estimands in the article
spec plus a multiplicity rule (Holm or FDR) applied to that list only; everything else labelled exploratory.

### N13 (added by this triage; gap the audit missed)
Direct test of the thesis (HV battery = power buffer, not energy reservoir): per-drive reported-SoC excursion and energy
cycled relative to the assumed window, and how often the window is used up. Report twice: reference-free (reported SoC
points, Ah) and at the assumed 2.1 kWh (`CAP_KWH`, verified:false, not changed). Depends on the N01/N02 kernels.
Needs pre-registered spec, blind audit, Director decision.

### Standing caveat (not a task)
May-October trends are confounded with season. Trigger: on the first winter ingestion re-run the health-trend and seasonal
blocks and check that no sign or interval status flips.

## Not adopted
Fixed 2000 kg regen mass (different estimand from `regenDisplayV2`); the audit's Huber/week-bootstrap model as a replacement
health model (post hoc, design condition number ~160; cite as a limit beside the M477 procedure statement); splitting the
18k-line module before the `MIGRATION.md` reproduction test passes; narrative UI options B and C before wording is fixed.

## Audit results: how to use them
Own script-written blocks (known-answer check against the audit): power-duration (N02), sub-1 Wh packets (N01),
SoC-secant ~5.0 Ah vs 4.893 Ah (N12), short 4-way weighting bridge (pooled per-km vs per-trip).
Cite as external corroboration only: 0.106 % energy agreement (N06 is the internal version), +0.46 % distance agreement,
98.9 vs 97.5 rotating hours at rpm > 400 (supports the M545/M546 rule), regen episode table (the 110 % at 90+ km/h,
41 events, shows the balance does not close; never clip it or quote it as an efficiency).

## Wording to enforce (language_gate rules, old wording added with ledger id)
reported BMS SoC; commanded torque; reference-scaled turnover; a bound comes from the CI endpoint, the half-width is
precision only; "consistent with ... under the declared screen", never always / confirmed / immune / independent sensor;
model scenario, never physical bound; "Exposure scenarios", not "Capacity fade".
