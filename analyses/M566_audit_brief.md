# M566 blind audit brief (analytical-auditor)

Task: from the RAW CSVs, reproduce for each drive in `analyses/M561_audit_sample.json` (22 drives, `files[].file` = master name, e.g. `20261013_200405.csv` = raw `raw/2026-10-13 20-04-05.csv`) the "upper bracket" of the highest mean power over a window of length W (5, 10, 30, 60, 120 s) lying inside one run of one-direction power. You are blind to the author's code and results.
FORBIDDEN (do not open): `tools/power_duration_uninterrupted.py`, `tests/synthetic/test_power_duration_run_end.py`, `tests/synthetic/test_power_duration_uninterrupted.py`, `analyses/M561_check*.json`, `analyses/M566_check*.json`, `analyses/M566_spec.md`, `duration_cache/` files starting `u561_` or `_u561`, `summary_arrays.json` key `powerDurationUninterrupted`, `STATE.md`, `CHANGELOG.md`, `tools/power_duration.py`, `analyses/M552_*`. Reuse your own M561 audit script `audit/m561_audit.py` as a starting point if you wish (your kernel for the exact window mean). Allowed pairing helper: `tools/energy_packets.py` `pair_stream(df, t)` after `compute_drive_summary_v6._prep_bytes(csv_bytes)`. Set `PYTHONUTF8=1`, `XT_RAW_DIR`.

## Definitions (as in your M561 audit, plus the extension)
Power P(t) piecewise linear between pair-stream samples; a raw step > 5 s is a gap that ends the segment (nothing crosses it). Work with q = P (discharge) or q = -P (charge, reported as a magnitude).
Upper run: take the maximal chains of CONSECUTIVE SAMPLES with q >= 0 (no interpolated zero crossing). Extend each chain on each side to the ADJACENT opposite-sign (q < 0) sample's TIME with the power ramping linearly from the chain's end value to 0 at that time (a knot (t_adjacent, 0)). Do NOT extend when the step to the adjacent sample has zero duration (duplicate timestamp), when the chain's end sample is exactly 0, or at a segment end (first / last sample of the segment, no neighbour). Runs never merge: two chains separated by an opposite-sign sample stay two runs even though their extensions touch at a zero knot. A chain consisting of a single same-sign sample between opposite-sign samples is extended on both sides (a triangle). A run needs at least two knots.
Per drive, W and direction report:
- `upperExact`: the exact continuous-start maximum of the window mean (trapezoid integral / W) over windows lying inside one upper run (candidates: starts where s or s+W meets a knot, the run ends, and the interior vertices of the piecewise-quadratic window mean), `null` if no upper run has length >= W.
- `holdExact`: the same, but the extension keeps the chain's end power CONSTANT to the adjacent opposite-sign sample time (a knot (t_adjacent, q_end)) instead of ramping to 0.
Also per drive and direction: the list of upper run lengths (seconds) for all upper runs of length > 0.
Tolerance for the later comparison: 0.01 kW.

## Return
Write your own script `audit/m566_audit.py` and the result `analyses/M566_audit_result.json`: `{file: {W: {dis: {upperExact, holdExact}, chg: {...}}}, "upperRunLengths": {file: {dis: [...], chg: [...]}}}` with full-precision numbers, plus every rule you found ambiguous. Do not look for or ask for the author's numbers.
