# Audit v3 triage: epower_project_deep_audit_v3_2026-10-01.pdf (88 printed pages)

Status 2026-10-01: COMPLETE. Every printed page (F1-F15, C1-C14, 1-59) was ruled unit by unit by the research-director.
1,214 rows in ledger_all.tsv (ledger/P*.txt = per-partition sources). `python compile_ledger.py` re-verifies: 0 malformed, 0 duplicate IDs, 88/88 pages covered.
Untracked working files, not committed. No pipeline, master (MD5 bd9d1072...) or raw file was touched.

Classes: FIX-NOW 496, INFO 307, SPEC-FIRST 270, OWNER 39, BACKLOG 34, BLOCKED 26, STALE 23, DECLINE 19. Verified on disk (V) 682, not verified (NV) 228, disputed (D) 7.
Audit numbers are known-answer targets for scripts only; never type them into the repo.

## Owner decisions (2026-10-01)
O1 single top-level Fuel tab (host tab in code is "charts"; there is no "Energy" tab). O2 retire UNUSED files only; soc_patterns.json KEEP (xtrail_summary.jsx:17, build_html.js). O3 fuel cost (FUEL-13) rejected.

## Milestone plan (one open branch at a time; M320 merges first); FIX-NOW / SPEC-FIRST rows
M321 Records+floor (72/0): F05,F06,F07, all Appendix A labels/ties, C04 fields.  M322 Wording sweep (241/0).  M323 Compare/GTR gate+release hardening (103/1).
M324 Fuel tab, requires M323 (39/0).  M325 Cell-spread sensitivity+grid (10/15).  M326 Raw-pass sidecars (7/16).  M327 Seasonal contracts regen (48/14).
M328 Fuel contract v1, FUEL-01,02,03,04,11,12 (8/100).  M329 GTR repair, Opus audit (4/35).  M330 Supported contrasts+FUEL-10 (0/30).  M331 Fuel phase 2 (0/44).
New: GateA2 (R2 per channel, needs Andrii), F03-zip-sweep (read-only, needs Andrii), M332 Records-v2, housekeeping (retire unused files with archive hash), article-scope (owner-gated), grade-aware, event-aligned-recovery, dwell-trunc, narrative-fn.

## Needs Andrii
Approve GateA2 and the read-only hash sweep of the ZIPs in the Investigation folder; Article-10 durability table; logger/PID question (does the app read the ECU fuel-rate PID or compute from MAF); article directions 1-10 and fuel article (each needs Opus audit and a signed F03 dual report); origin of f01_perdrive_correction.csv and fate of highspeed_130_runlength_check.csv; the audit's evidence ZIP if available; CLAUDE.md "335/457" -> 333/489 restatement.
Retirement candidates (O2, after git-tracked check and sha256 archive): _det1/_det2 (scratch of test_seasonal t15), five *_backup.json, m294_patch.py, kpi_ci* family, chart_registry.json (no consumer, stale).

## Addendum 2026-10-01 (owner answers + archive sweep)
Owner: ZIP sweep OK; unused-file retirement OK; GateA2 left to my judgement (decision: GO, small, after M320 merges, before the next ingestion; flag-only, never repairs).
ARCHIVE SWEEP RESULT (read-only; zip_sweep.py, zip_sweep_report.json): 4,329 CSVs hashed (331 loose + 43 ZIPs) in the Investigation folder.
All 333 canonical files that fail the manifest today have a BYTE-IDENTICAL copy (sha256 equals raw_manifest.json) in that folder (161 in exported_records_full.zip, 143 loose, 29 in other ZIPs); 0 normHash-only matches. The 156 passing files are also present.
=> The F03 premise "originals unavailable" is wrong. Rows ruled BLOCKED/OWNER on originals (F01, F01.r2, C14.9, E-N1, p1.6 area) need re-ruling. NOTHING was changed: raw/ and raw_manifest.json untouched. Next step is a Director-governed F03 milestone (verify, restore into a separate dir, test that master reproduces, then Andrii decides re-anchoring).
f01_perdrive_correction.csv = per-drive table from M229 (F01 zero-crossing integration fix; rel_*=released, cor_*=corrected). Historical evidence: KEEP, archive hash. highspeed_130_runlength_check.csv = M271 run-length evidence, no code reads it: KEEP until M321 scripts an equivalent.
Retire list (all git-tracked, so bytes survive in history): _det1/_det2 (after test_seasonal t15 moves to tempdirs), five *_backup.json, m294_patch.py, kpi_ci* family, chart_registry.json. Do in a separate housekeeping milestone after M320 merges; sha256 manifest first.

## Addendum 3 (owner answers, 2026-10-01 later)
GateA2 (M308 amendment): GO. Unused-file retirement, f01_perdrive_correction.csv (keep), highspeed_130_runlength_check.csv (keep until M321): OK.
ARTICLE-10 SOURCE (resolves F23.r3 / E-N2 / p23.7): https://www-europe.nissan-cdn.net/content/dam/Nissan/nissan_europe/ev-battery-regulation/X-Trail_e-POWER.pdf (image-only PDF; rendered copy nissan_article10_table.png). Checked row by row: summary_config.json officialDisclosure transcription is EXACT (5 Ah; capacity fade 34%; 66.0 kW at SoC80 room temp; power fade 25.8%; 0.210 ohm at SoC80; resistance increase 75% as an upper value; round-trip 99.6%, fade 0.3%; 14 years / 190,000 km; no warranty implication). The document carries no date. TODO M322: record the URL in _provenance; relabel "unverified transcription" -> "verified against manufacturer PDF (retrieved 2026-10-01)".
LEAD for the Director (not decided): OEM rated capacity 5 Ah vs the repo's C-rate basis (CAP_KWH=2.1 kWh / median voltage = ~5.85 Ah). 5 Ah x ~359 V median pack voltage ~ 1.8 kWh, ~14% below 2.1 kWh. Affects F21 (C-rate), GTC/FCE normalisation (verified:false) -> needs a spec; do not change CAP_KWH silently.
LOGGER = Car Scanner ELM OBD2 with AUTOMATIC fuel calculation (F-R1 resolved): the fuel rate/counter are app-calculated (from air flow / mixture data), not an ECU fuel measurement. Consequences: say "logged/app-calculated", never "measured" (jsx:9804/9807, docs/findings-and-methods.md:18); FUEL-12 (rate vs counter) only checks one derivation against its own integral = internal consistency, NOT validation; FUEL-06 fuel-rate map is partly circular (air flow depends on RPM/load); fuel-derived hp is not independent. A genuine external check needs fill-up records (litres + odometer). Re-rule FUEL-06/-12 and F3.5/C9.6/p3-series rows accordingly in M328 spec.
