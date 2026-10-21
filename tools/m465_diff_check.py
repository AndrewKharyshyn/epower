#!/usr/bin/env python3
"""M465: deep-diff allow-list for the Cold-extension payload changes. Compares a before-snapshot with the live summary_arrays.json: only ADDED keys under the
allow-listed prefixes and the listed leaf-string changes may differ. Usage: python tools/m465_diff_check.py BEFORE.json [AFTER.json]"""
import json, sys
ADD_PREFIXES = ("/fuelWarmup/groups/cold|", "/comparisonCube/urbanContrast/bands[", "/comparisonCube/urbanContrast/descriptive/cold")
CHANGE_OK = {"/comparisonCube/urbanContrast/caveat"}
def walk(a, b, path, out):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) | set(b):
            p = f"{path}/{k}"
            if k not in a:
                out.append(("add", p))
            elif k not in b:
                out.append(("del", p))
            else:
                walk(a[k], b[k], p, out)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            walk(x, y, f"{path}[{i}]", out)
    elif a != b:
        out.append(("chg", path))
def main():
    A = json.load(open(sys.argv[1], encoding="utf-8")); B = json.load(open(sys.argv[2] if len(sys.argv) > 2 else "summary_arrays.json", encoding="utf-8"))
    out = []; walk(A, B, "", out)
    bad = [(k, p) for k, p in out if not ((k == "add" and p.startswith(ADD_PREFIXES) and (p.endswith("/cold") or "/cold|" in p or p.startswith("/comparisonCube/urbanContrast/descriptive/cold"))) or (k == "chg" and p in CHANGE_OK) or p.startswith(("/_artifactStamps/fuelStates/", "/_artifactStamps/fuelWarmup/")))]
    print(json.dumps({"n": len(out), "unexpected": bad[:30], "added": [p for k, p in out if k == "add"][:12]}, indent=1))
    return 1 if bad else 0
if __name__ == "__main__":
    sys.exit(main())
