#!/usr/bin/env python3
"""M370 (analyses/M370_spec.md Rev 2, P4): accurate per-block basis labels for the five carried-forward GTR blocks.
The M366 collective note ("computed on the former raw/ re-exports ... not refreshed on the originals") is accurate for gtrClosure only; sensitivity,
simultaneity and speedSplit sit on OLDER DRIVE SETS (M279 / M282 / M255) and crossval on an 82-drive recovered file. Adds generatorTractionRecon.staleBlocks.perBlock
(one entry per block: basis milestone + date, n drives, n days where recorded, raw basis, status, source) and rewrites staleBlocks.note. No number of any block changes.
Every figure is read from the payload or parsed from the CHANGELOG entry named in `source` (asserted); nothing is typed. Deep diff: only /generatorTractionRecon/staleBlocks changes.
Usage: python tools/m370_labels_splice.py [--dry-run]"""
import json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
DRY = "--dry-run" in sys.argv
A = json.load(open("summary_arrays.json", encoding="utf-8"))
G = A["generatorTractionRecon"]
log = open("CHANGELOG.md", encoding="utf-8").read()


def entry(mid):
    m = re.search(r"^## %s \((\d{4}-\d{2}-\d{2})\)(.*?)(?=^## M\d)" % mid, log, re.S | re.M)
    assert m, mid
    return m.group(1), m.group(2)


RAW = "pre-M366 raw/ re-exports"
d279, t279 = entry("M279")
m = re.search(r"(\d+)-fuel / (\d+)-clean drive set", t279)
assert m, "M279 entry no longer states the drive set"
d282, _ = entry("M282")
d255, _ = entry("M255")
d280, _ = entry("M280")
Z = G["gtrClosure"]["scope"]
per = [
    {"block": "gtrClosure", "basisMilestone": "M336", "basisDate": None, "nDrives": Z["nDrives"], "nDays": Z["nDays"], "rawBasis": RAW, "status": "not refreshed on the originals",
     "source": "payload generatorTractionRecon.gtrClosure.scope"},
    {"block": "sensitivity", "basisMilestone": "M279", "basisDate": d279, "nDrives": int(m.group(1)), "nDrivesClean": int(m.group(2)), "nDays": None, "rawBasis": RAW,
     "status": "not refreshed; older drive set than the current headline", "source": "CHANGELOG M279 (drive set statement); n days not recorded"},
    {"block": "simultaneity", "basisMilestone": "M282", "basisDate": d282, "nDrives": int(sum(r["nDrives"] for r in G["simultaneity"])), "nDays": None, "rawBasis": RAW,
     "status": "not refreshed; older drive set than the current headline", "source": "payload generatorTractionRecon.simultaneity (sum of the four drive types); n days not recorded"},
    {"block": "speedSplit", "basisMilestone": "M255", "basisDate": d255, "nDrives": int(max(r["nDrives"] for r in G["speedSplit"])), "nDrivesNote": "largest speed bin", "nDays": None,
     "rawBasis": RAW, "status": "not refreshed; older drive set than the current headline", "source": "payload generatorTractionRecon.speedSplit (largest bin); n days not recorded"},
    {"block": "crossval", "basisMilestone": "M280", "basisDate": d280, "nDrives": G["crossval"]["nDrives"], "nDays": None, "rawBasis": RAW,
     "status": "Path A coefficients unpreserved; not recomputable; pre-M366 basis; not a validation of the current headline",
     "source": "payload generatorTractionRecon.crossval (recovered crossval.csv); n days not recorded"},
]
new = json.loads(json.dumps(A))
S = new["generatorTractionRecon"]["staleBlocks"]
S["note"] = "refresh pending (spec analyses/M370_spec.md); the basis of each block is stated separately because it is not the same for all five"
per.sort(key=lambda p: S["blocks"].index(p["block"]))     # payload order
S["perBlock"] = per
assert [p["block"] for p in per] == S["blocks"]


def walk(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            walk(a.get(k), b.get(k), f"{path}/{k}")
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            walk(x, y, f"{path}[{i}]")
    elif a != b:
        assert path.startswith("/generatorTractionRecon/staleBlocks"), (path, a, b)


walk(A, new)
if DRY:
    print(json.dumps(per, indent=1))
else:
    with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(new, f, ensure_ascii=False, indent=1)
    print("spliced staleBlocks.perBlock (%d entries)" % len(per))
