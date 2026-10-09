# M390 spec (pre-registered before the apply): SoC glitch rejection extended to every cached-frame reader, with a short-side time guard

Follows M388c (analyses/M388c_spec.md; Director). M388c covered the per-drive master columns and the two raw-SoC rainflow functions and disclosed three limits:
about a dozen other arrays readers of raw SoC still saw the 0.0 sample on the one affected drive, and the rule had no time guard. This milestone closes both.

## Correction found while preparing M390 (disclosed)
The first timing scan used for the guard design divided a pandas-3 `datetime64[us]` integer by 1e9 and so understated every SoC interval by 1000x (it suggested the
glitch sat inside a 0.047 s window). Re-measured with explicit units (`total_seconds`): consecutive SoC intervals have median 1.16 s, p99 2.47 s, p99.9 4.1 s; 22 intervals exceed 60 s
(max 1791.7 s). The one glitch (`2026-10-08 10-14-58`, 69.5 / 0.0 / 69.5) comes 45.8 s after the previous SoC sample (a PID dropout) and the next sample returns after 1.6 s.
A guard on the whole neighbour span (first draft: 5 s) would therefore never have flagged the real glitch; it was replaced by the short-side form below before any apply.

## Rule (fixed, not tuned; `soc_spike.py`)
Sample b with time-ordered neighbours a, c is a spike iff |b-a| >= 20 pp, |b-c| >= 20 pp, |a-c| <= 1.0 pp (unchanged from M388c) AND
min(t_b - t_a, t_c - t_b) <= 5 s (new). Reason: a move of >= 20 pp within 5 s implies about 300 kW on the 2.1 kWh pack (`CAP_KWH` is verified:false; the statement is an order-of-magnitude
bound against the 150 kW motor rating, also unverified), so it is not a battery state; a spike whose BOTH sides are long gaps is not flagged (a genuine excursion hidden by a logging gap stays).
Non-monotonic times (midnight roll-over of HH:MM:SS strings) fail the guard. First and last samples are never spikes. 5 s is about 4x the median SoC interval; the corpus result does not depend on it
(the single match has a 1.6 s short side).

## Scope
1. `soc_spike.py` (new, numpy/pandas only): `soc_spike_mask(v, t)`, `despike_frame(df)` (flagged cell -> NaN, row alignment kept, input untouched, same object returned when nothing is flagged).
2. `compute_drive_summary_v6.py`: `_series(col='soc')` passes times (per-drive master columns; identical result for the one drive: the master row is unchanged).
3. `compute_summary_arrays.py`: the two rainflow functions pass times.
4. `drive_raw_cache.make_frame_loader._load` returns `despike_frame(payload['df'])`: every cached-frame reader of SoC (context means, bins, hysteresis, ceilings, windows) now sees the glitch as missing.
Not touched: `m119v2_model.py` (frozen, hash-gated), `energy_mc_precompute.py` (start/end SoC only), `recon_engine.py`. Readers that parse raw bytes themselves (not via the frame loader) are listed by the audit and stay disclosed.

## Evidence before the apply (script output)
Loader over all 554 cached frames: exactly 1 cell changed, in `2026-10-08_10-14-58.csv`; no other column differs, no other frame changes.

## Gates
Known-answer test `tests/synthetic/test_soc_spike.py` (CI). Blind audit: reproduce the interval statistics and the match count independently, review the patch, enumerate the raw-byte readers not covered.
Apply: master unchanged (0 row diffs), fresh arrays build (`tools/m388c_rebuild_arrays.py`) then the stages from `stage_raw`; diff of the payload against the pre-M390 payload must be confined to blocks that read SoC
on the one drive (report every changed top-level key); `release_check.py` green.
Wording: estimated; rejection of a logger artefact, not a correction of study figures.
