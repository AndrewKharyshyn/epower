#!/usr/bin/env python3
"""M373 (analyses/M373_spec.md Rev 2): stage basis R (the FORMER per-sample raw basis) OUTSIDE the repo, never in raw/ or raw_only/.
For every drive_master key f (both key forms are used by the master): if the canonical key of f is one of the 333 archived lower-precision re-exports
(archived_reexports_sha256.json) the staged file is the archived re-export, else the sha256-verified original from raw_only/. drive_master.csv is copied (MD5 checked).
Hardlinks where possible (same volume), copies otherwise; every staged file is verified by sha256 (333 against reexportSha256, the other 156 against raw_manifest.json).
Usage: python tools/m373_stage_former.py [--dest PATH]   (default: <Investigation>/xtrail-m373-former)"""
import argparse, hashlib, json, os, re, shutil, sys
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
INV = os.path.abspath(os.path.join(ROOT, "..", ".."))
ARCHIVE = os.path.join(INV, "raw_reexports_archived_2026-10-04")
ap = argparse.ArgumentParser()
ap.add_argument("--dest", default=os.path.join(INV, "xtrail-m373-former"))
a = ap.parse_args()
assert os.path.abspath(a.dest).startswith(INV) and not os.path.abspath(a.dest).startswith(ROOT), "stage outside the repo, inside the Investigation folder"

sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
canon_of = lambda name: (lambda d: "%s_%s.csv" % (d[:8], d[8:14]))(re.sub(r"\D", "", name)[:14])
arch = {r["canonical"]: r for r in json.load(open("analyses/F03_originals/archived_reexports_sha256.json", encoding="utf-8"))["files"]}
man = {r["canonical"]: r for r in json.load(open("raw_manifest.json", encoding="utf-8"))["files"] if r.get("role") == "canonical"}
dm = pd.read_csv("drive_master.csv", low_memory=False)
os.makedirs(a.dest, exist_ok=True)
n_re = n_orig = 0
for f in dm["file"]:
    c = canon_of(f)
    dst = os.path.join(a.dest, f)
    if os.path.exists(dst):
        os.remove(dst)
    if c in arch:
        src = os.path.join(ARCHIVE, arch[c]["raw_name"])
        want = arch[c]["reexportSha256"]
        n_re += 1
    else:
        src = os.path.join(ROOT, "raw_only", f)
        want = man[c]["sha256"]
        n_orig += 1
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)
    if sha(dst) != want:
        sys.exit("sha256 mismatch for %s (%s)" % (f, "re-export" if c in arch else "original"))
shutil.copyfile("drive_master.csv", os.path.join(a.dest, "drive_master.csv"))
md5 = hashlib.md5(open(os.path.join(a.dest, "drive_master.csv"), "rb").read()).hexdigest()
assert md5 == hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
res = {"dest": a.dest, "nMasterKeys": int(len(dm)), "nReexports": n_re, "nOriginals": n_orig, "driveMasterMd5": md5}
json.dump(res, open("analyses/M373_stage_former.json", "w", encoding="utf-8", newline="\n"), indent=1)
print(json.dumps(res))
