# M523 spec (Rev 1, DRAFT for Director review): remaining literals near the RPM chart: bind, classify or label (M522 follow-up)

Status: PRE-REGISTERED DRAFT, 2026-10-27, written before any edit. Owner: Andrii (chat, 2026-10-27: "spec M523 ... and take it through the new-analysis workflow"). Origin: M521 audit literal list, M522 Director follow-up. Scope: wording and display binding only; NO payload key or value change, NO new computation (a producer for the M205/M218 centres would be a separate analysis, M524 candidate).

## 1. Inventory (read before this spec; payload and sources only, no outcome statistic)

Prose sites: `xtrail_summary.jsx` RpmDistributionChart pooled caption (~6088) and the Manufacturer cross-check (~12081); config note unchanged since M522.

| Literal | Where | Class | Payload source |
|---|---|---|---|
| 95 % (intervals), 50 % (first zone reaching 50 %), +/-25 rpm window, 1 Hz | various | A definitional: a method constant, not a finding | none needed |
| "1975-2025" (peak window), "1475-1525", "1564-1614" bin windows | caption, M205/M218 text | B bindable label | `S.rpmDistribution.bins` (peak via `bins[peakIdx]`) |
| "~2.5 %" motored share of the boost-classified population (RPM > fuelStateRpmMin) | caption (fuelledExtended view) | B bindable value | `fuelled.hours`, `motored.hours`: sum(motored)/(sum(motored)+sum(fuelled)) = 0.94 % on the live payload (hours basis); the literal 2.5 % is stale, bound would show 0.9 % |
| 2000.30 rpm weighted centre of mass, 1500 and 1589 setpoint centres, 96 %+ within +/-25 rpm, 45/55 split of the old 1900-2100 bin, "1400-1600" old bin, 98.3 % recall / 0.33 % contamination (M89), 78.9 % recall / 30 %+ contamination | caption, cross-check | C historical finding: derived at M205/M218/M89 from a 5 rpm re-derivation or calibration on the corpus of that date | NO payload key; not recomputable from stored histograms (bin edges are 25-50 rpm wide) |

## 2. Change

1. Class A: no change; where a sentence states one as a result, name it as a method setting (e.g. "95 % day-clustered interval") only if it does not already.
2. Class B: bind the peak/setpoint window labels to `S.rpmDistribution.bins` with the M522 style guard (label shape check, else omit the label rather than show a literal); bind the motored share to a helper `motoredShareText(rd)` (hours basis, one decimal, "n/a" on missing/zero, scope text "hours, bins >= fuelStateRpmMin"). The sentence becomes "... it is only ~" -> "... it is {x.x} % of the boost-classified hours" (no "~"). This changes ONE displayed number (2.5 -> 0.9).
3. Class C: no binding. Add one provenance clause in each sentence: "(historical M205/M218 re-derivation at 5 rpm resolution on the corpus of that date; not recomputed on the current corpus)". The numbers stay; the claim "from raw field telemetry" at the cross-check is qualified accordingly.
4. Language rule `M523-historical-rpm-literals`: forbids stating the class C numbers without the "historical ... not recomputed" qualifier in the same sentence (context rule), and the old "~2.5%" wording.
5. Record the class C list and the M524 candidate in the CHANGELOG: a pipeline producer (raw 5 rpm pass, new payload key `rpmSetpointCentres`) needs its own spec, blind audit and Director decision; it is NOT done here.

## 3. Acceptance and falsification

