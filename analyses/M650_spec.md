# M650 spec Rev 1: P-04 declare stage dependencies at payload-key granularity (tooling, gate T)

Tooling only; no payload value or figure changes.

## Changes
1. `tools/stage_order.py`: stages may declare `reads` / `writes` tokens (`arrays:<top-level payload key>` or a repository file). A reader must come after every declared writer (`writes`, or `outputs` for file tokens) unless it waives the token in `reads_prior_state` (violation `declared_read_before_write`). Stamping-final rule: stages marked `stamps: true` (stamp_basis, restamp_ingest, stamp_dependencies) end the payload-writing part of the run; a later stage that lists `summary_arrays.json` in `outputs` or an `arrays:` token in `writes` is a violation (`payload_write_after_stamp`), so the stamps describe the final payload.
2. Declarations added: comparison_cube writes comparisonCube; urban_week_block and urban_contrast_balance read it; dump_tabs, jsdom read xtrail_dashboard.html; semantic_gate reads the tab dump; m483_wording_splice / m432_refresh write their blocks.
3. `m483_wording_splice` and `m432_refresh` moved to before `stamp_basis` (they wrote the payload after the stamps).
4. Lint speed: string constants of each source file are parsed once per process (cache keyed by mtime and size); the full lint went from about 204 s to about 130 s.

## Not done (stated)
Fragment files and a 3-worker pool for independent sidecars (the "then" part of P-04) are a separate step. Declarations exist only where an order defect was found or a swap named by the audit; the rest of the 98 stages keep the file-level inference and `needs`.

## Acceptance
`tests/synthetic/test_m650_stage_declarations.py`: the swaps comparison_cube/urban_week_block, build_html/jsdom (and the other dashboard readers) are rejected; moving either content stage after the stamping stages is rejected; the shipped list passes; `test_stage_order.py` unchanged and green.
