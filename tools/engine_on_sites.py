#!/usr/bin/env python3
"""M539 wave 1 (analyses/M539_spec.md Rev 2): the machine-readable registry of every code site that tests or defines an rpm engine-on / engine-off threshold, and the grep tripwire that finds new, unregistered sites.
`scan()` returns (file, line, text) for every non-comment code line that compares an rpm-like name with 300 or 400 or defines a *_ENG_ON / RPM_ON constant; `analyses/M539_site_registry.json` lists the allowed sites by file and anchor
(a substring of the line, so line shifts do not break it). Evidence / documentation tools of the M536 programme (tools/engine_on_*, tools/m5xx_*) and tests are out of scope.
Usage: python tools/engine_on_sites.py   (prints unregistered sites; exit 1 if any)"""
import glob, json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REGISTRY = os.path.join(ROOT, "analyses", "M539_site_registry.json")
PAT = re.compile(r"\b(rr|rp|er|rpm|eng_rpm|e_rpm|rv)\b[^#\n]{0,45}?(>=|<=|>|<)\s*(300|400)(?:\.0)?\b|_ENG_ON\s*=\s*(300|400)|\bRPM_ON\s*=\s*(300|400)")
SKIP = re.compile(r"^tools/(m5\d\d|engine_on_)")


def files():
    base = ["compute_summary_arrays.py", "compute_drive_summary_v6.py", "crosscheck_events.py", "rpm_opt_pass.py", "regen_seasonal_raw.py", "drive_raw_cache.py", "recon_engine.py", "fuel_recon.py"]
    out = [f for f in base if os.path.exists(os.path.join(ROOT, f))]
    out += sorted(os.path.relpath(p, ROOT).replace(os.sep, "/") for p in glob.glob(os.path.join(ROOT, "tools", "*.py")))
    return [f for f in out if not SKIP.match(f)]


def scan():
    hits = []
    for f in files():
        for i, line in enumerate(open(os.path.join(ROOT, f), encoding="utf-8", errors="replace"), 1):
            s = line.strip()
            if not s or s[0] in "#'\"" or s.startswith(("f'", 'f"')):
                continue
            if PAT.search(line):
                hits.append((f, i, s))
    return hits


def unregistered(registry=None):
    reg = registry if registry is not None else json.load(open(REGISTRY, encoding="utf-8"))
    sites = reg["sites"]
    return [(f, i, s) for f, i, s in scan() if not any(x["file"] == f and x["anchor"] in s for x in sites)]


if __name__ == "__main__":
    bad = unregistered()
    for f, i, s in bad:
        print("UNREGISTERED", f, i, s[:120])
    sys.exit(1 if bad else 0)
