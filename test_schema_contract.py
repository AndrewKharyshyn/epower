"""
test_schema_contract.py -- P0-3 (audit F-03) schema-contract guard.

Asserts that the columns the versioned core builder actually EMITS, through its
real two stages, are exactly the columns the release master publishes -- no
missing published field, no out-of-band extra. This is the regression test that
would have caught `T1_at_peak_Crate` / `T1_at_peak_Crate_isFallback` being
generated only by an out-of-band probe (c1_joint_temp_crate.py): before P0-3, a
rebuild produced 184 columns while the release published 186.

Builder = two versioned stages:
    stage 1  analyze_bytes(csv_bytes, filename)  -> per-drive row
    stage 2  postprocess_master(dm)              -> ML16 ensemble +
                                                    offset-correction + derived
Running BOTH on a spanning sample of real drives and unioning the resulting
column set is the authoritative "what the public path can regenerate" surface,
so a genuinely new orphan column still fails -- no hand-maintained allowlist.

Exit non-zero on any breach so a release build can gate on it.

Local-run copy: paths are overridable via XT_RAW / XT_MASTER / XT_CODE
(defaults preserve the Project-Knowledge paths).
"""
import os
import sys
import pandas as pd

RAW = os.environ.get('XT_RAW', '/mnt/project')
MASTER = os.environ.get('XT_MASTER', '/mnt/project/drive_master.csv')
SAMPLE_STRIDE = 11

sys.path.insert(0, os.environ.get('XT_CODE', '/home/claude/work'))
import compute_drive_summary_v6 as v6

SUMMARY_STAGE_ALLOW = set()  # columns injected only at summary/crosscheck time

# Columns the versioned builder emits but the RELEASE master deliberately does not yet publish
# (declared, dated, single-purpose -- NOT a general escape hatch). EMPTY since M285c (2026-09-20):
#   highspeed_discharge_longest_run_s_130p (M271 deferral) was published as the 187th master column in the
#   re-baselining milestone (corpus MD5 04cc3f3f... -> cbc206a8..., stamps re-issued; every other column
#   byte-identical, verified by column-drop round trip). Mechanism kept so a future deferral must be declared.
# Fail-closed in both directions: a deferred column that HAS been published must be
# removed from this set (stale allowance), and any other extra column still fails.
DEFERRED_MASTER_COLUMNS = set()


def build_sample_master(files):
    rows = []
    for fn in files:
        try:
            with open(f"{RAW}/{fn}", 'rb') as fh:
                b = fh.read()
        except FileNotFoundError:
            continue
        rows.append(v6.analyze_bytes(b, fn))
    dm = pd.DataFrame(rows)
    dm, _report = v6.postprocess_master(dm, verbose=False)
    return dm


def main():
    published_dm = pd.read_csv(MASTER, low_memory=False)
    published = set(published_dm.columns)
    files = list(published_dm['file'].dropna().unique())[::SAMPLE_STRIDE]

    # A stride sample can miss CONDITIONALLY-emitted columns (e.g.
    # energy_null_reason fires on only 2/367 drives). Guarantee coverage: for
    # every published column, ensure at least one drive that has a non-null
    # value for it is in the sample, so a real "column never emitted" breach is
    # never masked by unlucky sampling.
    fileset = set(files)
    for col in published:
        if col == 'file':
            continue
        nn = published_dm[published_dm[col].notna()]
        if len(nn) and not (set(nn['file']) & fileset):
            carrier = nn['file'].iloc[0]
            fileset.add(carrier)
    files = [f for f in published_dm['file'].dropna().unique() if f in fileset]

    rebuilt = build_sample_master(files)
    emitted = set(rebuilt.columns)
    print(f"sampled {len(files)} drives")
    print(f"rebuilt master emits {len(emitted)} columns (both builder stages)")
    print(f"published master has {len(published)} columns")

    missing = published - emitted - SUMMARY_STAGE_ALLOW
    stale_allow = DEFERRED_MASTER_COLUMNS & published
    deferred_seen = DEFERRED_MASTER_COLUMNS & emitted - published
    extra = emitted - published - DEFERRED_MASTER_COLUMNS

    ok = True
    if missing:
        ok = False
        print("\nFAIL: published columns the versioned builder does NOT emit "
              "(public path cannot regenerate them):")
        for c in sorted(missing):
            print(f"    - {c}")
    if extra:
        ok = False
        print("\nFAIL: builder emits columns absent from the published schema "
              "(undeclared / out-of-band):")
        for c in sorted(extra):
            print(f"    + {c}")

    if stale_allow:
        ok = False
        print("\nFAIL: DEFERRED_MASTER_COLUMNS lists columns that are now published "
              "(remove the stale allowance):")
        for c in sorted(stale_allow):
            print(f"    ~ {c}")
    if deferred_seen:
        print("\nNOTE: builder emits deferred, not-yet-published column(s) "
              "(declared allowance, M271): " + ", ".join(sorted(deferred_seen)))

    if ok:
        print("\nPASS: rebuilt-master columns reconcile exactly with the "
              "published schema (P0-3).")
        assert 'T1_at_peak_Crate' in emitted, "T1_at_peak_Crate not emitted"
        assert 'T1_at_peak_Crate_isFallback' in emitted, \
            "T1_at_peak_Crate_isFallback not emitted"
        print("      T1_at_peak_Crate + isFallback confirmed emitted by the "
              "versioned builder.")
        sys.exit(0)
    sys.exit(1)


if __name__ == '__main__':
    main()
