#!/usr/bin/env python3
"""M433 (audit F21): ratchet on numeric literal fallbacks in xtrail_summary.jsx.
A required metric or a declared parameter must not have a silent numeric default (`x ?? 20`, `x || 120`, `x || {cold:20}`): missing -> unavailable, parameters -> payload.
Allowed: the harmless guards below (zero / unit / small-count guards, rendering geometry) listed in ALLOW with the reason; anything else fails tests/synthetic/test_literal_defaults.py.
Usage: python tools/literal_defaults_scan.py [--list]"""
import json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HARMLESS = {"0", "1", "2", "3", "4", "5", "10", "100", "-1"}          # zero / unit / count / percent guards
NUM = re.compile(r"(\?\?|\|\|)\s*(-?\d+(?:\.\d+)?)(?![\w.])")
OBJ = re.compile(r"(\?\?|\|\|)\s*\{\s*[A-Za-z_]+\s*:\s*-?\d")
# (snippet, reason): rendering geometry only, no scientific meaning
ALLOW = [
    ("c.find(s=>s>=raw)||1000", "axis tick-step fallback after the nice-step list is exhausted"),
    ("C0.axis.yMax)||40", "C-rate chart y-axis extent when the payload gives none (geometry)"),
    ("AX.xMin ?? 8, xMax=AX.xMax ?? 55", "temperature-axis extent when the payload gives none (geometry)"),
    ("strokeWidth={sw||0.8}", "stroke width (geometry)"),
    ("width:s.width||1.8", "legend line width (geometry)"),
    ("(a?.accelMax??-1)", "reduce seed for a maximum"),
]


def scan(path=None):
    path = path or os.path.join(ROOT, "xtrail_summary.jsx")
    out = []
    for i, line in enumerate(open(path, encoding="utf-8").read().split("\n"), 1):
        if line.lstrip().startswith(("//", "/*", "*")):
            continue
        for m in list(NUM.finditer(line)) + list(OBJ.finditer(line)):
            if m.re is NUM and m.group(2) in HARMLESS:
                continue
            if any(sn in line for sn, _ in ALLOW):
                continue
            out.append({"line": i, "match": line[max(0, m.start() - 40):m.end() + 12].strip()})
    return out


if __name__ == "__main__":
    r = scan()
    if "--list" in sys.argv or r:
        print(json.dumps(r, indent=1))
    print("unallowed numeric literal defaults: %d" % len(r))
    sys.exit(1 if r else 0)
