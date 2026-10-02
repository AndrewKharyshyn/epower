# M326 W0 addendum (committed BEFORE any edit): provenance footer and false literals
Rows: Cs-76, p4.3, p14.11, F01.r3 (done in M325), D-1 (done in M325), F2.22 (text deletion), F34.r3 (text part). Verified on disk 2026-10-02: the jsx no longer contains "no fuel-flow"; the false fuel text lives in the builder/payload (see N1).
Pure wording + generated text; no estimand/number changes. Payload leaf strings are changed by an exact-old-string leaf splice (assert old text; idempotent) AND at their builder source so a regeneration does not revert them.

## Exact replacements
N1 builder compute_summary_arrays.py (~15111) and payload leaves energyPath.unobservable[1].why, seasonalCharts.charts.EnergyPath.data.{all,warm,shoulder}.unobservable[1].why (ledger F2.22, F34.r3, Cs-76, D-S7 text part):
 OLD: "no fuel-rate PID on the great majority of drives; MAF appears on a handful of early logs only, and MAF-derived power is an air-side estimate, not a fuel-energy measurement"
 NEW: "the logged fuel rate and fuel counter are calculated by the logger app (Car Scanner, air-flow based) and are present on a subset of drives; they are not an ECU fuel measurement, so fuel energy in is logged volume x assumed E10 LHV; MAF appears on a handful of early logs only, and MAF-derived power is an air-side estimate; engine brake thermal efficiency is therefore model-derived"
 (No number in the text; the coverage count key is pulled out as p17.13, a separate DATA milestone.)
N2 builder records_rainflow.py:24 and payload leaves records[26].note, records[27].note (p14.11):
 OLD: "Rainflow on the raw SoC trace, 1.0% amplitude floor (twice the PID quantisation step);"
 NEW: "Rainflow on the raw SoC trace, cycles with a range below 1.0 pp dropped (twice the PID quantisation step);"
 Verified: compute_drive_summary_v6.py:865 applies the floor to c[0] of rainflow.extract_cycles, which is the cycle RANGE (rainflow 3.2.0 yields (rng, mean, count, i_start, i_end)), not the amplitude.
N3 builder compute_summary_arrays.py (~5114) and payload leaf rfDodHistogram.methodology (p14.11):
 OLD: "RF_FLOOR_PCT=1.0 amplitude floor"  NEW: "RF_FLOOR_PCT=1.0 cycle-range floor (pp)"   (the builder formats the value with %.1f; only the words change)
N4 xtrail_summary.jsx Methods footer (Data provenance paragraph):
 (a) OLD: "the remainder are early-May logs that predate the full PID set and contribute 0.0 GTC"
     NEW: "the remainder have no integrable energy trace (including early-May logs that predate the full PID set) and are excluded from GTC, not counted as zero"
 (b) OLD: "(1.0%-SoC amplitude floor, twice the PID quantization step, to exclude single-LSB chatter)"
     NEW: "(cycles with a range below {S.rfDodHistogram?.floorPct} pp are dropped, twice the PID quantization step, to exclude single-LSB chatter; {S.rfDodHistogram?.nFilesUsed} SoC traces)"   [bound to payload]
## Language gate (infrastructure, same milestone)
New module language_gate.py (normaliser + matcher + RULES) used by semantic_gate.py check A2: matching per Director rev 2 (NFKC; arrows/hyphens/spaces collapsed; whitespace-stripped form for phrases >= 12 characters; case-insensitive; word-bounded with optional s/es; context rules with a 4-token window and negation allowance; payload string VALUES only; jsx strings FAIL, jsx comments WARN; summary_config.json scanned).
W0 FORBIDDEN (regex over the normalised text): "no fuel rate pid", "great majority of drives" (near fuel), "no fuel flow (data|channel)", "amplitude floor", "contribute 0 0 gtc", plus regression guards from M325: "410/410", "re serializ", "originals unavailable".
W0 REQUIRED (bound to payload values): the footer shows {rfDodHistogram.nFilesUsed} SoC traces and the phrase "cycle range"; the fuel-unobservable text names "logger app" and "subset of drives".
Tests: tests/synthetic/test_language_gate.py with known-answer fixtures (positive hits incl. plural, concatenated-words and arrow variants; hedged/negated forms must NOT fail; payload key names ignored; comments WARN) and a regression test that the 26 existing semantic_gate FORBIDDEN entries still fire on synthetic text.
Isolation: drive_master.csv, raw/, raw_manifest.json unchanged; summary_arrays.json deep-diff = exactly the 8 leaves above (4 unobservable[1].why, 2 records notes, 1 methodology; plus nothing else); jsdom text diff = only the replaced strings; release_check green.
