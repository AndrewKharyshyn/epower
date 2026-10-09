# M388c spec (pre-registered before the code): single-sample SoC spike rejection

Trigger: ingestion M388 (30 drives, Oct 5-8). `2026-10-08_10-14-58.csv` carries ONE SoC sample of 0.0 between readings of 69.5 (raw row index 7032;
trace 60 -> 55 %, real climb to 80 %). Rainflow counted a 70 -> 0 -> 70 swing: `soc_min` 0.0, `rf_dod_max_pct` 80.0 (previous corpus maximum 40.5), corpus
`rfDodHistogram.maxDodPct` 40.5 -> 80.0. A logger glitch, not a battery state. The plausibility gate (GateA2) is flag-only and does not repair.

## Rule (fixed, not tuned)
On the time-sorted SoC samples of a drive, sample `b` with neighbours `a` (previous) and `c` (next) is a spike iff
`|b - a| >= 20 pp` and `|b - c| >= 20 pp` and `|a - c| <= 1.0 pp` (the two neighbours agree within 2 LSB of the 0.5 pp PID resolution).
Spikes are dropped from the SoC series before any use (min/max/band, start/end, rainflow). No interpolation, no other filtering. First and last samples are never spikes.
Shared helper `compute_drive_summary_v6.soc_spike_mask(values)`; applied in `_series(col='soc')` (per-drive master columns) and in the two raw-SoC rainflow
functions of `compute_summary_arrays.py` (rfDodHistogram and its sibling at the second `extract_cycles` site).
Not touched: `m119v2_model.py` (hash-gated, frozen carry-forward), `energy_mc_precompute.py` (uses start/end SoC only), `recon_engine.py`.

## Evidence before the code (script output, scratch: scan of all 554 canonical raw files)
Rule at thresholds 20 / 10 / 5 pp (neighbour tolerance 1.0): exactly 1 sample in exactly 1 file at every threshold (this drive, 69.5 / 0.0 / 69.5). No other drive is affected,
so every pre-existing master row is unchanged (checked again after the change: 0 pre-existing-row diffs).

## Gates
Known answers: synthetic traces (spike, edge sample, two-sample plateau, tolerance edges); on the real drive `soc_min` becomes the minimum of the remaining trace (blind audit: 49.5), `rf_dod_max_pct`
falls to the real range (audit: 30.5), `soc_start/soc_end` unchanged (60 / 55). Audit figures are known-answer targets, never typed into the repo. Corpus: ML16 0/16, 0 pre-existing-row diffs, `rfDodHistogram.maxDodPct` back to a real value.
A second blind audit reproduces the scan and the effect independently. Wording: estimated; the filter is a logger-glitch rejection, disclosed in the CHANGELOG and the data-health note.

## Disclosed limits (blind audit)
About a dozen other arrays readers of raw SoC (context means, bins, hysteresis) still see the 0.0 sample on this one drive (small effect, outside this scope). `m119v2_model.py` frozen; `energy_mc_precompute.py` uses start/end SoC only. No time-gap guard in the rule (no such case in the corpus).
