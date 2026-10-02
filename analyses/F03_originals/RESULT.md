# F03-originals step 1b result (2026-10-02, read-only; spec.md pre-registered before the run)
Comparator: published master bd9d1072... (489 rows). Builder: unchanged master_refit_audit.py; Python 3.12.
| run | columns identical /186 | drifted | null-pattern mismatch files |
|---|---|---|---|
| A: raw/ as in repo | 69 | 117 | 10 |
| B: 333 hash-failing files replaced by sha256-verified originals | 161 | 25 | 3 |
G1 per-group drift, raw-derived non-ML columns (B_groups.json): hash_fail (333 drives) 0 columns drift; new (43) 0; hash_ok (113) only distance_km on 1 row (documented M286 repair).
Residual 25 drifted columns in B are ML16 / corpus-level refit outputs (iso/lof scores, ens_*, offset_2p cascade, cell_spread_adj_hub); ML16 drift is also present on the 43 new drives whose raw is hash-verified, so it is independent of raw content.
G2a determinism: two independent B rebuilds are identical (whole frame). Python 3.11 / frozen-historic-fit attribution NOT done.
G3: 333 failing now = 489 canonical - 156 hash-passing; CLAUDE.md "335/457" is the older corpus count (not a missing file).
Open: G2b (py3.11 env), G4 blind audit (also against 0bcfc400), arrays/dashboard not rebuilt, ledger re-ruling (needs per-row Director pass), Andrii sign-off.
Director ruling (a7b27969...): decision "revise"; allowed wording: "consistent with the published raw-derived per-drive values deriving from the sha256-verified originals; the archived raw/ copies of 333 files are lower-precision re-exports". Not "proven" / "reproducible from raw data" / "corrections". Keep CLAUDE.md/dashboard F03 wording until G1-G4 pass. Prefer originals as a second sha256-manifested archive; swapping raw/ only by Andrii after G1-G4 and a no-new-drive arrays control build.

## G4 blind audit (analytical-auditor, claim + data paths only; G4_audit/brief.json, results.json)
- 333/333 originals match raw_manifest sha256; 333/333 raw/ copies fail it.
- 41 sampled hash-failing drives (+10 hash-passing controls): original vs published = 0 mismatches (72-156 non-ML, non-corpus columns per drive, tol 1e-9), against both master bd9d1072 (489 rows) and the older master 0bcfc400 (commit 23d0397, 446 rows).
- raw/ copy vs published: 36/41 drives mismatch (1,496 cells, 80 columns; most often ev_dist_scale_k, gross_discharge/charge_kwh, net_draw_kwh, gtc, fce, peak_I_*). 5/41 match: Sep 4-17 drives. Checked by author: for those the raw/ vs original differences are only 2-13 GPS Latitude/Longitude cells (not used in the derived columns), so the hash fails but derived values are unchanged. Roughly 12% of the 333 may be value-neutral if the sample is representative.
- No column matches on raw/ but fails on the original. Verdict: supports (qualification: "raw/ copies do not reproduce" is true for ~88% of sampled drives, not all).
- Limits: sample not all 333; postprocess-only columns not compared; ML columns excluded.

## G2b Python 3.11.15 (2026-10-02)
Isolated env outside the repo (uv-installed CPython 3.11.15 + requirements.pinned.txt; scratchpad, not persisted). Rebuild B under 3.11.15 (B_originals_py311.json) is identical to the 3.12 run:
161 identical / 25 drifted columns, same per-column row counts, same exclusion sets and null-pattern files. The interpreter version is not the cause of the ML drift; with
G2a (deterministic) and the 43 hash-verified new drives (same ML drift), the residual is the frozen historic ML16 fit, not raw content. All gates G1-G4 passed.
Side effect to know: uv placed a python3.11 shim in C:/Users/AndriiKharyshyn/.local/bin (outside the repo; removable).
