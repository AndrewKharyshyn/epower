# M743 spec Rev 2: re-baseline of the cumulative-drift check in `tools/delta_report.py`

Status: Rev 2 after the Director review of Rev 1 (decision 'revise'; rulings and conditions in section 6, they override sections 2-3 where they differ). Written before any code and before any result. Tooling only: no payload key, dashboard figure, estimator or gate that stops an ingestion changes. Number taken after checking the CHANGELOG head (M741), open PR 419 (M742) and the remote branch `claude/m742-next` (parallel session).

## 1. Finding (read from disk, 2026-11-22)
1. `delta_report.py` flags `cumulative drift > baseline CI half-width` against `hist[0]`, the FIRST snapshot of `snapshots/kpis.jsonl`.
2. For `EnergyIntensity.shoulder` that snapshot is 2026-10-05: 26.80 [24.73, 30.12] (half-width about 2.70). The next snapshot of 2026-11-04 reads 19.52 [16.27, 25.23]; the current live value is 20.05 [16.86, 25.23]. Cumulative drift -6.74, about 2.5 half-widths. The step happened between the second and third snapshot (corpus growth is the recorded explanation in M721, not verified; definition, eligibility and season are not excluded).
3. The flag therefore fires on every ingestion and has been carried as "standing, report-only" in each CHANGELOG entry. A standing flag cannot detect a new shift (alarm fatigue); it also formally sets `route_to_audit`.
4. Second defect: the last snapshot is 2026-11-05 (M578). No ingestion stage runs `delta_report.py --commit` (grep of `tools/ingest_stages.json`: none), so the "previous snapshot" of the per-step flags is stale by every ingestion since M578. The current per-step delta (0.11 of the half-width) is a delta against 2026-11-05, not against the last ingestion.
5. The other two cohort KPIs show cumulative drift of +0.37 (all) and +0.21 (warm), inside their baselines: only shoulder is affected.

## 2. What changes (proposal)
**2.1 Rebaseline marker.** A snapshot record may carry an optional list `"rebaseline": ["<KPI name>", ...]`. The cumulative-drift reference for a KPI is the LAST snapshot that lists it in `rebaseline`, else `hist[0]` (unchanged behaviour for every other KPI and for all old records). The file stays append-only; no existing line is edited. The report records, per KPI, `baselineUtc` and `baselineValue`, so the reference is visible in `delta_report.json`.
**2.2 CLI.** `python tools/delta_report.py --commit --rebaseline NAME [NAME ...]` appends one record whose `rebaseline` lists NAME (names must exist in `kpi_paths.json`, else exit 2). Without `--rebaseline` the behaviour is unchanged.
**2.3 First use.** One re-baseline record for `EnergyIntensity.shoulder` only, appended after Director approval of this spec, with the live value at that time. Scale: the baseline half-width then is the current CI half-width (about 4.2), so the check regains meaning for the next shift. The old baseline stays readable in the history; the CHANGELOG entry states old and new baseline values from the script output.
**2.4 Snapshot cadence (second defect).** A routine `--commit` after each accepted ingestion is part of the ingestion milestone checklist (`docs/open_items.md`, next-ingestion list) rather than a new ingestion stage; making it a stage changes `tools/ingest_stages.json` and the resume/checkpoint logic and is out of scope here (offered as a separate decision). Until then the stale-previous finding is disclosed in the first report after the change.
**2.5 What is NOT changed.** The thresholds (outside previous CI, 0.5 x half-width, CI width change > 50 %, cumulative drift > baseline half-width), the other KPIs, `route_to_audit` semantics, the M723 reading flags, all payload keys. No flag is suppressed by name; the check is only measured against a newer reference.

## 3. Decisions for the Director
D1 Is a per-KPI re-baseline marker acceptable, or should a re-baseline require a decomposition of the 27 -> 20 shift first (corpus growth vs definition vs season)? Proposal: the re-baseline does not need it (it changes a monitor, not a figure) but the CHANGELOG entry states that the cause of the drop is not established; the decomposition stays a separate optional analysis.
D2 Should re-baselining be allowed for any KPI by the same flag, with the CHANGELOG entry as the record? Proposal: yes, one named KPI per decision.
D3 Snapshot cadence: checklist item now, ingestion stage later (needs its own review). Proposal: as in 2.4.
D4 The re-baseline hides a real signal if the shoulder level is still moving: report beside it the last three snapshot values so a trend stays visible. Proposal: add `history` (last 5 values) to the shoulder row of `delta_report.json`.

## 4. Checks
K1 known-answer test `tests/synthetic/test_delta_report_rebaseline.py` (add one line to the CI python test list): planted history of 4 snapshots with a step; without a marker the cumulative flag fires (old behaviour, reproduced exactly); with a marker on the planted KPI the reference moves and the flag clears; a second planted KPI without a marker keeps the old reference; unknown KPI name exits 2; old records are never rewritten (file bytes of the first lines unchanged).
K2 on the live data before the first use: the report with no marker equals the current `delta_report.json` flags exactly (regression); after the marker only the shoulder cumulative flag disappears.
K3 no blind audit of numbers is needed (no figure); Sonnet review of the diff for the append-only and per-KPI scoping.

## 5. Out of scope
The decomposition of the 27 -> 20 shift; the ingestion-stage change; other monitors (cadence, dissipation, winter); any dashboard or article figure. Language: "monitor reference", never "corrected" or "resolved" for the shoulder drift.

## 6. Rev 2 (Director rulings on Rev 1)
R1 (D1) Go without a decomposition: the change moves a monitor reference, not a figure. But the step from snapshot 2 (26.93 [24.98, 29.86]) to snapshot 3 (19.52) lies OUTSIDE the previous CI and was never blind-audited. The CHANGELOG states that its cause is not established and that the step is not accepted as a level; the decomposition is recorded as an OPEN item in `docs/open_items.md` (not only optional).
R2 (D2) The mechanism may serve any KPI, one named KPI per Director decision, recorded in the CHANGELOG. It is not self-service: the CLI is never run by an ingestion stage or by `data-worker`.
R3 (D3) Checklist item now, stage later as a separate decision. The first report after the change discloses that 'prev' is the 2026-11-05 snapshot (632 drives) against 717 drives now.
R4 (D4) Generalised: every KPI row that has a rebaseline carries `history` (last 5 `{utc, value, ci}`). The 'three' in 2.4 is read as five.
Conditions:
C1 `--rebaseline` exits 2 if, in the same run, the named KPI has any per-step flag (outside previous CI, |delta| > 0.5 x half-width, half-width change > 50 %): a re-baseline must not absorb a fresh shift.
C2 The rebaseline record carries a milestone id and a reason (`M743`). The row reports `baselineUtc`, `baselineValue`, `baselineHalfWidth` and the pre-rebaseline `hist[0]` reference.
C3 The marker counts only if that record holds the KPI with a numeric value and a complete CI; otherwise the reference falls back to `hist[0]`. K1 tests this.
C4 `delta_report.json` is written before the append. A rebaseline `--commit` also resets 'prev' for ALL KPIs (stated); run it only on an accepted state.
C5 K2 regression: flags identical with no marker; with the marker only 'EnergyIntensity.shoulder: cumulative drift' disappears and gtrClosure is unchanged.
C6 The CHANGELOG states the new baseline half-width is about 1.55 x the old (about 4.19 vs 2.69, from script output), so the sensitivity to a future shift drops; history rows mitigate but do not test for a trend.
Wording: 'monitor reference moved'; never 'resolved' or 'corrected'; nothing implying the 20 kWh/100 km level is established.
