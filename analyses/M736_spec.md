# M736 spec Rev 1: registry v4 for P2 (path-carry bound and offset-adjusted sensitivity)

Written before any v4 code ran and before any winter observation is read. Basis: Director ruling of M735 (`analyses/M735_director_review_M731.json`), note `analyses/M735_note.md`.

## 1. What stays
The v3 primary (`winter_p2_band.realised_band`, vendored engine, S2 with realised month shifts, shift_m = mean(A_day) - normal - BIAS, day bootstrap seed 42, 4000 draws) is called unchanged. Its source file is not edited. Model-derived band; never an ageing estimate.

## 2. What v4 adds (module `tools/winter_p2_v4.py`, scoring `tools/winter_score.py` version 5)
**2.1 Path-carry bound.** b = `maxRelDiffAhLt10` of `analyses/M735_p2_window_check.json` (read from the file, hashed in the registry; 0.01115). The primary window-matched band [lo, hi] is evaluated three ways: as is, shrunk to [lo(1+b), hi(1-b)] (collapsed to its midpoint if it would invert) and widened to [lo(1-b), hi(1+b)]. If the call (within / outside / inconclusive) differs between the three, P2 = "not evaluable (path-carry)".

**2.2 Offset-adjusted sensitivity.** The driver-read ambient is warmer than the engine reconstruction by 1.37 to 3.98 C per month (M735, May-Nov, frozen basis). Offsets O = {0, 1.37, 3.98} C (min and max of the monthly offsets in the M735 file, read from it). For each offset o > 0 the band is recomputed with shift_m reduced by o (implemented by passing normals + o; the S3a/S3b fill of thin months is NOT shifted, disclosed). Verdict: only if the primary call and both sensitivity calls agree; otherwise "not established (ambient-scale sensitive)". Wording: "offset-adjusted sensitivity", never "corrected shift".

**2.3 Order.** Support rule first (10 drives on 5 days; below it nothing is computed). Then the primary; then 2.1; then 2.2. The first reason that applies is reported, all three call sets are listed in the cell (`v4`).

**2.4 Diagnostic (report only, never decides).** The realised shift table (A_day minus normal per window month). It does NOT show a Dec-Feb driver-minus-engine offset: the engine ambient of winter drives is not reconstructed, so that part of the Director condition is only partly met (stated deviation; a frozen report-only reconstruction is a later, separately specified item).

**2.5 Director conditions of the M736 check.** R1: the offset-0 band must equal the v3 realised band to float identity, else P2 = not evaluable. R3: the cell lists the thin (filled) months and flags 'fill not offset-shifted'. Always report the primary call beside the status.

## 3. Checks before the freeze
K1 known answer (stub band): offsets pass through as normals + o; planted agreement gives the verdict, planted disagreement gives "ambient-scale sensitive"; planted band edge within b gives "path-carry". K2 provenance: offsets and b equal the M735 file values. K3 blind audit (analytical-auditor, claim + data path only): reproduces the three band intervals on a planted window frame with the vendored engine. K4 Director check of the registry. The registry sha256 is recorded in the CHANGELOG before any winter read; `winter_score.extractors_frozen` stays fail-closed.

## 4. Not changed
P1 (M732), P3-P7 extractors and the v3 registry file (kept as history; its `--check` leaves CI because `winter_score.py` changes by design).
