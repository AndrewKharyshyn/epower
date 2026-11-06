# M505 spec Rev 3 (2026-11-06): re-run of the pre-registered alignment-rule sensitivity of the resistance-proxy trend on the 632-drive master

Status: Rev 3, frozen before the run and before any result of this revision. Amends `analyses/M505_spec.md` Rev 2 (variants A0-A4, designs S0 and S1, estimands, decision rules, verdict rule, multiplicity, wording and hard stops are UNCHANGED unless stated here). Base: `main` at M585 (`1ac2554`), `drive_master.csv` MD5 `1574a8156a36c6ea4ea1dfdaafc7cc72` (632 drives). Trigger: `semantic_gate.py` WARN since M575 ("the live powerFade S1 slope differs from the dated M505 snapshot", 606 drives), named in the ingest-drive skill ("a re-run of M505 on the new corpus is a new milestone"). Owner instruction (Andrii, chat 2026-11-05/06): continue the open items in sequence.

## What was seen before this revision (disclosure)
The Rev 2 result (606 drives, `analyses/M505_result.json`): S0 reading of A1 and A4 depends on the alignment rule, S1 verdicts as in the payload block `vregAlignmentSensitivity`. The live S1 slope on the 632-drive master is known from the payload (`powerFade`, `powerFadeEquivalence.s1`, 279 drives, 102 days). No variant has been computed on the 632-drive corpus.

## Change 1: population
The 632 canonical drives of the master (the raw bytes by `ah_throughput.raw_loader`, 14-digit key identity 1:1 with the manifest, STOP otherwise). The A0 hard stop is unchanged: A0 must reproduce the master column `vreg_R_pack_mohm` on every drive (|diff| <= 1e-9, same missingness). The fidelity targets are read from the payload at run time (`powerFade` S1, n 279, 102 days; `degradationTrends.resistanceVreg` S0).

## Change 2: fidelity comparison is months-scale aware (stated deviation from Rev 2 R4, same estimand)
M505 refits S1/S0 on `months = days / 30.44` (the replicated `_powerfade_cadence_specs.fit`) while the published S1 slope (`powerFadeEquivalence.s1.slope`) and S0 slope come from `degradation_trends._prep` on `days / 30.4375`; the exact 4-decimal (S1) and 3-decimal (S0) equality of Rev 2 held only by rounding coincidence (the same gap as the M499 / M514 fidelity gates, Director ruling M578). The gate now compares the A0 slope with the published slope converted by `MONTH_DAYS / degradation_trends.MONTH_DAYS` (constants imported, never typed), tolerance 5.5e-5 on the unrounded A0 slope (1.1e-4 when only the rounded one is available); n, nDays, the proxy column and everything else stay exact. The Rev 2 file keeps its original fidelity block.

## Change 3: output and snapshot
The result is written to `analyses/M505_result_r3.json` (Rev 2 file kept as the dated 606-drive result); `--splice` replaces the payload block `vregAlignmentSensitivity` (leaf-level, deep-diff, additive pattern: only this key and its stamp change) with a snapshot of the 632-drive run (`snapshot.nDrives`, `a0S1Slope`); the stamp policy stays "carried at its basis" (dated snapshot, no ingestion stage). The sha256 of Rev 2 and Rev 3 are written into the output and the block.

## Unchanged (verbatim)
Variants, the in-process `_asof` replacement with its active-patch sentinel (no multiprocessing), the 4000-draw day-clustered bootstrap (seed 42), the paired and own populations, the verdict labels, the 8 + 5 interval multiplicity statement, the post hoc A1V decomposition (not in the verdict), the allowed wording ("reading unchanged across the five pre-registered alignment rules"; never "robust" or "insensitive to alignment" in general), basis "raw/ = sha256-verified originals (M366)".

## Outputs and tests
`tools/vreg_alignment.py` gets: the scale-aware fidelity comparison (pure helper `fidelity_matches`), an option `--out` (exists) used for Rev 3, spec hashes in the block. Known-answer tests added to the existing M505 test: the scale-aware gate passes the 30.4375-scale published value and rejects an off-by-3e-4 slope, an n mismatch and an nDays mismatch. Blind audit (analytical-auditor): independent reproduction of the S0 and S1 refits of A0 and of at least A1 and A4 from the per-drive proxies in the result plus the master covariates (n, days, slope, day-bootstrap interval), the A0-equals-master check, and the paired shifts; Director decision on the verdict changes. Dashboard: the existing M505 panel (`S.vregAlignmentSensitivity`) re-renders from the new block; Dashboard change rule applies.

## Out of scope
Any change of the production alignment, `_vsag_metrics`, `drive_master.csv`, the cell-spread pairing, the M393/M500 cadence emulation, an ingestion stage, any article figure.
