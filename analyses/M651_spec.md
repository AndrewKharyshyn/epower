# M651 spec Rev 1: P-07 generic carry of previous leaves (tooling, gate T)

Tooling only; no estimator or figure changes. Control build required by the backlog: done (below).

## Change
`tools/ingest_core.py` `carry_lost_leaves(arrays, prev, rules)` runs after `carry_forward` in `step4_arrays`. Every subtree of the previous payload that the builder did not produce is copied into the fresh payload at its highest missing dict node, EXCEPT (deny-list): `_artifactStamps` (the stamp stages own hash, time and basis), any path with a list index (elements cannot be matched by position after a rebuild), and leaves covered by a declared `analyses/leaf_guard_rules.json` rule (expected losses). A present leaf keeps the fresh value. The carried node paths are reported (`carried_leaf_nodes_stale_until_stage_runs`), never stored in the arrays. `NESTED_CARRIED` stays (the generic carry subsumes it; no removal without a refit control).

## Control build (no new drive, `tools/p07_control_build.py`, results `analyses/M651_control_report.json`)
The builder is called as `step4_arrays` calls it (raw_only, `recompute_m119v2=False`, `recompute_energy_mc=True`) and written to a temp path. Lost previous leaves (of 299,183): as built 256,024 (86 top-level keys owned by downstream stages); after the former carry 1,189; after the generic carry 971, all of them `_artifactStamps` (658, re-issued by the stamp stages), `records` list elements (269; the list length differs, 42 vs 39) and `engineStartsByType` list elements (44). The generic carry removes the dict-path class (socHysteresis.startRatioClustered, seasonalLife.hotTail sample occupancy, meta.intakeAir and dates, crawlStopGo.phaseEnergy.blindAudit): 218 leaves in 9 nodes.

## Not done (stated)
- The four stages that restore spliced leaves (`post_splices`, 77, 82, 83) are NOT removed: their idempotent restores stay as the second line, and the list-indexed and stamp classes still depend on them. A removal needs a full ingestion run.
- The early `leaf_guard_early` stays report-only for the same reason.
- No claim that a full ingestion no longer stops at leaf_guard: the build shows the dict-path class carried; the list and stamp classes remain.

## Acceptance
`tests/synthetic/test_m651_carry_leaves.py` (known answer for the carry and the deny-list) and the control report (losses 1,189 to 971, remaining classes limited to stamps, `records`, `engineStartsByType`); `release_check.py` green.
