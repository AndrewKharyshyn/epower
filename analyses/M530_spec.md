# M530 spec (Rev 1, DRAFT for Director review): three session-ledger notes that read "corpus now N drives" (M528 A3 follow-up); text only

Status: PRE-REGISTERED DRAFT, 2026-10-28, written before any edit. Owner: Andrii (chat, 2026-10-28: "continue"). Origin: M528 A3 sweep (`analyses/M528_a3_sweep.json`, out-of-scope hits). Scope: THREE string leaves in `summary_config.json` (`sessionGroups[17,18,19].note`); wording only; NO numeric field (`drives`, `km`), NO key, NO recompute, NO payload change.

## 1. Facts (read before this spec)

- Hand-curated ledger rows of the dashboard section "Sessions (grouped by phase)" (CLAUDE.md "Session ledgers"). Each of the three notes ends "Extends the observation window to Jul 21 / Jul 22 / Jul 23; corpus now 167 / 173 / 180 drives / 4,644.7 km / 712.02 kWh gross throughput / GTC 339.06 / 341.31 / 358.49." The statement was true on that date and reads as present tense today (the corpus is 606 drives).
- The same config scan (patterns "corpus now", "now N drives", "total now", "to N drives") finds 29 phrase hits: only these three use the present-tense "corpus now". The other hits are batch-ledger phrasing ("this batch lifts the study to N drives") and the `sessions[28]` reconstruction note (a dated statement about 186 versus a 194-drive master); they are dated by construction and NOT changed.
- Rendered in 5 dumps (the grouped-sessions panel). `sessionLedgerAudit` (release_check) compares the ledger rows' numeric fields with the master; it does not parse the note text (to be confirmed by running the gate: A1).
- Neither the quoted cumulative figures nor the dates change; they are the ledger's own dated values.

## 2. Change

For the three notes: "; corpus now N drives / ..." -> "; corpus at that date: N drives / ...". Nothing else in the notes changes. Rule `M530-ledger-corpus-now` (config + dom scope): forbids "corpus now" followed by a drive count in ledger text; 0 hits on the whole post-edit config and on the rendered dumps; the batch-ledger phrase "lifts the study to N drives" is not flagged.

## 3. Acceptance and falsification

- A1 byte-level: the config differs from HEAD only in those three strings (deep diff = exactly `sessionGroups[17,18,19].note`); every numeric field, key, `sessions` row, `_artifactStamps` / `stampLineage` byte-identical; `verify_declared` output identical before and after (the notes are in no declared configSection: to be checked by script); `release_check` including `sessionLedgerAudit` PASSED.
- A2 rendered diff: the tab dumps change ONLY in those three sentences (5 dumps); the replaced text is exactly "now" -> "at that date:".
- A3 the M528 A3 sweep re-run: the three config hits disappear; the remaining hits are unchanged (listed in `analyses/M530_a3_sweep.json`).
- Negative controls: the rule fires on "corpus now 167 drives" and not on "this batch lifts the study to 247 drives"; planted extra change caught; idempotent splice.
- Stop: any need to change a number; any ledger row whose date cannot be determined.

## 4. Language

"at that date", "as of the end of that observation window"; not "corrected", "up to date", "stale".

## 5. Gates and process

py_compile, build_html, validate_jsdom, dump_tabs THEN semantic_gate, new test in CI, release_check (sessionLedgerAudit included), full CI unit list locally (background), CHANGELOG M530 (spec SHA-256 before the edit), Director decision, dashboard change rule (the rendered text changes: SendUserFile render + commit with sources). Merge ONLY when the PR run is `completed` with conclusion `success` on the current head (checked in the same command). No new blind audit (text-only, three leaves, A3 script re-run); no article figure; no Andrii sign-off.

## 6. Questions for the Director

Q1 Is "corpus at that date: N drives" the right tense fix, or should the clause be dropped? Q2 Do the dated `sessions[28]` and batch phrases stay? Q3 Is the rendered change a content change needing the dashboard rule (yes expected)?

## 7. Rev 2 (2026-10-28): Director review (verdict "accept", minor revisions, no re-review). Rev 1 SHA-256 recorded before the edit: 5aec41409eaf1df4.

- **Rulings.** Q1: keep the clause (it records the corpus growth path); preferred wording names the date: "corpus as of Jul 21: N drives / ..." (Jul 22, Jul 23 for the other rows); the CHANGELOG states that the figures in the notes are the ledger's own dated values and were NOT re-verified against the master (sessionLedgerAudit checks only numeric fields). Q2: `this batch lifts the study to N drives` and `sessions[28]` stay. Q3: rendered text changes in 5 dumps: content change under the dashboard rule (SendUserFile render plus commit with sources; no S.* binding changes; stated in the one-line note).
- **Additions.** A1: confirm by grep in release_check / tools and by gate output that `sessionLedgerAudit` and `verify_declared` do not parse note text. A2: the dump diff shows exactly 3 changed sentences (counted by script), not only 5 dumps. A3: the sweep re-run is written to `analyses/M530_a3_sweep.json`. Negative control: the generator template in `tools/extend_session_ledgers.py` does not emit "corpus now" (test assertion, so a later template edit is caught). The rule stays a context rule ("corpus now" + drive count in ledger text) so it does not fire on future live text bound to S.*; the old wording enters as rule `M530-ledger-corpus-now`.
- **No sign-off.** The Session-ledgers owner decision covers coverage and numeric agreement; a tense change on dated notes leaves both untouched. Mentioned in the PR body and the CHANGELOG so Andrii sees it. No blind audit (text only, three leaves, A3 script).
