"""
project_paths.py -- single source of truth for filesystem locations and the
raw-drive filename classifier (audit Section 8: package hygiene).

Prior state: raw_temp_pass.py, recon_engine.py, c1_joint_temp_crate.py and
fuel_recon.py each hard-coded '/mnt/project' (and one a '/home/claude/work'
output path), and the canonical-filename regex accepted underscore forms only
while the project archive also stores names with a space separator
('20260629 175248.csv'). Result: identical scripts silently processed a
different file population depending on where they were run.

Resolution order (first hit wins), for each location:
  XT_RAW_DIR   / XT_PROJECT_DIR / XT_WORK_DIR   environment variables
  ./ (cwd) if it contains drive_master.csv       (project checkout)
  /mnt/project                                    (legacy sandbox mount)

No import-time side effects other than reading os.environ.
"""
from __future__ import annotations
import os, re

_LEGACY = "/mnt/project"


def project_dir() -> str:
    p = os.environ.get("XT_PROJECT_DIR")
    if p:
        return p
    if os.path.exists(os.path.join(os.getcwd(), "drive_master.csv")):
        return os.getcwd()
    return _LEGACY


def raw_dir() -> str:
    return os.environ.get("XT_RAW_DIR") or project_dir()


def work_dir() -> str:
    p = os.environ.get("XT_WORK_DIR")
    if p:
        os.makedirs(p, exist_ok=True)
        return p
    return os.getcwd()


def with_sep(p: str) -> str:
    return p if p.endswith(os.sep) else p + os.sep


# ---- canonical drive-file classifier --------------------------------------
# Accepted: YYYYMMDD[_ ]HHMMSS.csv   and   YYYY-MM-DD[_ ]HH-MM-SS.csv
_CANON = re.compile(
    r"^(\d{8}[_ ]\d{6}|\d{4}-\d{2}-\d{2}[_ ]\d{2}-\d{2}-\d{2})\.csv$")
# Excluded: e4ORCE exports (any case, '_' or ' ' after prefix) and comparison files
_EXCL_PREFIX = re.compile(r"^e4orce[_ ]", re.IGNORECASE)


def is_canonical_drive(basename: str) -> bool:
    if _EXCL_PREFIX.match(basename) or "_comparison" in basename.lower():
        return False
    return bool(_CANON.match(basename))


def canonical_key(basename: str) -> str:
    """Master key form: separator between date and time is always '_'."""
    return re.sub(r"^(\d{8}|\d{4}-\d{2}-\d{2}) ", r"\1_", basename)


def resolve_raw(fname: str, root: str | None = None) -> str | None:
    """Return the on-disk path for a master 'file' key, tolerating the
    underscore/space separator variants. None if neither exists."""
    root = root or raw_dir()
    cands = [fname]
    if "_" in fname:
        cands.append(re.sub(r"^(\d{8}|\d{4}-\d{2}-\d{2})_", r"\1 ", fname))
    if " " in fname:
        cands.append(canonical_key(fname))
    for c in cands:
        p = os.path.join(root, c)
        if os.path.exists(p):
            return p
    return None
