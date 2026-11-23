# M756 spec addendum: rerun of the M751 heat-soak gap sensitivity on the M755 ambient basis

Dated 2026-11-23. Committed BEFORE the rerun is executed. Author: main session (Sonnet). Owner: "Yes, start M751" (rerun, answering the next-step question after M755). Parent spec: `analyses/M751_spec.md` Rev 2 (all sections and rulings 9.1 to 9.8 stay in force, unchanged).

## 1. What changes and why
- M751 was computed on the former ambient basis: its V0 control reproduced the then-published `heatSoakCarryover` block, which skipped the 66 plain-number ambient entries (11 to 22 September 2026; 593 of 706 pairs with ambient). M755 (merged, PR 430) changed the published block to the shared-reader basis (650 of 706 pairs with ambient; tau 11.03 -> 11.10 h). The M751 conclusions therefore carry the same omission and were registered as to be rerun on the fixed basis (`docs/open_items.md`, CHANGELOG M755).
- The only change: the ambient of a pair is read through `tools/ambient_protocol.mean_reading` (the tool already does this since M755). Nothing else in the design moves: same pairs, same classes S/D/U/X, same sets A/B/C/C1, same estimands E0 to E4, same decision rules (5 pp, tau band [0.80, 1.25] on k, floor 20 pairs and 10 days), same clustering, seed 42, 4000 draws, same registered inputs (master MD5 d514d6009d6d9a0a168ad4fb09b9bb98; M729 gap table sha256 d1d3f8e9da732e7c58212c3bcf5718e05304a186df4f45e567d8799c704d159f).
- The tool file hash differs from the M751 record (the M755 reader edit); the new hash is recorded in the result. The M751 result files stay as the record of the former basis; the rerun writes to `analyses/M756_rerun/` (files keep their M751_ names inside it).

## 2. Control and acceptance
- V0 must reproduce the CURRENT published block (650 pairs with ambient, tau 11.10 h) leaf by leaf; a mismatch stops the run and nothing is interpreted.
- Report side by side, per script, the M751 value and the rerun value for: pairs with ambient per set, the E2 shifts A-B and A-C per supported bin with intervals, the tau and k results, the overall wording. A change of any decision (material / small / not distinguishable) for any bin or for tau, or a change of the overall wording, goes to the Director (the pre-stated escalation); no decision is tuned.
- No payload, dashboard or published figure changes in this milestone (parent section 1). Blind audit (Sonnet): reproduce the changed E2 bins and tau for A and B from the master, raw files, `summary_config.json` and the M729 table, not the tool. Director decision. CHANGELOG M756 with pins. Merge only on all-green CI.

## 3. Falsification and language
- Unchanged from the parent: the rerun can reverse the M751 wording ("sensitive to unlogged driving (lower bound)") if the supported bins or tau stop being material under B and C. Wording stays "estimated, lower bound, a sensitivity of the published carryover, never a correction"; "unlogged" means no OBD record.
