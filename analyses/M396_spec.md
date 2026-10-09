# M396 spec (pre-registered before the stage is registered): explicit flag when the logger PID polling cadence is slow again

Owner request (2026-10-09, chat): "add the explicit flag to notify me once the PID polling cadence reverts to slow again. I have reactivated fast polling, so it should work on next drives in next ingestion."
Scope: a REPORT-ONLY ingestion stage (`tools/cadence_monitor.py`). No change to the master, any estimator, the regime rule or any payload value.

## Background (script output, cadence_regime.csv)
Median HV-current polling interval per day: 2026-10-01 to 2026-10-07 about 0.82-0.86 s (fast); on 2026-10-08 the first three drives are fast (0.81-0.89 s) and every drive from 10:15 on (12 drives) is 1.35-1.55 s: slower than the earlier
slow regime (about 1.25 s) and labelled 'slow' by the M379a rule (fast: master `I_sample_period_s` < 1.05 s). The column set did not change (about 80 columns incl. fuel rate, throttle, boost, SoC). The owner attributes the change to the app and has
re-activated fast polling (2026-10-09). The single-sample SoC glitch of M388c/M390 sits in the first drive of the new setting (timing consistent with a configuration change; not verified).

## Monitor
State `analyses/cadence_monitor.json` (deterministic, no timestamps): expected regime ('fast', since 2026-10-09, owner), last drive seen (date, time_start, file), its regime, `last_update` and a cumulative `flag_history`.
The first run BOOTSTRAPS on the corpus as it is (baseline = through 2026-10-08_21-24-03; no flags). Every later run looks only at drives after the last seen one (ordered by date, time_start, file):
- `cadence_slow_while_fast_expected` (FLAG): one or more new drives are slow. Reports the first slow drive (file, date, time), the number of slow and fast new drives, the median interval of the slow ones, the reference medians of the fast regime (last 30 fast drives before the batch)
  and of the slow regime (all earlier slow drives), `slower_than_reference_slow` (median > 1.10 x the reference slow median: the 'third setting' seen on 2026-10-08), and the action ("check the app PID / polling settings").
- `fast_polling_confirmed` (info): every new drive with a regime is fast; reports the count and the median interval (the positive confirmation the owner asked for).
- `cadence_unknown` (info): new drives without a regime (fewer than three HV-current samples): not evaluable, never a pass.
A run with no new drives leaves the file untouched (a pipeline rerun cannot erase an alert); a flag enters `flag_history` once per first slow drive; the monitor never stops an ingestion (`main()` prints `monitor_error` and exits 0 on an unexpected failure).

## Surfacing (the owner must be told)
`tools/delta_report.py` gets an informational block `cadenceMonitor` (never in `flags` / `route_to_audit`). The ingestion skill (`.claude/skills/ingest-drive/SKILL.md`, step 7) now makes the FIRST LINE of every ingestion report the cadence status
(fast confirmed or the flag with its details), followed by any `dissipationMonitor` flags. These monitors are report-only, so the agent must read and report them. The stage output prints `FLAG ...` / `INFO ...` lines in the run log.

## Fixed, not tuned
Regime rule (M379a, 1.05 s), 'slower than reference' factor 1.10, reference windows (30 fast / all slow). No dashboard figure. Wording: 'slow while fast polling is expected', never a diagnosis of the cause (the CSVs cannot show whether the app setting, the adapter or the phone changed).

## Gates
Known-answer test `tests/synthetic/test_cadence_monitor.py` (CI): bootstrap without flags; nothing new leaves the file untouched; all-fast batch = confirmation; fast then slow in one batch = the flag with its details; history once; a slow batch at the earlier slow level is flagged but not 'slower'; unknown = info;
ordering independent of sidecar row order; main() never raises. Real-data check: bootstrap on the current sidecar ends at 2026-10-08_21-24-03.
