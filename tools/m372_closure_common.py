"""M372 helpers shared by the gtrClosure producers (analyses/M372_spec.md Rev 2). Read-only; imports nothing with side effects (never wire_gtr_seasonal).

check_raw_originals(): every raw file of the closure drives must match raw_manifest.json sha256 BEFORE a run may carry the M366 basis label.
assert_baseline_set(): the eligible set must equal the published M336 set (IDs, days, km) BEFORE any estimate is computed or written.
M372_BASIS is a parameter set only after those checks pass; it is never edited after a run."""
import hashlib, json, os
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE_DIR = os.path.join(ROOT, "analyses", "M372_baseline")
BASE_CSV = os.path.join(BASE_DIR, "M336_closure_perdrive.csv")
M372_BASIS = "raw/ = sha256-verified originals (M366)"


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def check_raw_originals(canon_to_rawname):
    """canon_to_rawname: {canonical key (YYYYMMDD_HHMMSS.csv): file name in raw/}. Raises on any missing manifest record or sha256 mismatch."""
    man = {r["canonical"]: r for r in json.load(open(os.path.join(ROOT, "raw_manifest.json"), encoding="utf-8"))["files"] if r.get("role") == "canonical"}
    bad = []
    for canon, raw in canon_to_rawname.items():
        rec = man.get(canon)
        if rec is None:
            bad.append((canon, "no manifest record"))
        elif sha256(os.path.join(ROOT, "raw", raw)) != rec["sha256"]:
            bad.append((canon, "sha256 differs"))
    if bad:
        raise SystemExit("raw originals check FAILED (%d of %d): %s" % (len(bad), len(canon_to_rawname), bad[:5]))
    return {"nChecked": len(canon_to_rawname), "nMismatch": 0}


def assert_baseline_set(files, dm):
    """files: eligible drive keys of this run; dm: drive_master DataFrame. Raises unless IDs, n days and km equal the published M336 set."""
    base = pd.read_csv(BASE_CSV)
    pub = set(base["file"])
    got = set(files)
    if got != pub:
        raise SystemExit("ID-set mismatch vs published M336 set: only-new %s, only-published %s" % (sorted(got - pub)[:5], sorted(pub - got)[:5]))
    sub = dm[dm["file"].isin(got)]
    n_days, km = int(sub["date"].astype(str).nunique()), round(float(sub["distance_km"].sum()), 1)
    if n_days != int(base["date"].nunique()) or km != round(float(base["km"].sum()), 1):
        raise SystemExit("n days / km mismatch: %s / %s vs published %s / %s" % (n_days, km, int(base["date"].nunique()), round(float(base["km"].sum()), 1)))
    return {"nDrives": len(got), "nDays": n_days, "km": km}