- A1: the motored share shown equals the recompute from `summary_arrays.json` to 0.1 percentage point in all five cohort modes where the view renders (cohort-aware like the chart: it follows the shown cohort's `motored`/`fuelled`; pooled otherwise); test `tests/synthetic/test_m523_literals.py` with the M522 negative controls (patched hours change the text; zero/NaN -> n/a; relabelled bins -> label omitted).
- A2: tab-dump diff before/after shows changes ONLY in the caption/cross-check sentences; `summary_arrays.json` byte-identical; master MD5 unchanged.
- A3: no class C number appears in the rendered dumps without the qualifier (test on the dumps).
- Stop: any need to change a payload value or add a key, or to assert that a class C value still holds on the current corpus (not testable without the raw pass) -> M524.

## 4. Language

Allowed: "historical M205/M218 re-derivation (5 rpm resolution, corpus of that date; not recomputed on the current corpus)"; "bound to the payload". Not: "corrected", "up from 2.5 %" (the literal was stale/hand-typed; do not call it a trend), "still holds", "independently confirmed" for class C values, "measured" (rpm is logged).

## 5. Gates

py_compile, `node build_html.js`, `node validate_jsdom.js`, `node dump_tabs.js` THEN `semantic_gate.py`, new test, `release_check.py`, the full CI unit list locally (background), CHANGELOG M523 with this session's gate counts (no carried delta flags), blind `analytical-auditor` (recompute the motored share, list every numeric literal still unqualified in the two sentences), Director decision. No article figure; no Andrii sign-off unless the Director says otherwise.

## 6. Questions for the Director

Q1 Is labelling class C as historical (no recompute) acceptable for M523, or must the centres be recomputed first (M524 before M523 display)? Q2 Motored share basis: hours (as the payload offers) vs samples vs drives; the sentence says "population". Q3 May the cross-check sentence "from raw field telemetry rather than a bench calibration" stay once qualified? Q4 Are the A-class constants left as they are. Q5 Does the old "1400-1600 secondary mode" phrase (an obsolete bin) stay as history or go.

## 7. Rev 2 (2026-10-27): Director review (verdict "revise, minor"); incorporated, no re-review needed

- **Rulings.** Q1: labelling class C as historical is acceptable (M524 need not come first); the qualifier names the source milestone and the resolution and says "not recomputed on the current corpus". Q2: hours basis, sentence names it: "of boost-classified engine-on hours (bins >= fuelStateRpmMin)"; never "population"; no claim that the hours share equals a sample or drive share. Q3: keep the contrast with a bench calibration; "raw field telemetry" becomes "logged field telemetry" plus the historical qualifier; nothing may suggest reproducibility from raw/. Q4: class A unchanged (edit only where stated as a result). Q5: "1400-1600 secondary mode" stays, labelled "obsolete pre-M205 bin definition".
- **R1 (trace of "2.5 %").** `git log -S` places the literal at the M299 import (first commit); the CHANGELOG has no entry that derives it. Its basis (samples / drives / hours, threshold, corpus date) is therefore NOT traceable. The wording will say "hand-typed, basis not traceable; replaced by the payload hours share", never "stale" or "corrected", and the CHANGELOG states this. Escalate if a basis is found later that differs.
- **R2.** The bound share is "descriptive, no interval"; the text shows hours (motored h of total h). A day-clustered interval is M524.
- **R3.** Other "only ~" sites (jsx ~6274 hand-typed history text, 8047, 10112 comment, 13080 payload-bound kW) are OUT OF SCOPE; listed in the CHANGELOG.
- **R4.** A2 also requires `cohort_arrays.json` and `summary_config.json` byte-identical.
- **Negative controls added.** (a) patched `fuelStateRpmMin` moves the share; (b) switching cohorts changes the text; (c) missing motored/fuelled key shows n/a; (d) an injected unqualified class C number makes the dump test fail; (e) the language rule fires on the old "~2.5%" and on unqualified class C wording and passes the new wording.
- **Language.** Never "corrected", "up from", "still holds", "independently confirmed", "measured"; "logged" rpm; name the hours base.
- **Escalate if** the 2.5 % basis is found and differs, any payload/key change or class C recompute (M524), the dump diff touches sentences outside the two scoped sites, or cohort values disagree with the recompute by > 0.1 pp. No Andrii sign-off.

## 8. Implementation deviation D1 (2026-10-27)

Class B bin windows ("1975-2025", "1475-1525", "1564-1614") occur only inside the M205/M218 history sentences, where they state what that re-derivation did; binding them to the live bin labels would rewrite history. They are treated as class C (qualified, not bound). Only the motored share is bound. To be confirmed by the Director with the audit.
