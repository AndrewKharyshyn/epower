#!/usr/bin/env python3
"""M375 step (analyses/M375_spec.md Rev 2, required change 4): READ-ONLY ripple scan of every site that states or binds the headline eligibility / counts: hard-coded 260 / 261 / 2003.9,
'f_gen not NaN', 'headline definition', nProduction / nDrives, in the dashboard source, tests, gates, tools and the payload strings. Writes analyses/M375_ripple_scan.json only.
CHANGELOG history and analyses/ are not scanned. Usage: python tools/m375_ripple_scan.py"""
import glob, json, os, re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
PAT = re.compile(r"\b26[01]\b|2003\.9|f_gen not NaN|headline definition|not canonical-clean|nProduction|\bnDrives\b|f_gen is not NaN|clean = f_gen")
files = [f for pat in ("*.jsx", "*.js", "*.py", "tests/**/*.py", "tests/**/*.js", "tools/*.py", "*.sh") for f in glob.glob(pat, recursive=True)]
files = sorted(set(f for f in files if not f.startswith(("node_modules", "tabtext", "audit", "analyses", "runs")) and "tmp" not in os.path.basename(f)))
hits = []
for f in files:
    try:
        lines = open(f, encoding="utf-8", errors="replace").read().split("\n")
    except OSError:
        continue
    for i, l in enumerate(lines, 1):
        for m in PAT.finditer(l):
            hits.append({"file": f, "line": i, "match": m.group(0), "context": l.strip()[:200]})
# payload strings
A = json.load(open("summary_arrays.json", encoding="utf-8"))
ph = []


def walk(o, p=""):
    if isinstance(o, str):
        for m in PAT.finditer(o):
            ph.append({"path": p, "match": m.group(0), "context": o[max(0, m.start() - 80):m.end() + 80]})
    elif isinstance(o, dict):
        for k, v in o.items():
            walk(v, p + "/" + k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            walk(v, f"{p}[{i}]")


walk(A.get("generatorTractionRecon", {}), "/generatorTractionRecon")
walk(A.get("seasonalCharts", {}).get("charts", {}).get("GeneratorTractionRecon", {}), "/seasonalCharts/charts/GeneratorTractionRecon")
by_file = {}
for h in hits:
    by_file.setdefault(h["file"], []).append(h)
out = {"nSourceHits": len(hits), "nFiles": len(by_file), "byFile": {f: {"n": len(v), "matches": sorted({x['match'] for x in v})} for f, v in sorted(by_file.items())}, "hits": hits, "payloadStringHits": ph}
with open("analyses/M375_ripple_scan.json", "w", encoding="utf-8", newline="\n") as fh:
    json.dump(out, fh, indent=1, ensure_ascii=False)
    fh.write("\n")
print("source hits", len(hits), "in", len(by_file), "files; payload string hits", len(ph))
for f, v in sorted(by_file.items(), key=lambda kv: -len(kv[1]))[:25]:
    print(f"  {f}: {len(v)}  {sorted({x['match'] for x in v})}")
for h in ph[:12]:
    print("  PAYLOAD", h["path"], "|", h["match"], "|", h["context"][:140].replace("\n", " "))
