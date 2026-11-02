# M565 spec Rev 1 (2026-11-02, before any code): R2 sibling rule for the channel-dependency audit (M557 follow-up)

Status: PRE-REGISTERED DRAFT for Director review. Tier B (tooling rule with known answers; no payload number, no ledger status changes). Parent: `analyses/M557_spec.md` Rev 1-3, `tools/dependency_audit.py`, `channel_dependency_graph.json`, `independence_claims.json`.

## 1. Problem
M557 rule R2 classifies a (target, validator) pair from the graph only. Two `model_output` nodes that are nested specifications fitted to the same derived response (E6: `power_fade_trend` vs `resistance_vreg_trend`; C6: `power_fade_s1` vs `power_fade_s0_control`) share data ancestors only through the response's inputs, so R2 returns `shared_raw_input`. The blind audit and the Director settled them as `model_adequacy`; the payload carries `computedClass` and `settledClass` side by side and records the E6 expectation as NOT MET. The workaround is a hand-written `settledClass`; the rule should produce the class itself.

## 2. Rule (new, R2b)
A node of kind `model_output` may declare `responseNode`: the id of the derived node it is fitted to (a `derived` parent of that node). After the circularity checks of `classify` (a validator that is an ancestor or descendant of the target, or the target itself, stays `circular`) and before the shared-ancestor test: if the target and EVERY validator are `model_output` nodes that declare the same `responseNode`, the class is `model_adequacy` (sibling model specifications of one response; shared inputs are the response's inputs and say nothing about independent evidence). The declaration is explicit because the graph alone cannot tell sibling specifications of one response (E6, C6) from a control that re-estimates the same derived quantity on perturbed data (C2: `cadence_thinning_estimate` vs `cadence_slow_to_slower` share the derived `gross_throughput_kwh` and must stay `shared_raw_input`).
Schema check (added to `validate_graph`): `responseNode` is allowed on `model_output` nodes only, must name an existing node of kind `derived`, and that node must be a parent of the declaring node.
Declarations added (the only edits to the frozen graph, before / after hashes in `analyses/M565_graph_edits.json`): `responseNode: "vreg_r_proxy"` on `power_fade_trend`, `resistance_vreg_trend`, `power_fade_s1`, `power_fade_s0_control`, `power_fade_temp_specs`, `serial_trend_resistance` (every model fitted to the resistance proxy). No claim, class, expectation or `settled*` field is edited.

## 3. Pre-registered expectations (before the run)
- Computed classes: E6 and C6 change from `shared_raw_input` to `model_adequacy` (equal to their settled class); the other 11 claims (E1-E5, C1-C5, C7) keep their current computed class exactly; in particular C2, C3 (thinning controls), E2 (different algorithm, same channels) and C7 (`circular`) are unchanged.
- `settledClass` and `settledRelation` stay in the payload (audit trail) and now equal `computedClass` for E6 / C6; `preRegisteredNotMet` still lists E6 (the pre-registered expectation was `shared_raw_input`; it is not rewritten).
- Payload diff: only the computed class fields (and counts) of E6, C6, the class counts, the graph hash and the rule text; no other leaf.

## 4. Known answers (unit tests)
- KC1 two model_output siblings with the same `responseNode` (shared derived parent plus a shared raw input) -> `model_adequacy`.
- KC2 two model_output siblings sharing the same derived parent but WITHOUT a common `responseNode` declaration -> `shared_raw_input` (the C2 pattern).
- KC3 siblings with different `responseNode` -> `shared_raw_input`.
- KC4 a validator that is a child (or parent) of the target with the same `responseNode` -> still `circular` / the existing `model_adequacy` branch (the circular checks run first).
- KC5 target model_output and validator a raw channel node with a `responseNode` on the target -> unchanged (`shared_raw_input`); `responseNode` on a non-model_output node, on a non-derived node, or naming a non-parent -> schema error.
- KC6 mixed validator list (one sibling, one non-sibling) -> not `model_adequacy`.
- KC7 (real registry, hard gate) the 13 computed classes equal section 3.

## 5. Escalation
A0: `drive_master.csv` MD5 and ML16 unchanged; no ledger `validationStatus` changes; payload diff as section 3. Blind audit not repeated: the auditor's class for E6 and C6 (analyses/M557_audit_result.json) was obtained blind and is what the rule reproduces; the check is KC7 against that record. Escalate to the Director if any other claim's computed class changes or if KC7 fails. A4: no article figure.

## 6. Questions for the Director
Q1 Is an explicit `responseNode` declaration the right way to separate nested specifications from re-estimation controls, or should the rule use the existing `sameDerivationAs`-style field? Q2 Should C7 (decision rule on the spread of the specification slopes) stay `circular`? Q3 Anything else required before the PR?

## 7. Rev 2 (2026-11-02): Director review (verdict revise); incorporated. Rev 1 SHA-256 before this edit: a517081d340aa9e37817d9b669172e69a5d20510afbd5229494af5919625c836
Where this section and sections 1-6 differ, this section governs.
- R1 (what changes, per field). For ledger checks `computedClass` and `relation` are the same value: E6 changes from `shared_raw_input` to `model_adequacy` in both. For controls `relation` carries the class and `computedClass` stays `negative_control` / `decision_rule`: C6 changes only `relation` (to `model_adequacy`); C2, C3, C5, C7 change nothing (C7 relation `circular`, computedClass `decision_rule`). Section 3's statement that C6's computed class changes is superseded by this.
- R2 (full pre-registered payload diff). E6: `computedClass`, `relation`, `settledClass` unchanged (`model_adequacy`, now equal to computedClass), the E6 trigger "declared shared_raw_input differs from computed model_adequacy" and the trigger "computed model_adequacy differs from the pre-registered shared_raw_input" are ADDED (2 new triggers; the M557 A3 rule escalates triggers, this milestone is that escalation: both are expected and recorded); `settledOverrides` loses E6 (computed equals settled) and keeps C6 (settledRelation); C6 `relation`; `classCounts` (computed classes of ledger checks and controls: shared_raw_input -1, model_adequacy +1); `graphSha256`; `rule.classes` text (R2b added); `blindAudit.note`. `preRegisteredNotMet` still lists E6 (the pre-registered expectation stays recorded as not met; it is not reworded as met). Any other diff escalates to the Director.
- R3 (ancestors). R2b returns the shared data and unverified-constant ancestors exactly as the shared-ancestor branch does (it changes the class, not the evidence): `sharedDataAncestors` and `ancestorDisagreement` for E6 and C6 are unchanged. `pack_temp` is a shared covariate and not an input of `vreg_r_proxy`; the wording is "nested specifications fitted to the same response proxy", never "shared inputs are the response's inputs".
- R4 (added known answers). KC8 `sameDerivationAs` plus the same `responseNode` -> `coding_check_only` (existing check first). KC9 `responseNode` declared on one side only -> `shared_raw_input`. KC10 several validators that are all siblings of the target -> `model_adequacy`. KC11 a `responseNode` naming a derived node that is not a parent of the declaring node -> schema error. KC12 shared data ancestors are returned unchanged by R2b.
- R5 (KC7 strengthened). KC7 asserts `relation` and `computedClass` for all 13 claims against the section-3 table (with R1) and the exact trigger set, and checks `analyses/M557_audit_result.json` by sha256 against the value recorded in the payload.
- R6 (hashes). Graph before / after SHA-256 in `analyses/M565_graph_edits.json` and appended to `analyses/M557_frozen_hashes.txt`; the claims file hash is unchanged (no edit to `independence_claims.json`).
- R7 (audit). A blind re-audit is waived (the rule reproduces classes obtained blind and no new class appears outside E6 / C6). A short targeted Sonnet review of the `classify()` diff and the known answers (rule order and leakage only) is required before the PR.
- Q1: explicit `responseNode`, not `sameDerivationAs` (same derivation = a coding check; reusing it would conflate the two). Q2: C7 stays `decision_rule` / `circular`. Q3: this section.
