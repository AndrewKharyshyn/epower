# M522 spec (Rev 1, DRAFT for Director review): bind the stale "~4%" 300-1400 rpm literal to the payload and re-rule "near-empty" / "transient rev-through"

Status: PRE-REGISTERED DRAFT, 2026-10-27, written before any edit. Owner: Andrii (chat, 2026-10-27: "Yes: spec M522 ..."). Origin: M521 Director ruling (follow-up M522) and the M521 blind audit finding CFG1. Scope: ONE displayed number changes (4 % -> the payload-derived share); no payload value changes, no new estimator.

## 1. Facts read before this spec (payload and code only)

- `S.rpmDistribution.pooledHours` (1 Hz grid, duration-weighted, rpm >= 300): bin 1 = "300-1400 (transient)" = 5.204 h; engine-on total (bins[1:]) = 99.867 h; share = 5.21 %. The displayed "~4%" is a hard-coded literal (stale, from an earlier corpus). `S.rpmDistribution.params.fuelStateRpmMin` = 1400.0 (the other hard-coded "1400 rpm").
- Displayed occurrences: `xtrail_summary.jsx` ~12070 (Manufacturer cross-check: "the 300-1400 rpm band near-empty (~4% of engine-on time, a transient rev-through, not a sustained band)"); ~6077 ("note the near-empty 300-1400 band", no number). Config text (not rendered by `.note`, but embedded and language-gated): `summary_config.json` `oemTechReview.engineFloor.note` ("independently resolves as near-empty (~4% of engine-on time, a rev-through transient, M83)"). The bin label "(transient)" comes from the producer (`RPM_HIST_EDGES` labels).
- Not bindable: "2000.30 rpm" (M205 centre of mass) has no payload key; it is listed, not edited.
- The rpm duration inside the band is not analysed anywhere (no run-length by rpm band): "transient / rev-through" is an inference from the low share and from the M83 reading, not a measured duration.

## 2. Change (wording and binding only)

1. 12070: compute the band share in the existing IIFE from `hrs` (same derivation pattern as `peakPctOfEngineOn`): `bandPct = hrs[1]/engineOnHrsTotal*100`, `bandH = hrs[1]`, floor = `S.rpmDistribution.params.fuelStateRpmMin`. Display one decimal (5.2 %), with hours.
2. Wording (Director to rule, recommendation): replace "near-empty" by "low-occupancy"; replace "a transient rev-through, not a sustained band" by "consistent with passage through the band rather than sustained operation (time spent inside the band is not analysed)". Alternative A: keep "near-empty" with the bound number. Alternative B: drop the mechanism clause entirely.
3. 6077: add the bound share next to "300-1400 band" in the same wording.
4. Config note: remove the numeric literal and the mechanism clause; point to the RPM Distribution section (config strings cannot compute). `measured directly` -> `field-logged` only if the Director agrees (M521 pattern).
5. Language rule `M522-band-occupancy` (old wording: near-empty, rev-through, "~4% of engine-on time") with ledger id; allowed phrases must not trip context rules.

## 3. Acceptance and falsification

- A1: the displayed share equals `pooledHours[1]/sum(pooledHours[1:])` to 0.1 percentage point, shown in the rendered tab dump of `charts` in all five cohort modes; test `tests/synthetic/test_m522_band_binding.py` recomputes from `summary_arrays.json` and checks the dump.
- A2: tab-dump diff (before/after) shows changes ONLY in the lines above; no other displayed number changes; `summary_arrays.json` byte-identical; `drive_master.csv` MD5 unchanged.
- A3: if the share moves at a later ingestion the displayed value follows the payload (no literal remains in the sentence); a negative control (patched payload) changes the dump.
- Stop: any need to change a payload value, add a payload key, or make a duration claim about the band -> separate milestone with its own spec.

## 4. Language

Allowed: "low-occupancy 300-1400 rpm band (5.2 % of engine-on time, rpm >= 300, 1 Hz grid, duration-weighted)". Not: "near-empty", "rev-through", "measured" for rpm-derived shares, "transient" as a finding, "corrected" for the edit. The 5.2 % replaces 4 %: say "bound to the payload", not "corrected".

