# M350 spec: NaN-offset idiom removed from the remaining GTR scripts (follow-up of M349)
Tooling change (Sonnet, medium; no new estimand, no payload splice).
Scope: `speed_split.py`, `crossval_gtr.py`, `sensitivity_gtr.py`, `simultaneity_gtr.py` use `fuel_recon.corpus_offset` / `resolve_offset` (fail-closed) instead of `float(x or 0.0)`.
Why now: `speed_split.py` deliberately replicated fuel_recon's NaN pass-through (M255) to match the then-shipped fuel_recon_master.csv; after M349 that replication fails validation against the repaired master (verified: old idiom 0/2 matched on the two Aug 13 drives, resolve_offset 2/2), so it had to move with fuel_recon.
Not changed: `tools/gtr_closure_diag.py` (pre-registered M336 result; it skips NaN-offset drives by design: disclosed inconsistency), any payload block. The payload blocks `generatorTractionRecon.{speedSplit,sensitivity,simultaneity,crossval}` are carried forward from earlier runs (speedSplit: 181 drives vs 261 now); refreshing them would change published blocks and is a separate decision (needs its own spec, control and sign-off).
Tests: `tests/synthetic/test_nan_offset_pattern.py` (source scan for the idiom + helper contract); `speed_split.py` full run validates 261/261 drives against the repaired fuel_recon_master.csv (max diff 0.0000).
Evidence: `analyses/M350_result.json` (script-written).
