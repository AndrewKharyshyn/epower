# M416 spec (Rev 1): journaled release for the stage runner (audit F20, owner decision 2026-10-12)

Status: tooling milestone (no figure, payload, dashboard or master change). Branch `claude/next-milestone` from `main` (390ea99, M415). Origin: deep audit 2026-10-11 F20 ("sequential writes can publish mixed versions"; `ingest_core` has per-file tmp + `os.replace` and gate backups, `run_ingest` had no downstream rollback), FEASIBILITY.md row F20, owner direction 2026-10-12 ("F20/F11 - OK", read as the recommendation: journaled swap now, release directories after MIGRATION.md).

## Design
- **Snapshot.** Before the first stage the whole working tree outside the excluded directories (`.git`, `node_modules`, `runs`, `raw`, `raw_only`, `raw_cache`, `drive_raw_cache`, `capacity_cache`, `audit`, `tabtext`, caches) is hashed (sha256) and copied to `runs/<ts>/journal/files/` (files above 30 MB are hashed only). On the real tree: 858 files, 208 MB hashed, 67 MB copied, about 3.4 s. The snapshot covers every file a stage may write, declared or not.
- **Commit.** A fully green run records its write set (changed / created / deleted) and the undeclared writes (files outside the declared stage outputs) in `journal.json`, deletes the copies and releases the lock.
- **Rollback.** A failed gate, an exception, SIGINT or SIGTERM restores every changed file (temp file + `os.replace`), removes created files, re-creates deleted files, then re-hashes the whole tree against the snapshot: `rolled_back` only if every hash equals; otherwise `rollback_failed` with the mismatches (exit 4). A file above the copy cap that changed cannot be restored and is reported as such.
- **Interrupted run.** A hard kill leaves the journal `started` and `runs/.release.lock`; the next run refuses to start (exit 5) until `run_ingest.py --recover` rolls the tree back from the journal. A live second release is refused while the lock holder is running.
- **Flags.** `--keep-on-failure` leaves the mixed state for inspection (journal stays open); `--no-journal` disables the mechanism (development only).
- **Always-run integrity.** The commit happens only after the final stages (build, jsdom, `release_check`, state) are green; a green status file alone is not the commit condition, the journal state is. `RF.plan` (fingerprint) is now computed only when `--skip-unchanged` is requested (behaviour unchanged otherwise).

## Not covered (disclosed)
- `raw/` is never modified by a rollback (raw originals are never deleted); raw files added by a failed run are listed in `status.json` (`journal.rawAdded`) and picked up as new files by the next ingestion.
- There is still no single-pointer release directory (blocked by the flat-tree rule in MIGRATION.md): readers can see the mixed state during a run; the lock file and the journal mark that window. A release-directory layout stays a separate decision after the reproduction test in MIGRATION.md.
- Files outside the snapshot (the excluded directories) are not rolled back; the caches are regenerable and `runs/` holds the logs.

## Tests (`tests/synthetic/test_release_journal.py`, in CI)
Throw-away tree with copies of the runner, the journal and a three-stage list: green run commits with the exact write set and undeclared writes; an injected failure at each of the three stages restores the previous file set byte-identically (and a second attempt is accepted); raw files added by a failing run are reported and kept; a killed runner leaves an open journal, the next run is refused (exit 5), `--recover` restores the tree; `--keep-on-failure` keeps the mixed state and blocks the next run until `--recover`; a live lock holder blocks a second release; `--no-journal` leaves the mixed state; a rollback that cannot restore is `rollback_failed` (verification is by re-hashing) and retry succeeds; the snapshot excludes `raw/` and `runs/`.

## Acceptance
Failure-injection tests green; existing runner tests green; `release_check.py` and CI green; CHANGELOG `M416`; no figure changes. The first real ingestion after this milestone reports its undeclared writes in `status.json`; those are added to the declared outputs in a follow-up (informational, not blocking).
