"""eligibility.py (M375, analyses/M375_spec.md Rev 2): the ONE definition of canonical-clean eligibility for the GTR family (headline, sensitivity, simultaneity, speedSplit).

Standing rule (CLAUDE.md): the canonical exclusion is ens_outlier_v2 (== ens_invalid); energy rates use canonical-clean eligibility. A drive is excluded when EITHER flag is explicitly True
(the existing convention of cohort_arrays.py, M295). The single flag source is drive_master.csv (seasonal_drive_master.csv carries no outlier column). For every fuel-instrumented row the
flag must be present: a missing flag after the join, a duplicated drive_master row or a disagreement between ens_invalid and ens_outlier_v2 is a STOP (EligibilityError), never treated as clean.
"""
import pandas as pd


class EligibilityError(RuntimeError):
    pass


def _true(v):
    return str(v).strip().lower() == "true"


def load_flags(path="drive_master.csv"):
    """drive_master flags: DataFrame(file, ens_outlier_v2, ens_invalid); asserts one row per drive."""
    d = pd.read_csv(path, usecols=["file", "ens_outlier_v2", "ens_invalid"], low_memory=False)
    if d["file"].duplicated().any():
        raise EligibilityError("duplicated drive_master rows: %s" % d.loc[d["file"].duplicated(), "file"].tolist()[:5])
    return d


def excluded_files(flags, files):
    """Set of `files` (fuel-instrumented drives) excluded by the canonical rule. Raises EligibilityError on a missing row, a missing ens_outlier_v2 flag or a flag disagreement."""
    files = list(files)
    if len(set(files)) != len(files):
        raise EligibilityError("duplicated fuel rows")
    f = flags.set_index("file")
    missing = [x for x in files if x not in f.index]
    if missing:
        raise EligibilityError("fuel drives without a drive_master row: %s" % missing[:5])
    sub = f.loc[files]
    nan_flag = sub.index[sub["ens_outlier_v2"].isna()].tolist()
    if nan_flag:
        raise EligibilityError("missing ens_outlier_v2 flag for fuel drives (never treated as clean): %s" % nan_flag[:5])
    both = sub.dropna(subset=["ens_invalid"])
    dis = both.index[both["ens_invalid"].map(_true) != both["ens_outlier_v2"].map(_true)].tolist()
    if dis:
        raise EligibilityError("ens_invalid and ens_outlier_v2 disagree: %s" % dis[:5])
    return {x for x in files if _true(sub.loc[x, "ens_outlier_v2"]) or _true(sub.loc[x, "ens_invalid"])}


def canonical_clean(files, flags=None, path="drive_master.csv"):
    """`files` (order kept) without the canonical exclusions, after the stop checks."""
    flags = load_flags(path) if flags is None else flags
    files = list(files)
    ex = excluded_files(flags, files)
    return [x for x in files if x not in ex]