## 5. Gates

py_compile, `node build_html.js`, `node validate_jsdom.js`, `node dump_tabs.js` THEN `semantic_gate.py`, new test, `python release_check.py`, full CI unit list locally (background), CHANGELOG M522 (prepend via `tools/changelog_draft.py`), blind `analytical-auditor` (reproduce the share and list every hard-coded number in the two sentences from the sources), Director decision. No article figure; no Andrii sign-off unless the Director says otherwise.

## 6. Questions for the Director

Q1 wording (recommendation vs A vs B). Q2 is the 6077 number addition in scope. Q3 may the config note lose its number and mechanism clause in this milestone. Q4 "field-logged" for "measured directly". Q5 the other flagged literals (95 %, 50 %, 2000.30 rpm, 1400 rpm elsewhere): leave, or bind where a key exists.

## 7. Rev 2 (2026-10-27): Director review (verdict "revise, minor"); incorporated, no re-review needed

- **Rulings.** Q1: "low-occupancy 300-1400 rpm band (X.X % of engine-on time, Y.Y h of Z.Z h; rpm >= 300, 1 Hz grid, duration-weighted; descriptive, no interval)"; the mechanism clause is "consistent with passage through the band rather than sustained operation (not tested: time spent inside the band is not analysed)"; Alt A rejected. Q2: in scope; ONE helper builds the text for both call sites (6077 and 12070). Q3: yes (config note loses number and mechanism clause; "M83 reading" as history only). Q4: "field-logged". Q5: out of scope; only the "1400 rpm" in the two edited sentences binds to `params.fuelStateRpmMin`; 95 %, 50 %, 2000.30 rpm and other literals are listed in the CHANGELOG with a follow-up id.
- **R1.** The producer bin label "300-1400 (transient)" renders in the dump: rule `M522-band-occupancy` is scoped to "near-empty", "rev-through" and "~4% of engine-on time" only (no bare "transient"); a test shows the bin label passes and the old sentence fails.
- **R2.** `pooledHours` is pooled; the displayed value must be identical in all five cohort modes (A1 checks it).
- **R3.** Guards: missing / zero / NaN `pooledHours[1]` or total renders "n/a", never a literal. Negative controls: (a) patched `pooledHours[1]` changes the dump; (b) patched `fuelStateRpmMin` changes the floor text; (c) the gate flags the old sentence; (d) the old "~4%" string is absent from the JSX source.
- **R4.** The share is descriptive: "descriptive, no interval"; no n/CI key is added (payload unchanged).
- Language: "bound to the payload", never "corrected"; no "up from 4 %" (corpus growth, not a trend); no dwell claim. Escalate if a payload value/key or producer label must change, another displayed number moves, `summary_arrays.json` or master MD5 changes, the auditor's recompute differs by > 0.1 pp or finds another occurrence of the literal.

## 8. Implementation deviation D1 (2026-10-27, to be ruled by the Director with the audit)

R2 asked for an identical value in all five modes. Only the Manufacturer cross-check site (12070, pooled `S.rpmDistribution`) is mode-independent (5.2 % of 99.9 h in all five). The chart site (6077, `RpmDistributionChart`) reads `cohortOr("RpmDistribution", ...)`, i.e. the chart's own cohort data, so its sentence follows the chart: warm 5.3 % (4.1 h of 77.3 h), shoulder 5.1 % (1.0 h of 20.2 h), cold 3.7 % (0.1 h of 2.4 h; exploratory), all 5.2 %. Binding it to the pooled series inside a cohort-filtered chart would put a figure next to bars that do not match it. The test checks the chart site against `seasonalCharts.charts.RpmDistribution.data[mode]` and the cross-check site against the pooled series. Tab-dump diff before/after: only the five `highway_vs_city` dumps change (the two sentences); `summary_arrays.json` is untouched.
