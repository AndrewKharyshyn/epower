#!/usr/bin/env python3
"""M471 (audit F01) additive leaf-level splice of the sensitivity `etaBus` column. The O-run (tools/m373_point.py --point O --tag M377) recomputes the sensitivity axes with etaBus as the RATIO OF SUMS
sum(E_gen)/sum(E_fuel); this tool writes ONLY these leaves into summary_arrays.json and refuses (exit 3, nothing written) on anything else:
  generatorTractionRecon.sensitivity[i].etaBus                      (10 axes; axis labels and row key sets must equal the existing ones)
  generatorTractionRecon.refreshedBlocks[*].baseGate.equalsLiveHeadline.etaBus   (the gate record restates the live headline)
  generatorTractionRecon.refreshedBlocks[*].source.{O, scripts}     (the O file's sha256 and the producer script hashes the O file records; simultaneity / speedSplit VALUES are asserted identical)
Stops: O file not the M377 point-O run on the live master; BASE axis (gen100, trac100, fgen, etaBus) != the live headline; any gen100 / trac100 / fgen / nClean of any axis differs from the payload (the f_gen
axis values and the frozen reading-flip acknowledgement must not move); a deep-diff outside the two leaf groups. Usage: python tools/m471_etabus_splice.py [--dry-run]"""
import copy, hashlib, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
OFILE = "analyses/M377_O_blocks.json"      # the standard point-O artifact (python tools/m373_point.py --point O --tag M377), regenerated with the ratio-of-sums etaBus
md5 = lambda p: hashlib.md5(open(p, "rb").read()).hexdigest()


def walk(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            yield from walk(a.get(k), b.get(k), f"{path}/{k}")
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            yield from walk(x, y, f"{path}[{i}]")
    elif a != b:
        yield path


def stop(msg):
    print("STOP:", msg)
    sys.exit(3)


def main(argv):
    p = "summary_arrays.json"
    raw = open(p, encoding="utf-8", newline="").read()
    A = json.loads(raw)
    O = json.load(open(OFILE, encoding="utf-8"))
    if O["meta"].get("tag") != "M377" or O["meta"].get("point") != "O":
        stop("O file is not the M377 point-O run")
    if O["meta"]["driveMasterMd5Before"] != md5("drive_master.csv"):
        stop("O file master MD5 != live master")
    G = A["generatorTractionRecon"]
    axes = O["sensitivity"]["axes"]
    old = G["sensitivity"]
    if [a["axis"] for a in axes] != [r["axis"] for r in old]:
        stop("axis labels differ")
    corp = G["corpus"]
    base = axes[0]
    if (base["gen100"], base["trac100"], base["fgen"], base["etaBus"]) != (corp["generator"], corp["tractionGross"], corp["fGen"], corp["etaBus"]):
        stop(f"BASE axis {base} != live headline {corp}")
    for a, r in zip(axes, old):
        for k in ("gen100", "trac100", "fgen"):
            if a[k] != r[k]:
                stop(f"axis {a['axis']}: {k} {r[k]} -> {a[k]} (only etaBus may move)")
        if "nClean" in r and a.get("nClean") != r["nClean"]:
            stop(f"axis {a['axis']}: nClean changed")
    for blk, key in (("simultaneity", "rows"), ("speedSplit", "bins")):
        if O[blk][key] != G[blk]:
            stop(f"{blk} values differ from the payload (only etaBus may move)")
    B = copy.deepcopy(A)
    for a, r in zip(axes, B["generatorTractionRecon"]["sensitivity"]):
        r["etaBus"] = a["etaBus"]
    osha = hashlib.sha256(open(OFILE, "rb").read()).hexdigest()[:16]
    for rb in B["generatorTractionRecon"].get("refreshedBlocks", []):
        eq = (rb.get("baseGate") or {}).get("equalsLiveHeadline")
        if isinstance(eq, dict) and "etaBus" in eq:
            eq["etaBus"] = corp["etaBus"]
        src = rb.get("source")
        if isinstance(src, dict) and str(src.get("O", "")).startswith("analyses/M377_O_blocks.json sha256 "):
            src["O"] = "analyses/M377_O_blocks.json sha256 " + osha
            src["scripts"] = O["meta"]["scriptSha256"]
    bad = [d for d in walk(A, B) if not (d.startswith("/generatorTractionRecon/sensitivity[") and d.endswith("/etaBus"))
           and not (d.startswith("/generatorTractionRecon/refreshedBlocks[") and (d.endswith("/baseGate/equalsLiveHeadline/etaBus") or "/source/" in d))]
    if bad:
        stop(f"deep-diff outside the allow-list: {bad[:5]}")
    changed = list(walk(A, B))
    print(json.dumps({"changedLeaves": len(changed), "paths": changed, "etaBusAxes": [(a["axis"], r["etaBus"], a["etaBus"]) for a, r in zip(axes, old)]}, indent=1, default=str))
    if "--dry-run" not in argv and changed:
        open(p, "w", encoding="utf-8", newline="").write(json.dumps(B, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
        print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
