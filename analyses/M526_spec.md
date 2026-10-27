# M526 spec (Rev 1, DRAFT for Director review): stale corpus-size statements in payload text (sweep result) - correct or qualify; payload TEXT leaves only

Status: PRE-REGISTERED DRAFT, 2026-10-27, written before any edit. Owner: Andrii (chat, 2026-10-27: "continue"). Origin: M524/M525 follow-ups ("sweep for other one-off blocks outside staleBlocks", `loadProxyBasis`, "tone=measured" check). Scope: payload STRING leaves and their producer text only; NO numeric payload value, NO key added or removed, NO computation. The analyses deferred from the earlier list (raw 5 rpm recompute of the historical 2000.30 / 1500 / 1589 rpm values; a day-clustered interval for the motored share, which needs per-drive motored/fuelled hours that the payload does not hold) are renumbered M527.

## 1. Sweep (read-only; method and result before any edit)

Method: every string leaf of `summary_arrays.json` (178 top-level keys; all 178 stamps carry the live master hash, so stamps are NOT evidence of freshness) searched for "NNN-drive" corpus-size statements with 200 <= NNN < 606; each hit read in context and classified. Result (12 keys hit; classified):
- **History or correctly labelled (no change):** `determinism._provenance`; `generatorTractionRecon._provenance`, `refreshedBlocks[*].carriedBasis`, `eligibilityAlignment.*` (frozen M375 record); `fuelAnalytics.fuel12.m366Shift.basis` (frozen M366); `batteryTempRanges`, `exposureBasis`, `riskDischargeShare`, `socBalancedFuel` (subset counts: drives with the PID / accumulator, correct); `records[26,27]` ("601 drives" = drives with rainflow cycles and distance > 0, recomputed from the master = 601: correct); `records[37]` (gate-sensitivity counts); `rpmFinding.supersededNote`, `rpmOptBand.supersedes` (M525, correct).
- **Stale statements to fix:**
  1. `generatorTractionRecon.limitations[4]` (RENDERED in the fuel tab, 4 dumps): "The headline corpus figures, drive-type split and RPM empirical-grounding sample (410 drives, refreshed M281) are current." The RPM sample is the superseded one-off pass; the live value is `rpmOptBand` (M525).
  2. `rpmDistribution.params.loadProxyBasis` (+ the same string in `seasonalCharts.charts.RpmDistribution.data.{all,warm,shoulder,cold}.params`; 5 leaves; producer line `compute_summary_arrays.py` ~4619; not rendered, payload scope): "only ~2.5% of the boost-classified population" (hand-typed since the M299 import, basis not traceable; the payload hours share is 0.94 %) and "load-based motored recall (up to 78.9%) carries 30%+ contamination" (historical M89 calibration, no payload key).
  3. `seasonalCharts._meta.nativeEquivalence.note` and `_meta.md5RestampNote` ("re-derived on the live 446-drive payload", "matched the live 446-drive corpus"): the corpus is 606; the statements describe the M295 / M293 state; `seasonalCharts._staleness.reason` ("stay carried forward at the 410-drive basis ...") must be checked against `perChartStatus`/`stillStale` (the text says 0 failed the parity guard). Not rendered.
  4. `socHysteresisV2.recomputePolicy`: "even at the current 320-drive corpus" (the verification was run at 320 drives). Not rendered.
- **Withdrawn from the list:** "tone=measured" - `MetricHighlight`'s `tone` only selects a colour class (`evStatus(tone)`); no "measured" text is rendered; not a wording issue.

## 2. Change (text only)

1. limitations[4]: "... are current; the RPM-grounding OPT-band occupancy was a one-off 410-drive pass and is superseded by the live `rpmOptBand` (M525)." (no new number).
2. loadProxyBasis (producer string + 5 leaves, byte-identical edit in all): "only ~2.5% of the boost-classified population" -> "a small share of the boost-classified hours (the live hours share is shown in the RPM Distribution section; the earlier hand-typed ~2.5 % has no traceable basis)"; "up to 78.9%" and "30%+" get the existing historical qualifier ("historical M89 calibration, not recomputed on the current corpus"). Additive leaf-level splice with a deep diff (only those 5 leaves change).
3. Notes: replace "live 446-drive" by "the 446-drive corpus of that milestone (M295)" and likewise for M293; re-read `_staleness.reason` against `perChartStatus`; fix only if it contradicts the structured fields.
4. recomputePolicy: "at the 320-drive corpus of that verification (peak RSS 1874MB then; not re-measured at the current corpus)".
5. Language: new rule `M526-corpus-size-text` (payload scope included) forbidding "refreshed M281) are current", "only ~2.5%", "live 446-drive", "current 320-drive"; the M523 rule's payload exemption is lifted for "only 2 5 of the boost classified population" once the payload text is fixed.

## 3. Acceptance and falsification

