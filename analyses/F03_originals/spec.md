# F03-originals step 1b spec (pre-registered 2026-10-02, before the run)
Question: does the published master (drive_master.csv MD5 bd9d1072...) reproduce from the recovered ORIGINALS better than from today's raw/?
Design: two full rebuilds with the unchanged versioned builder (master_refit_audit.py), same code, same host, same Python.
 A = raw/ as in the repo (reference run: analyses/M310_refit_audit_489_todays_raw.json, master MD5 then 5197ab6d..; RE-RUN today on the current master so A and B share the comparator).
 B = raw/ with the 333 hash-failing canonical files replaced by their sha256-verified originals (tools/originals_recover.py output). 156 hash-passing files unchanged; auxiliary files unchanged.
Outcomes (fixed in advance): columnsIdentical and nullPatternMismatchFiles for A and B; per-column drift split into the 16 ML/domain columns vs raw-derived columns;
 per-group (hash_fail vs hash_ok vs new) row drift as in refit_provenance_diag; canonical exclusion sets.
Interpretation rule: B reproduces the published master (0 drifted raw-derived columns on hash_fail drives) => published values derive from the originals and raw/ is a lossy re-export.
 B drifts like A => originals do not explain the drift; published values came from yet another source. Partial => report per column group, no tuning.
No data written to raw/, raw_manifest.json or drive_master.csv. Any re-anchoring is Andrii's decision after the Director's ruling.
