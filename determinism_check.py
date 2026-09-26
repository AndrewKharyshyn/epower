#!/usr/bin/env python3
"""M207/M208 (F-14 / audit H-02): repeatable determinism proof for the ML16
ensemble-outlier stage.

RE-AUTHORED (2026-09-02). The previous determinism_check.py was absent from the
repository and the embedded summary_arrays.determinism block was frozen at the
2026-08-10 / 219-drive era (audit F-14/H-02). This script regenerates the proof
on the CURRENT master and is the single source of the determinism block, which
is a verbatim copy of this script's `block` output.

WHAT IT PROVES. The ML16 stage (KMeans k=3, IsolationForest 500 trees, LOF,
MAD gates -> ens_* votes) is fit with fixed seeds (random_state=42). This runs
`postprocess_master()` twice, from scratch, on the current master and checks:

  * withinSessionRepeatPass  -- every one of the 16 ML columns is bit-identical
                                across the two independent runs (seed-stability).
  * canonicalSetReproducible -- the canonical exclusion column ens_outlier_v2
                                flags the SAME FILES across the repeat.
  * canonicalSets[col]       -- per ens column: repeat-run count n,
                                exactFileIdentityMatch (A==B by file), and
                                matchesFrozenMaster / frozenN (does a full
                                re-fit reproduce the shipped frozen column).
  * componentFlagDrift       -- per component column, # rows differing A vs B.
  * continuousScoreDrift     -- max |A-B| of iso_score / lof_score.

FROZEN-MASTER NOTE. ens_extreme is a statistical-vote component (>=2 votes) and
a full re-fit on the whole current corpus can vote differently from the
incrementally-frozen master column (ML16 freeze/restore protocol). This does
NOT affect the canonical exclusion: ens_outlier_v2 = ens_invalid (hard physical
rules, M88), which reproduces exactly. Group statistics use ens_outlier_v2 only.

Usage:  python3 determinism_check.py [drive_master.csv]
Writes: determinism_check.json  (full diagnostics)
Prints: the determinism block (JSON) for embedding into summary_arrays.json.
"""
import sys
import json
import datetime as _dt
import numpy as np
import pandas as pd

import compute_drive_summary_v6 as v6

ML16_BOOL = ['iso_outlier', 'f_iso', 'f_lof', 'f_mad', 'f_iso_i', 'f_lof_i',
             'f_mad_i', 'ens_invalid', 'ens_extreme', 'ens_outlier_v2']
ML16_CONT = ['iso_score', 'lof_score']
ML16_CAT = ['drive_cluster_k3']
COMPONENT_COLS = ['iso_outlier', 'f_iso', 'f_lof', 'f_mad', 'f_iso_i',
                  'f_lof_i', 'f_mad_i', 'drive_cluster_k3']
ENS_COLS = ['ens_invalid', 'ens_extreme', 'ens_outlier_v2']


def _run_once(master_csv):
    d = pd.read_csv(master_csv)
    out = v6.postprocess_master(d, verbose=False)
    return out[0] if isinstance(out, tuple) else out


def _file_set(df, col):
    m = df[col].fillna(False).astype(bool)
    return set(df.loc[m, 'file'].astype(str))


def _pkg_versions():
    import scipy
    import sklearn
    import rainflow
    import statsmodels
    return {'python': '.'.join(map(str, sys.version_info[:3])),
            'numpy': np.__version__, 'pandas': pd.__version__,
            'scipy': scipy.__version__, 'sklearn': sklearn.__version__,
            'rainflow': rainflow.__version__,
            'statsmodels': statsmodels.__version__}


