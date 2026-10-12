# M423 spec (Rev 0): ingestion refresh of the exposureBasis block (found by the M422 rehearsal)

Status: tooling milestone; no figure changes on the committed corpus. Branch `claude/next-milestone` from `main` (7d314ec, M422). Origin: the M422 rehearsal ingestion of the 20 pending drives stopped in `restamp_ingest` ("stale stamp(s) without a policy entry: ['exposureBasis']") and showed the cause: the block `exposureBasis` (M415) was spliced once from two control builds; its populations, the rated-over-legacy factor, the legacy-basis disclosure values, the rated point beside the Monte Carlo and the primary exposure depend on the corpus, and no stage refreshed them. Owner direction 2026-10-12/13: "exposureBasis then speedups".

## Design (no second arrays build)
The dashboard reads from `exposureBasis.legacy` only `meta.gtcSum`, `meta.fceSum` and `metricConvention.efcStandard` (Provenance / ledger tag lines); the other stored legacy values (cycleByType, cycleBySpeed, cycleCumulativeLast, C-rate axes and reference lines) are disclosure values kept in the payload. All of them are recomputed here without a legacy-basis control build:
- from `drive_master.csv` alone with the released builders on the legacy exposure frame (`tools/exposure_frame.exposure_frame(dm, "legacy2p1kWh")`): `_metric_convention`, `category_A` (cycleByType, cycleCumulative), `_crate_axes`, `_crate_ref_lines`, the meta sums;
- cycleBySpeed legacy rows are DERIVED from the rated payload rows (rate = kWh / CAP_KWH / km x 100 from the stored one-decimal kWh and km; the raw-pass accumulators are not re-run, so a rate may in principle differ in the last digit from the unrounded builder value; the M415 values are reproduced exactly on the committed corpus);
- the rated side is the payload itself (built on the rated basis); populations and the factor come from `drive_master.csv` and the Ah sidecar; `windowFractionBand` and `primaryExposure` from the refreshed `capacityBasis`;
- the block is assembled by `tools/exposure_splice.build_block` (the M415 code).
`tools/exposure_basis_refresh.py` writes only `/exposureBasis` and `/_artifactStamps/exposureBasis`; stage `exposure_basis_refresh` after `capacity_basis` and before `stamp_basis`; `restamp_ingest` STAMP_POLICY gets the key (regen).

## Known-answer checks
1. On the committed corpus (554 drives) the refreshed block equals the M415 block in every key except the provenance text (`tests/synthetic/test_exposure_basis_refresh.py`).
2. On the 574-drive rehearsal state: populations 540 -> 560 drives (109 -> 113 days), legacy sums 747.1 -> 779.0 GTC, and the factor identity rated payload sum / legacy sum = 1.1587 (equal to the sidecar-based factor).
3. Mutation: a master without its last 20 rows changes the legacy sums and rows; the splice writes only the block and the stamp; a second refresh on the same corpus changes only the stamp.

## Limits
The derived cycleBySpeed rows rest on one-decimal stored values (stated in the tool docstring); the legacy disclosure values stay reference-only (no consumer other than the three displayed numbers). No Director wording ruling is needed (no text or figure changes; the three displayed legacy numbers are unchanged on the committed corpus).

## Rev 1 note
The cycleByType / cycleCumulative legacy values come from helpers extracted unchanged from `category_A` (`_category_a_frames`, `_cycle_by_type`, `_cycle_cumulative_ledgers`); the whole `category_A` takes about 85 s and its other outputs are not needed. `category_A` output is identical before and after the extraction (all keys, canonical JSON, committed master).
