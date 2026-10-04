#!/usr/bin/env python3
"""M372: replace generatorTractionRecon.gtrClosure by the block regenerated on the originals and drop gtrClosure from staleBlocks (blocks + perBlock).
Refuses unless: analyses/M372_closure_delta.json has no stop trigger (pre-registered rules, analyses/M372_spec.md Rev 2; --accept-triggers only after a Director ruling),
the key set of the regenerated block equals the published one (values only), summary_arrays.json sha256 equals the value recorded at the start of the run, and a deep diff shows that
only /generatorTractionRecon/gtrClosure and /generatorTractionRecon/staleBlocks change. Every number is read from the script-written M372 JSON; nothing is typed.
Usage: python tools/m372_closure_splice.py [--dry-run] [--accept-triggers]"""
import hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
if "--m372" not in sys.argv:
    sys.argv.append("--m372")
import gtr_closure_block as GB

DRY, ACCEPT = "--dry-run" in sys.argv, "--accept-triggers" in sys.argv
delta = json.load(open("analyses/M372_closure_delta.json", encoding="utf-8"))
RULED = {"/scope/publishedRowsWithFgenOne"}      # the ONLY trigger the Director ruled acceptable (M372 trigger ruling: documentation leaf emptied by the M349 repair)
if ACCEPT and {x["path"] for x in delta["stopTriggers"]} - RULED:
    raise SystemExit("--accept-triggers covers only the Director-ruled leaf; other triggers: %s" % [x for x in delta["stopTriggers"] if x["path"] not in RULED])
if delta["stopTriggers"] and not ACCEPT:
    raise SystemExit("stop triggers present (%d): Director ruling required: %s" % (len(delta["stopTriggers"]), delta["stopTriggers"][:3]))
diag = json.load(open("analyses/M372_closure_diag.json", encoding="utf-8"))
raw = open("summary_arrays.json", "rb").read()
if hashlib.sha256(raw).hexdigest() != diag["m372"]["summaryArraysSha256Start"]:
    raise SystemExit("summary_arrays.json changed since the run started")
A = json.loads(raw.decode("utf-8"))
G = A["generatorTractionRecon"]
old_blk = G["gtrClosure"]
new_blk = GB.build()


def keys(o, p=""):
    if isinstance(o, dict):
        return {p + "/" + k for k in o} | {x for k, v in o.items() for x in keys(v, p + "/" + k)}
    if isinstance(o, list):
        return {x for i, v in enumerate(o) for x in keys(v, f"{p}[{i}]")}
    return set()


ALLOWED_NEW = {"/sources/fuelReconMaster", "/sources/fuelReconMaster/path", "/sources/fuelReconMaster/sha256"}   # Director ruling (M372 trigger): record the sha256 of the file the current f_gen values are read from
assert keys(old_blk) <= keys(new_blk) and keys(new_blk) - keys(old_blk) == ALLOWED_NEW, ("key set differs", sorted(keys(old_blk) ^ keys(new_blk))[:5])
new = json.loads(json.dumps(A))
N = new["generatorTractionRecon"]
N["gtrClosure"] = new_blk
sb = N["staleBlocks"]
sb["note"] = sb["note"].replace("not the same for all five", "not the same for all of them").replace("the basis of each block", "the basis of each remaining block")
sb["blocks"] = [b for b in sb["blocks"] if b != "gtrClosure"]
sb["perBlock"] = [p for p in sb["perBlock"] if p["block"] != "gtrClosure"]
assert [p["block"] for p in sb["perBlock"]] == sb["blocks"]


def walk(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            walk(a.get(k), b.get(k), f"{path}/{k}")
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            walk(x, y, f"{path}[{i}]")
    elif a != b:
        assert path.startswith("/generatorTractionRecon/gtrClosure") or path.startswith("/generatorTractionRecon/staleBlocks"), (path, a, b)


walk(A, new)
if DRY:
    print("dry run ok; blocks now", sb["blocks"])
else:
    with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(new, f, ensure_ascii=False, indent=1)
    print("spliced gtrClosure; staleBlocks.blocks =", sb["blocks"])