- A1 `tests/synthetic/test_m526_payload_text.py`: the old strings are absent from payload, producer and rendered dumps; the new strings are present; the rule fires on each old string and passes the new ones.
- A2 deep diff: only the listed string leaves changed (<= 5 + 1 + 3 + 1 = 10 leaves); every numeric leaf, every key and `drive_master.csv` / `cohort_arrays.json` / `summary_config.json` byte-identical; stamps untouched except the declared-stamp re-derivation if required.
- A3 the rendered dumps change only in the limitations sentence (fuel tab, 4 dumps).
- A4 blind audit: re-run the sweep without being told the list and report any remaining stale corpus-size statement.
- Stop: any need to change a number or a key; a sentence whose true basis cannot be determined (then the sentence gets the "basis not traceable" wording, never a guessed number).

## 4. Language

"hand-typed, basis not traceable", "historical, not recomputed on the current corpus", "superseded by rpmOptBand". Not: "corrected", "up to date", "stale" as a claim about the data, "measured".

## 5. Gates and process

py_compile, `node build_html.js`, `node validate_jsdom.js`, `node dump_tabs.js` THEN `semantic_gate.py`, new test in CI, `release_check.py`, full CI unit list locally (background), CHANGELOG M526 (spec SHA-256 before the first edit), blind audit, Director decision. No article figure; no Andrii sign-off.

## 6. Questions for the Director

Q1 Is editing a producer text constant plus a leaf-level splice (no recompute) acceptable for loadProxyBasis, or must the arrays producer be re-run (it reprocesses every raw file, forbidden for routine updates)? Q2 For the frozen records (M366, M375) keep as is? Q3 May the M523 rule's payload exemption be lifted in this milestone? Q4 Is M527 (raw 5 rpm recompute; motored-share interval) correctly separated as new analyses?

## 7. Rev 1.1 (2026-10-27): Director review (verdict "revise, minor"); incorporated. Spec SHA-256 of Rev 1 recorded before the first edit: 2833c949d13779ec.

- **Rulings.** Q1: producer constant edit + leaf-level splice (no producer re-run) is the additive-splice pattern; every leaf must name its writer. Q2: frozen M366/M375 records, `carriedBasis` and `supersededNote` stay verbatim. Q3: lift the M523 payload exemption in this milestone after A1 is clean, for that pattern only; old wording kept as rule (M523 + M526 ids). Q4: M527 is a new analysis.
- **Leaf and writer table (9 payload leaves).** (1) `generatorTractionRecon.limitations[4]`: one-off, frozen; text lives in `tools/m373_p2_splice.py` line 69 (a splice constant: edited too so a re-run cannot restore it). (2-6) `rpmDistribution.params.loadProxyBasis` and `seasonalCharts.charts.RpmDistribution.data.{all,warm,shoulder,cold}.params.loadProxyBasis`: writer `compute_summary_arrays.py` (`rpmDistribution` block, ~4619: constant edited so an ingestion cannot restore the old text; `tools/m487_wording_splice.py` only patches the 98.3 % clause and is not touched). (7) `seasonalCharts._meta.nativeEquivalence.note`: one-off, frozen; text lives in `m295_payload.py` line 56 (edited too). (8) `seasonalCharts._meta.md5RestampNote`: one-off, frozen; no writer text found in any script. (9) `socHysteresisV2.recomputePolicy`: writer `compute_summary_arrays.py` (~17345, edited). `seasonalCharts._staleness.reason` is regenerated by `m296_refresh_master_seasonal.py` / `tools/regen_seasonal_raw.py` from `stillStale`; with `stillStale = []` the sentence "the 0 that failed the parity guard stay carried forward at the 410-drive basis" is accurate (zero charts): not changed (aligned to the structured fields, never the reverse).
- **Attributions grepped from the CHANGELOG.** M216 (320-drive corpus verification, peak RSS 1874 MB) and M293 are headings; M89, M294 and M295 have no heading entry and the "78.9 %" / "30 %+" figures are not traceable in the CHANGELOG: those clauses say "basis not traceable in the CHANGELOG" and keep the historical qualifier. "limitations[4]": only the RPM item is changed; the "headline corpus figures and drive-type split are current" claim is left as written (unchanged claim, not part of this milestone).
- **Extra controls.** N1 the new rule gives 0 hits on the frozen/history strings and the whole post-edit payload (the new loadProxyBasis text keeps "~2.5 %" in a hand-typed-basis clause: checked); N2 a planted extra leaf change makes A2 fail; N3 the splice is idempotent; N4 a static test that the producer constants equal the payload leaves; N5 the A4 sweep is wider ("N drives", "n=N", "current/live corpus", "refreshed M###", N < 200, over summary_config.json and jsx strings too); hits outside scope are listed as follow-ups, not edited. Declared stamps: list in A2 every stamp covering `generatorTractionRecon` / `seasonalCharts` / `rpmDistribution` / `socHysteresisV2`; re-derive only through the existing restamp tool; check the parity guard and the semantic-gate payload scope do not hash `_meta` text. Sonnet blind audit (A4) + Director decision; no Opus; no Andrii sign-off.
