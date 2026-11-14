# M649 spec Rev 1: P-03 move gates earlier (tooling, gate T, no new estimate)

Scope: self-audit backlog item P-03. Tooling only; no payload value, estimator or dashboard figure changes. Owner decisions D-01..D-08 not touched.

## Changes
1. M321 acknowledgement stop: `tools/m321_ladder_monitor.py update` exits 1 after writing the report-only monitor block when status is warn-newspec and no valid acknowledgement exists (`ack_failure`, the same predicate as `gate()`), so the ingestion halts at stage `m321_ladder_monitor` and not at the final release gate. All other `gate()` checks stay in `release_check.py`.
2. Estimator gate candidate: `ingest_core.estimator_gate_keep` writes the freshly computed arrays to `runs/ingest_core_<ts>/candidate_summary_arrays.json` (not canonical) before re-raising the `Gate`; `summary_arrays.json` is still restored from the backup.
3. Shared S1 fidelity: new stage `s1_fidelity` (`tools/s1_fidelity.py`) after `powerfade_equivalence` (it needs the density sidecar that stage writes) and before `powerfade_temperature_specs`: point slope (M578 months-scale conversion), n, nDays and temperature coefficient of the replicated T0 design must equal the published S1 reference. Point part only; the interval comparisons stay in the stages that compute intervals. The per-stage checks are not removed.
4. Language/semantic gate at ingestion: stages `dump_tabs` and `semantic_gate` directly after `build_html`; `release_check.py` keeps its clean-environment run.
5. Early lost-leaf report: stage `leaf_guard_early` right after `ingest_core` with `--report-only` (non-blocking). DEVIATION from the backlog wording ("run leaf_guard right after ingest_core"): the splice stages (`post_splices`, 77, 82, 83) restore leaves the arrays rebuild drops, so a blocking guard there would stop every ingestion; P-07 (carry previous leaves in the builder) is what makes it blocking. The final `leaf_guard` stays the gate.

## Acceptance
`tests/synthetic/test_m649_early_gates.py`: each gate fires at the earlier stage in a synthetic failure (unacknowledged W2/W3, stopped estimator gate keeps a candidate, each S1 point mismatch, stage order, leaf_guard report-only versus gate). New stages are `verified:false` until a first full ingestion. `tools/stage_order.py` lint and `release_check.py` stay green.
