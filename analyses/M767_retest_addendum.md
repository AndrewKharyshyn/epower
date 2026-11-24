# M767 tool Rev 3 addendum: retest mode of `tools/dem_grade_shares.py` (spec M746 Rev 5, section 10; written before any retest on a later master)

Scope: tooling only. No estimand, class edge, mask, exclusion, bootstrap (seed 42, 4000 draws, calendar-day resampling), floor or decision rule changes. The registered result `analyses/M767_grade_class_shares.json` (sha256 b86d3aac..., master d514d600..., 717 drives) is never written by a retest.

1. `--retest` accepts a master whose MD5 differs from `PINNED_MD5`; registered mode (no flag) still stops with exit 1 on a different master and writes nothing (M746 8.1; test).
2. A retest refuses `--out-dir` equal to `analyses/` and writes ONE file `grade_shares_retest.json` into the given directory (the wrapper promotes it to `analyses/cloud_retests/grade_shares_<master md5 first 8>/`).
3. Nested control (Director ruling, 10.4): the first 717 canonical files of the master must equal the registered set (sha256 of the sorted names `65878488...e2e0a8`); their steps must reproduce M762 C1 stage counts and C6 FABDEM step shares and misclassification with tolerance 0 (`control_r1`). New drives are added on top. A failed control stops (exit 3) and writes nothing.
4. The result carries `retest: true`, `registeredMd5`, `masterMd5`, `drives`, `nestedControl`, `retestLabel` ("retest on N drives (master MD5 xxxxxxxx...)") and a scope note: descriptive monitoring, no confirmatory reading, M726 not read by the winter session. Aggregates only; the M767 privacy scan runs.
5. Known-answer (M746 8.6): a retest on the pinned master reproduces the registered E1, E3, E4 numbers byte-identically apart from label fields (`milestone`, `spec`, `toolSha256`, `seconds`, `retest*`, `registered*`, `nestedControl`, `drives`).
6. `tools/dem_crosscheck.py` is called, not modified; a test records its sha256 and the stage checks it is unchanged.
