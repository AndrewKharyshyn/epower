"""M377c attribution test (Director ruling 2026-10-05; scratch run, nothing written to the repo tree). Evidence script, not part of the pipeline.
Question: is the per-drive drift of the 257 previous closure IDs (analyses/M377c_identity_drift.json) caused by the master change of the acknowledged M376 recalibration?
Procedure: a scratch git worktree at the post-M376 HEAD (new code, current raw/, current master) in which the master rows of the 257 previous IDs are replaced by their
rows from the pre-M376 master (git blob 7131fb8:drive_master.csv, sha256 517f9660984d6484...; all columns, all other rows unchanged; hybrid sha256 f7360390d8af88564e6b...);
stage_raw; `python tools/gtr_closure_diag.py --ingest` with the identity check against the pinned analyses/M372_closure_perdrive.csv (sha256 2155964f8d66a6aea...).
Result: raw originals 292 / 292 match, flags equal, the identity check PASSED (no differences at 1e-5 on any of the 257 previous IDs; no drift report written); set 292 drives, 54 days.
Reading: with the pre-M376 master values the previous IDs reproduce the pinned file exactly; the drift therefore comes from the master columns changed by the recalibration
(offset and offset-dependent energies), not from code or raw files. Called 'recalibration drift (M376 offset refit)'."""
import os, pandas as pd

S = os.path.dirname(os.getcwd())
old = pd.read_csv(os.path.join(S, "old_master.csv"), dtype=str, keep_default_na=False)
cur = pd.read_csv("drive_master.csv", dtype=str, keep_default_na=False)
prev = set(pd.read_csv("analyses/M372_closure_perdrive.csv")["file"])
assert list(old.columns) == list(cur.columns)
oi = old.set_index("file")
hy = cur.copy()
m = hy["file"].isin(prev)
for c in hy.columns:
    if c != "file":
        hy.loc[m, c] = hy.loc[m, "file"].map(oi[c])
hy.to_csv("drive_master.csv", index=False, lineterminator="\n")
print("hybrid rows replaced", int(m.sum()), "of", len(hy))
