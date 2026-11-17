#!/usr/bin/env python3
"""M707 (B2): keep the CI master-MD5 anchor in step with drive_master.csv inside the ingestion transaction.

`.github/workflows/ci.yml` pins `verify_import.py --quick --expect-master-md5 <MD5>`. After an ingestion the master changes; a stale anchor passed the static preflight
but turned release_check / release-gate red. The stage `ci_anchor` (right after ingest_core, journaled with everything else, so a rollback restores ci.yml) rewrites exactly
that one MD5 to the MD5 of the staged drive_master.csv. Idempotent; line endings and every other byte of ci.yml are preserved; refuses to run when the anchor line is missing
or occurs more than once (a stop, never a guess).
Usage: python tools/ci_anchor.py [--check] [--root DIR]   (--check: exit 1 if the anchor differs, writes nothing)"""
import argparse, hashlib, os, re, sys

PAT = re.compile(r"(--expect-master-md5\s+)([0-9a-f]{32})")


def md5_of(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


def sync(root, check=False):
    """Returns (changed, old, new). Raises RuntimeError when the anchor is missing or not unique."""
    ci = os.path.join(root, ".github", "workflows", "ci.yml")
    raw = open(ci, "rb").read().decode("utf-8")
    hits = PAT.findall(raw)
    if len(hits) != 1:
        raise RuntimeError("ci.yml must carry exactly one --expect-master-md5 anchor, found %d" % len(hits))
    old, new = hits[0][1], md5_of(os.path.join(root, "drive_master.csv"))
    if old == new:
        return False, old, new
    if not check:
        with open(ci, "wb") as f:
            f.write(PAT.sub(lambda m: m.group(1) + new, raw, count=1).encode("utf-8"))
    return True, old, new


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--root", default=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    a = ap.parse_args(argv)
    try:
        changed, old, new = sync(a.root, check=a.check)
    except RuntimeError as ex:
        print("STOP ci_anchor:", ex)
        return 2
    if a.check:
        print(("FAIL anchor %s != master %s" % (old, new)) if changed else "ok anchor equals master %s" % new)
        return 1 if changed else 0
    print(("updated anchor %s -> %s" % (old, new)) if changed else "anchor already equals master %s" % new)
    return 0


if __name__ == "__main__":
    sys.exit(main())
