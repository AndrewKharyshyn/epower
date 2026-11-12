#!/usr/bin/env python3
"""M594 (audit D11): ONE release identity written from disk: master MD5, sha256 of the code and payload files, payload block count,
CHANGELOG head milestone, git head. Dated standalone artifacts (determinism_check.json for 446 drives, raw_manifest.json note) are historical
and are NOT rewritten here; this file is the as-of reference for the current archive. Usage: python tools/release_identity.py [--check]"""
import argparse, hashlib, json, os, re, subprocess, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FILES = ["drive_master.csv", "summary_arrays.json", "cohort_arrays.json", "summary_config.json", "xtrail_summary.jsx", "compute_summary_arrays.py", "xtrail_dashboard.html"]


def digest(p, algo):
    h = hashlib.new(algo)
    with open(os.path.join(ROOT, p), "rb") as f:
        for ch in iter(lambda: f.read(1 << 20), b""):
            h.update(ch)
    return h.hexdigest()


def build():
    arrays = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
    head = None
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        for line in f:
            m = re.match(r"## (M\d+[a-z]?) \((\d{4}-\d{2}-\d{2})\)", line)
            if m:
                head = {"milestone": m.group(1), "date": m.group(2)}
                break
    try:
        git = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except Exception:
        git = None
    meta = arrays.get("meta", {})
    try:                                                    # M621 (P-01): raw-corpus fingerprint kept apart from the master CSV digest
        rm = json.load(open(os.path.join(ROOT, "raw_manifest.json"), encoding="utf-8"))
        raw = {"snapshotId": rm.get("snapshotId"), "manifestSha256": digest("raw_manifest.json", "sha256")}
    except Exception:
        raw = None
    return {"changelogHead": head, "gitHead": git, "payloadBlocks": len(arrays), "totalDrives": meta.get("totalDrives"), "dateRange": meta.get("dateRange"),
            "masterMd5": digest("drive_master.csv", "md5"), "rawCorpus": raw,
            "sha256": {p: digest(p, "sha256") for p in FILES if os.path.exists(os.path.join(ROOT, p))},
            "historicalArtifacts": {"determinism_check.json": "446-drive standalone artifact, historical", "raw_manifest.json note": "describes the 446-drive snapshot, historical"}}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--check", action="store_true"); a = ap.parse_args()
    blk = build(); out = os.path.join(ROOT, "release_identity.json")
    if a.check:
        cur = json.load(open(out, encoding="utf-8")) if os.path.exists(out) else {}
        bad = [k for k in ("masterMd5", "payloadBlocks", "sha256", "rawCorpus") if cur.get(k) != blk[k]]
        print("release_identity stale: %s" % bad if bad else "release_identity current"); sys.exit(1 if bad else 0)
    json.dump(blk, open(out, "w", encoding="utf-8", newline="\n"), indent=1, sort_keys=True); print("wrote release_identity.json", blk["changelogHead"], blk["payloadBlocks"])
