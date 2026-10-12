#!/usr/bin/env python3
"""Leaf-level diff of two arrays builds (tools/exposure_control_build.py outputs) for the exposure-basis control build (spec analyses/M413_spec.md gate (e)).
Prints a summary by top-level key and writes the full list of differing leaf paths when --out is given. Exit 0 iff the diff is empty (--expect-null) or always 0 (default).
Lists are compared element-wise by index; a length change is reported as ONE structural difference at the list path (the caller replaces such arrays whole).
Usage: python tools/exposure_control_diff.py A.json B.json [--out FILE] [--expect-null] [--ignore KEY ...]   (--ignore: leaf names skipped, e.g. generatedAt, a wall-clock stamp)"""
import json, math, os, sys


def isnum(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def same(a, b):
    if isnum(a) and isnum(b):
        return (a == b) or (isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b))
    return a == b


IGNORE = set()


def walk(a, b, path, out):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k in IGNORE:
                continue
            if k not in a:
                out.append((path + "/" + k, "only in B", None, None))
            elif k not in b:
                out.append((path + "/" + k, "only in A", None, None))
            else:
                walk(a[k], b[k], path + "/" + k, out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path, "list length %d -> %d" % (len(a), len(b)), None, None))
        else:
            for i, (u, v) in enumerate(zip(a, b)):
                walk(u, v, "%s/%d" % (path, i), out)
    elif not same(a, b):
        kind = "numeric" if isnum(a) and isnum(b) else "value"
        out.append((path, kind, a if not isinstance(a, (dict, list)) else "<%s>" % type(a).__name__, b if not isinstance(b, (dict, list)) else "<%s>" % type(b).__name__))


def diff(A, B):
    out = []
    walk(A, B, "", out)
    return out


def summary(out):
    by = {}
    for p, *_ in out:
        by.setdefault(p.split("/")[1] if p.count("/") else p, 0)
        by[p.split("/")[1] if p.count("/") else p] += 1
    return by


def main(argv):
    IGNORE.update(argv[i + 1] for i, x in enumerate(argv) if x == "--ignore" and i + 1 < len(argv))
    A = json.load(open(argv[1], encoding="utf-8"))
    B = json.load(open(argv[2], encoding="utf-8"))
    out = diff(A, B)
    by = summary(out)
    print(json.dumps({"nDifferingLeaves": len(out), "byTopLevelKey": dict(sorted(by.items(), key=lambda x: -x[1]))}, indent=1))
    if "--out" in argv:
        json.dump([{"path": p, "kind": k, "a": a, "b": b} for p, k, a, b in out], open(argv[argv.index("--out") + 1], "w", encoding="utf-8", newline="\n"), indent=1, default=str)
    return 1 if (out and "--expect-null" in argv) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