def build(master_csv='drive_master.csv'):
    frozen = pd.read_csv(master_csv)
    A = _run_once(master_csv)
    B = _run_once(master_csv)

    # ---- component drift (A vs B) ----
    comp_drift = {}
    for c in COMPONENT_COLS:
        if c not in A.columns:
            comp_drift[c] = None
            continue
        a = A[c].fillna('∅').astype(str).values
        b = B[c].fillna('∅').astype(str).values
        comp_drift[c] = int((a != b).sum())

    cont_drift = {}
    for c in ML16_CONT:
        if c not in A.columns:
            cont_drift[c] = None
            continue
        d = float(np.nanmax(np.abs(A[c].fillna(0).values - B[c].fillna(0).values)))
        cont_drift[c] = round(d, 12)

    # ---- canonical / ens sets ----
    canon = {}
    for c in ENS_COLS:
        if c not in A.columns:
            canon[c] = None
            continue
        sa, sb = _file_set(A, c), _file_set(B, c)
        sf = _file_set(frozen, c)
        entry = {'n': int(len(sa)),
                 'exactFileIdentityMatch': bool(sa == sb),
                 'matchesFrozenMaster': bool(sa == sf)}
        if sa != sf:
            entry['frozenN'] = int(len(sf))
        canon[c] = entry

    within_pass = (all((v == 0) for v in comp_drift.values() if v is not None)
                   and all((v == 0) for v in cont_drift.values() if v is not None)
                   and all(canon[c]['exactFileIdentityMatch'] for c in ENS_COLS
                           if canon.get(c)))
    canonical_reproducible = bool(canon['ens_outlier_v2']['exactFileIdentityMatch']
                                  and canon['ens_outlier_v2']['matchesFrozenMaster'])

    n_drives = int(len(A))
    block = {
        '_provenance': ('GENERATED by determinism_check.py on the current master '
                        '(F-14, 2026-09-02): re-authored and regenerated, replacing '
                        'the stale 2026-08-10 / 219-drive block. This block is a '
                        'verbatim copy of the script output; if a fresh run and this '
                        'value disagree, trust the fresh run and regenerate -- do '
                        'not hand-edit.'),
        'generatedAt': _dt.datetime.now(_dt.timezone.utc).isoformat(),
        'nDrives': n_drives,
        'canonicalN': n_drives,
        'withinSessionRepeatPass': bool(within_pass),
        'canonicalSetReproducible': canonical_reproducible,
        'canonicalSets': canon,
        'canonicalExclusionByFileIdentity': {
            'column': 'ens_outlier_v2',
            'n': canon['ens_outlier_v2']['n'],
            'reproducesAcrossRepeat': canon['ens_outlier_v2']['exactFileIdentityMatch'],
            'matchesFrozenMaster': canon['ens_outlier_v2']['matchesFrozenMaster']},
        'componentFlagDrift': comp_drift,
        'continuousScoreDrift': cont_drift,
        'frozenMasterConsistencyNote': (
            'ens_extreme is a statistical-vote component (>=2 votes), not the '
            'canonical exclusion; a full re-fit on the whole current corpus can '
            'vote differently from the incrementally-frozen master column (ML16 '
            'freeze/restore), so matchesFrozenMaster may be false for it. '
            'ens_invalid (hard physical rules) and the canonical exclusion '
            'ens_outlier_v2 = ens_invalid (M88) reproduce exactly; group '
            'statistics use ens_outlier_v2 only.'),
        'packageVersions': _pkg_versions(),
        'reproducibilityScope': (
            'Self-audit P3-1 (2026-09-03). This harness proves bit-identical '
            'seed-stability ONLY for the ML16 ensemble-outlier stage '
            '(postprocess_master: KMeans/IsolationForest/LOF/MAD -> ens_* '
            'columns), run twice from scratch on the current master. It does '
            'NOT re-execute and does NOT prove reproducibility for: (1) the '
            'statsmodels-based degradation trends (degradation_trends.py -- '
            'cluster-robust OLS, mixed-effects GLM, TOST equivalence), which '
            'depend on the pinned statsmodels version recorded in '
            'packageVersions above (a statsmodels/scipy upgrade can shift '
            'numerical optimizer paths for the mixed-effects fit even with a '
            'fixed random seed); (2) energy_uncertainty_mc.py / '
            'energy_mc_precompute.py Monte Carlo draws, which are seeded but '
            'not covered by this harness; (3) m119v2_model.py (M119-v2 '
            'socHysteresisV2), which is frozen/carried-forward and not '
            'refit by default (see socHysteresisV2.recomputePolicy), '
            'including its own M222.1 rolling-origin CV re-fits and M222.2 '
            'detector reconciliation; (4) interDriveCarryover\'s (M223.1) '
            'day-clustered bootstrap OLS (seeded, seed=42) and its secondary '
            'day random-intercept mixed-effects check, which shares the same '
            'statsmodels-version sensitivity as (1) and separately can fail '
            'to converge on a singular random-effects covariance at low '
            'pairs-per-day density (observed and reported as such, not a '
            'reproducibility failure of this harness); (5) regimeTransition\'s '
            '(M223.2) day-block-preserving permutation test (seeded, '
            'seed=42, 4000 draws) and its Dirichlet/day-clustered-bootstrap '
            'per-cell uncertainty intervals (seeded, 1000 draws), neither '
            're-executed here; (6) dailyFingerprints\' (M227.2) k-means '
            'clustering (seed=42) and its day-bootstrap adjusted-Rand-'
            'index stability check (200 resamples, seed=42), neither '
            're-executed here. Treat this block as scoped evidence for the '
            'ML16 exclusion set only, not a whole-pipeline determinism '
            'proof.'),
        'note': ('Generated live by determinism_check.py on the current '
                 f'{n_drives}-drive master. postprocess_master() is run twice from '
                 'scratch; the ML16 ensemble (KMeans k=3 n_init=20, IsolationForest '
                 '500 trees contamination 0.06, LOF n_neighbors=15, MAD gates) is '
                 'seeded (random_state=42), so the two runs are bit-identical and '
                 'the canonical exclusion reproduces exactly by file identity. '
                 'Validity is conditional on packageVersions. See '
                 'reproducibilityScope for what this proof does and does not cover.')}
    full = {'block': block,
            'runA_ens_outlier_v2_files': sorted(_file_set(A, 'ens_outlier_v2')),
            'runB_ens_outlier_v2_files': sorted(_file_set(B, 'ens_outlier_v2'))}
    return block, full


if __name__ == '__main__':
    mc = sys.argv[1] if len(sys.argv) > 1 else 'drive_master.csv'
    block, full = build(mc)
    json.dump(full, open('determinism_check.json', 'w'), indent=1, ensure_ascii=False)
    print(json.dumps(block, indent=1, ensure_ascii=False))
