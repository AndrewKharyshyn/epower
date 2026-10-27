# M519 spec - close audit R01 and R02 (re-audit 2026-10-26, snapshot M518)

Scope: tooling and wording only. No estimator, payload value, drive_master.csv row or raw file changes. Stop condition: any payload figure other than the stamp fields moves -> stop and escalate.

## R01 (P2) dependency identity can advance without recomputation
Defect: `verify_declared()` did not compare the stored master / input-file identities with live files or the two stored representations (`declaredIdentity`, `upstreamHashes`) with each other; `derive_all()` stamped the live input hash when the producer had not run.
Change:
1. `stamp_common.verify_declared(..., live_master=None, root=None)`: FAIL when declaredIdentity.{corpusHash, configSectionHashes, inputFileMd5} disagree with upstreamHashes, when stamp.corpusHash differs from declaredIdentity.corpusHash, when inputFileMd5 does not cover the declared input files, when the declared master differs from the live drive_master.csv, or when a declared input file md5 differs from the live file. Message says "dependency changed, block not recomputed". release_check passes the live master and root.
2. `stamp_dependencies_apply.derive_all()`: producer did not run and no backfill evidence -> the stamp is re-derived from its PRIOR declaredIdentity (computedAt kept, no lineage entry, in-place restamp overwrites undone); the live-vs-prior difference is reported as `dependencyDrift`. The release gate then fails until the producer runs (ingestion) or replay/attestation evidence is supplied (backfill path unchanged).
Negative controls (tests/synthetic/test_stamp_dependencies.py): false stored input-file hash; false declared master hash; disagreeing representations; input file changed on disk (19.0 -> 19.125 C witness) with no producer run -> identity not advanced, gate fails; real payload verifies against live master and files.

## R02 (P2) matrix summary omits the G2 population exception
Change: `jointMatrixSentence()` states G0/G1 cells = paired set (`pairedSet.nDrives` / `nDays`) and G2 grid-exclusion cells = smaller subset (`pairedSet.g2Subset`), keeps the dependence warning ("dependent, not independent tests"). Bound to S.resistanceJointSensitivity.pairedSet only. New jsdom test `test_power_fade_matrix.js` opens the nested Charts > Power fade view in every cohort mode (added to CI).

## Not in scope
Support-restricted refits, unrounded deltaVsPrimary, other event time bases (audit section 9 item 3): separate milestone, each needs its own spec and blind audit. Winter coverage: not a defect.
