# M398 spec (pre-registered before the code): attributed re-pin of the GTR closure per-drive pin after recalibration drift

Follows the Director's M388 follow-up ("replace these recurring manual re-pins with an explicit gate mechanism ... compare against a hybrid run (pre-recalibration master rows), require exact identity there, report the recalibration drift separately against a tolerance").
Scope: the previous-ID identity gate of `tools/gtr_closure_diag.py --ingest` (stage `gtr_closure_refresh`, M377c). No estimator, master or payload change; a clean ingestion without drift behaves exactly as before.

## Problem (evidence)
At M376 and M388 the identity check STOPPED the ingestion (previous closure IDs differ from the pinned file at the 1e-5 level) and a one-time manual re-pin by Director ruling was needed ("M388 only; a third occurrence is not approved by precedent").
A clean-room replay of the M388 ingestion with today's code (scratch worktree at the pre-M388 commit, today's code overlaid) stops at the same gate with the same counts (g2t 65, trac 74, b2t 69, g2b_model 71, excess 63 drives changed): the next real ingestion will stall there unless a ruling is obtained again.
Cause: any new data moves the corpus offset by about 0.001 A (M391: 2.8 % of the CI half-width), which rewrites the offset-dependent master columns (`RECAL_COLS`) of pre-existing rows; the closure rows of previous IDs are functions of those columns, so they move by up to about 1e-4.

## Rule (fixed, not tuned)
On an identity drift in `--ingest` mode (and only then; no `--repin-reason`), the diagnostic runs an ATTRIBUTION and either re-pins automatically or STOPs. All of the following must hold, otherwise STOP exactly as today (no automatic action):
1. **Pin belongs to the committed master:** the pin record's `master` MD5 equals the MD5 of `git HEAD:drive_master.csv` (the pre-ingestion master). Otherwise STOP (the pin and the baseline disagree).
2. **Inputs differ only in the recalibration columns:** for the previous IDs, the pre-ingestion master rows (`git HEAD:drive_master.csv`) and the current master rows differ only in `recal_gate.RECAL_COLS`; any other changed column STOPs (independent of the ingest_core gate that enforces the same).
3. **Hybrid run reproduces the pin EXACTLY:** the closure rows of the previous IDs are recomputed with the current code from the PRE-ingestion master rows (same raw originals, same flags) and must equal the pinned file at the same 1e-5 rule as the identity check. Any difference STOPs (code, raw or provenance drift is not recalibration drift).
4. **Drift is small:** between the current rows and the pin, per column maxAbs <= 1e-3 and relative column-sum change <= 1e-3 (the M388 observation was 1.3e-4 and 6.1e-5; headroom about 8x and 16x; chosen once, recorded, not tuned). Larger drift STOPs for a Director ruling.
When all hold: the drift report (`analyses/M377c_identity_drift.json`, as today) is written with an `attribution` section (hybrid identity exact, changed columns, tolerances, magnitudes); the previous IDs' outputs on the new master become the new pin (file `analyses/closure_baselines/perdrive_<n>drives_recal_<master md5 first 8>.csv`, unique per master so no earlier pin file is overwritten;
the record keeps `repinnedFrom`, `repinReason = 'auto (M398): ...'`, the evidence) and the stage continues. The manual `--repin-reason` path is unchanged (Director override). Identity stays exact (1e-5) against the new pin on later runs.

## Wording / disclosure
"closure drift attributed to the recalibrated offset columns (hybrid run reproduces the pin exactly); re-pinned automatically". The CHANGELOG entry of every ingestion that triggers it quotes the evidence block (changed columns, magnitudes). Never "corrected". A recalibration HARD flag still requires its own acknowledgement at ingest_core (unchanged).

## Gates
Known-answer tests (tests/synthetic/test_closure_attribution.py): exact identity -> no action; drift + all conditions -> re-pin written, record updated, evidence returned; each condition failing separately (pin master mismatch, a non-recalibration column changed, hybrid not exact, drift beyond tolerance) -> STOP with no pin written; unique file naming; `--repin-reason` path unchanged.
Integration: the clean-room replay (scratch worktree) resumes at `gtr_closure_refresh` and passes the gate automatically; the final replay payload and master are compared with the merged M388 state.
Blind audit reproduces the hybrid identity and the tolerance logic independently; Director ruling (this supersedes the M388 "no precedent" note by a stated mechanism).

## Director ruling (M398, "revise" then closed)
Design accepted (fails safe: a hybrid run that deviates from the pin STOPs). Required and implemented before it became the standing gate: (1) condition 3 independently recomputed in a fresh process by the analytical-auditor (292/292 IDs, max abs diff 0.0 vs the old pin from the pre-ingestion master rows and the sha256-verified originals) with negative controls (one perturbed non-recalibration input breaks identity; the current master rows reproduce the new pin exactly and differ from the old pin by up to 1.3e-4); (2) a drifting non-numeric closure column STOPs; (3) cumulative drift against the ORIGINAL pin (`originalPin` in the record) is bounded by the same 1e-3 / 1e-3 and recorded (`cumulativeVsOriginalPin`), a larger cumulative drift STOPs for a Director ruling. nDrivesChanged is descriptive only and always quoted "at >1e-5 on 5-dp rounded values". Manual `--repin-reason` stays a Director-only override. This supersedes the M388 "no precedent" note by a stated mechanism.
