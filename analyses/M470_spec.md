# M470 spec: language-gate speed-up with exactly equal decisions (audit 2026-10-21, "Adoption order: first")

Audit measurement (not a full-pipeline claim): rule evaluation of 122 strings 4.249 -> 0.723 s (5.88x) with identical ordered hit lists; the live payload holds 41,001 string values but 5,191 distinct strings.

Change (`language_gate.py` only; no rule, no wording, no threshold changes):
- `prepare(text)` normalises a text ONCE (norm, whitespace-stripped norm, tokens) and every rule decides on that triple (`Rule.hits_prepared`); `Rule.hits(text)` stays and calls it.
- Per-rule data (phrase regex and stripped phrase, ctx term words and near set) is computed in `Rule.__init__`.
- `scan_text` caches the hit tuple per distinct text for the shared `RULES` list and returns a copy; a caller-supplied rule list is never cached. `scan_payload` still appends per string occurrence, so duplicate locations are reported exactly as before.

Equivalence (`tests/synthetic/test_language_gate_equiv.py`, added to ci.yml): the oracle is the former implementation (`hit_phrase`, `norm`+regex, `hit_ctx`, unchanged module functions). Ordered rule-hit lists are identical on a deterministic quarter of the distinct live payload/config strings, the JSX code and comment text, six rendered tab dumps and the fixtures; payload location reports with duplicates are identical; cached results are copies. Measured on that corpus: former 26.5 s, now 5.9 s (4.5x, cold single pass); a measurement of this test, not of the pipeline.
Acceptance: all `test_m*_wording`, `test_language_gate`, `test_trend_facts` pass unchanged; `release_check.py` green; semantic gate A2 output unchanged.
