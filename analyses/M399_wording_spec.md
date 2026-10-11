# M399 spec (Rev 1): truthful-output wording wave (audits of 2026-10-11, N09 / D3 / F16 wording / F25 / N08)

Status: Rev 1, written before any edit. Origin: `analyses/audit_feasibility_2026-10-11/FEASIBILITY.md` (plan phase P0; Director triage section 6b: "wording wave first"). Branch `claude/next-milestone` = `main` (4a43360, M398).
Numbering: this wave takes M399. The capacity milestone currently drafted as `analyses/M399_spec.md` / `M399_experiment_protocol.md` is renumbered when it starts (its spec allows this); file names are left untouched.
No figure, estimator, CI, master column or published per-drive value changes. `drive_master.csv` MD5 `64dfd0cbff3db404d9b83e180f777525` must be identical before and after. ML16 not touched.

## Facts read from disk (2026-10-11)
- N09a: `xtrail_summary.jsx:12268` ends "...must not be mixed; gross runs ~2x net." On the corpus gross is 1568.944 kWh and signed net is about -49.6 kWh.
- N09b: `xtrail_summary.jsx:12387` says "the audit could not verify raw-stream results because the 1 Hz corpus was not in the audit package"; the span about fingerprints not establishing originals is gated on `rawManifest.corpusByteHash`, a key the payload no longer has. `provenanceSensitivity.raw` holds `nCanonical`, `nCanonicalHashFailing` (0), `originalsAvailable`, `formerReexportsReplaced`.
- D3: JSX 7385, 7440, 7500, 8468, 8882, 9041, 9290 say "~1.3 Hz" / "~1.26 Hz"; `eligibility.dataCoverage.currentPid.updateIntervalS` gives median 1.284 s (p10 0.784, p90 1.716).
- F16 wording: "scales linearly" with the 2.1 kWh constant (JSX 11742, 11986, 12381; `summary_config.json` capacityNote and `constantProvenance.CAP_KWH.note`; `compute_summary_arrays.py` CONSTANT_PROVENANCE; payload `assumptionsRegistry[0].sensitivity`); GTC/FCE = throughput / reference and C-rate = current / reference charge capacity, so they scale **inversely**. "not a published OEM spec / not an OEM nameplate figure" (config 3710/3712, producer line 162, JSX 2506, 6611, 10775, 11897, 12268, 12368, payload `constantProvenance`, `assumptionsRegistry[0].source`, `generatorTractionRecon.audit[8].basis`) contradicts Nissan Australia (13 Oct 2022, page fetched 2026-10-11): "a high-output 2.1kWh battery" for the X-Trail e-POWER with e-4ORCE (twin-motor AWD); no gross/usable definition; no FWD statement.
- Silent fallbacks: 10 x `?? 2.1` in the JSX (lines 1150, 1854, 3643, 4161, 4238, 10775, 10841, 12268, 12272, 12368).
- Archaeology / labels: JSX 3435 (rendered "M58 ... previously quoted"), 11414-11422 (rendered "recomputed 2026-07-10 (M27) after the prior hand-typed ... superseded 28 W figure"), 4902 ("refreshed at M373"). JSX 3944-3947 is a `{/* */}` comment, not rendered: no change.
- F25: `energy_uncertainty_mc.json` (written only by `energy_uncertainty_mc.py` as a CLI, not by any stage) says nominal 1295.913 kWh; live `energyUncertaintyMC.grossThroughputMC.nominalReleasedThroughputKwh` is 1568.9442.
- N08: `tools/mc_dq_note_refresh.py` executes at import and regex-parses prose.

## Changes
1. JSX helpers `capKwhText()` (no silent 2.1; renders "n/a (CAP_KWH missing from the payload)") and `cadenceText()` (median update interval in seconds first, Hz second, from `eligibility.dataCoverage.currentPid.updateIntervalS`). All 10 `?? 2.1` removed.
2. N09a: sentence "gross runs ~2x net" deleted; the capacity parenthesis bound to the provenance wording below.
3. N09b: footer rebuilt from `rawManifest` (counts, corpus MD5) and `provenanceSensitivity.raw` (canonical files matching `raw_manifest.json`, originals, replaced re-exports); old audit-limitation text removed (it belongs to the CHANGELOG).
4. D3: the seven Hz statements use `cadenceText()`.
5. Capacity wording: "scales linearly" replaced by "scales inversely with the selected reference capacity" everywhere (JSX, config, producer, payload leaves); the OEM statement replaced by: "assumed normalization constant; Nissan Australia publishes 2.1 kWh for the X-Trail e-POWER e-4ORCE (13 Oct 2022) without defining gross versus usable energy; applicability to this front-wheel-drive pack is unverified". The 5 Ah per-cell sentence stays. No capacity value, `verified` flag or `CAP_KWH` changes.
6. 3435 and 11414-11422 rewritten without history; 4902 "refreshed at M373" replaced by the block's `status` text from `refreshedBlocks`.
7. F25: `energy_uncertainty_mc.json` is regenerated from the live payload object by a new tool `tools/write_mc_sidecar.py` and run as the last step of the existing MC stage; `release_check` asserts sidecar nominal == live nominal.
8. N08: `tools/mc_dq_note_refresh.py` gets a pure `refresh(arrays)` and a `main()` guard; import writes nothing (unit test).
9. Language gate: every replaced wording becomes an OLD-wording rule with ledger id `M399-*` (scope: dom, payload, config, jsx). Required-wording checks: "scale inversely", the Nissan Australia qualification in the CAP_KWH note, the cadence sentence containing seconds.
10. Fact-aware checks in `semantic_gate.py`: (a) no sentence "gross runs ~Nx net" may render (any N) and the footer must state the matching count from `provenanceSensitivity.raw`; (b) no `?? <number>` fallback on a payload constant in the JSX (regex over the source, allow-list empty); (c) sidecar == payload nominal.
11. F06 (stamp schema split) is **not** in this milestone: it is a design decision (deferred by M382 for the same reason) and gets its own spec.

## Acceptance
- `drive_master.csv` MD5 unchanged; deep-diff of `summary_arrays.json` / `summary_config.json` limited to the leaves in the allow-list (capacity wording leaves, `assumptionsRegistry[0]`, `generatorTractionRecon.audit[8].basis`, `constantProvenance.CAP_KWH.{source,note}`, `fadeModes.capacity.whyNoObservable` only if it contains the retired wording).
- New tests fail on the pre-fix state (known-answer OLD strings) and pass after; `node build_html.js` ok; `validate_jsdom.js` 10 tabs, 0 console errors; `semantic_gate.py` 0 failed; `python release_check.py` green.
- Dashboard change rule: render with SendUserFile; commit with sources (`xtrail_summary.jsx`, `summary_arrays.json`, `cohort_arrays.json`) in one commit; PR opened by the agent; CHANGELOG `M399` entry via `tools/changelog_draft.py`.

## Out of scope
F06 schema split; N01-N07 and other P1 items (next milestone); any capacity value change (M399-capacity / M399a); the "+0.73" / "r=0.5514" calendar-correlation line (not located; needs the audit's `targeted_literal_inventory.json`).
