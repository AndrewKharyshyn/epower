#!/usr/bin/env python3
"""M491 isolation diff (spec analyses/M491_spec.md Rev 2, acceptance A / amendment A5): compares the payload before and after the comparison-cube run and fails if any leaf other than the registered ones changed or appeared.
Registered under /comparisonCube/urbanContrast/bands[i]/difference/: ci95 (value), method (text), the new ci95IndependentCohorts, ci95Stratified, nSharedDates, nUnionDates, bootstrapCorrelation, nDrawsDropped, nDrawsDroppedStratified, seed, B;
and /comparisonCube/_meta/contrastUncertainty (new); the comparisonCube artifact stamp may be re-issued. Usage: python tools/m491_diff_check.py BEFORE.json [AFTER.json=summary_arrays.json]"""
import json, re, sys

ALLOWED_CHANGE = re.compile(r"^/comparisonCube/urbanContrast/bands\[\d+\]/difference/(ci95|method)(\[\d+\])?$")
ALLOWED_ADD = re.compile(r"^/comparisonCube/urbanContrast/bands\[\d+\]/difference/(ci95IndependentCohorts|ci95Stratified|nSharedDates|nUnionDates|bootstrapCorrelation|nDrawsDropped|nDrawsDroppedStratified|seed|B)(\[\d+\])?$|^/comparisonCube/_meta/contrastUncertainty$")
STAMP = "/_artifactStamps/comparisonCube"


def leaves(o, p=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from leaves(v, p + "/" + k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from leaves(v, "%s[%d]" % (p, i))
    else:
        yield p, o


def main(argv):
    a = dict(leaves(json.load(open(argv[1], encoding="utf-8"))))
    b = dict(leaves(json.load(open(argv[2] if len(argv) > 2 else "summary_arrays.json", encoding="utf-8"))))
    changed = sorted(k for k in a if k in b and a[k] != b[k])
    added = sorted(k for k in b if k not in a)
    removed = sorted(k for k in a if k not in b)
    bad = [("change", k) for k in changed if not (ALLOWED_CHANGE.match(k) or k.startswith(STAMP))]
    bad += [("add", k) for k in added if not (ALLOWED_ADD.match(k) or k.startswith(STAMP))]
    bad += [("remove", k) for k in removed if not k.startswith(STAMP)]
    print(json.dumps({"nChanged": len(changed), "nAdded": len(added), "nRemoved": len(removed), "unregistered": bad[:20], "nUnregistered": len(bad)}, indent=1))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
