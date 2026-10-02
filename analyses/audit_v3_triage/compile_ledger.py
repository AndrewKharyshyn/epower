"""Compile Director ledger partitions and check coverage of the audit PDF text.

Reads  ledger/P*.txt   (pipe-delimited rows: ID | pg | ln | class | ver | ms | eff | action)
Reads  page_map.json   (printed page label -> [first line, last line] in audit.txt)
Reads  audit.txt       (for page text lengths / empty-page detection)
Writes ledger_all.tsv, coverage_report.txt
"""
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

SP = os.path.dirname(os.path.abspath(__file__))
CLASSES = {"FIX-NOW", "SPEC-FIRST", "BLOCKED", "STALE", "DECLINE", "BACKLOG", "INFO", "OWNER"}
VERS = {"V", "NV", "D", "n/a"}
EFFS = {"S", "M", "L", "-"}
GAP_LINES = int(sys.argv[1]) if len(sys.argv) > 1 else 22

page_map = json.load(open(os.path.join(SP, "page_map.json")))
audit_lines = open(os.path.join(SP, "audit.txt"), encoding="utf-8").read().split("\n")

rows, bad = [], []
for path in sorted(glob.glob(os.path.join(SP, "ledger", "P*.txt"))):
    part = os.path.basename(path)[:-4]
    for i, raw in enumerate(open(path, encoding="utf-8").read().split("\n"), 1):
        raw = raw.rstrip()
        if not raw.strip():
            continue
        f = [x.strip() for x in raw.split(" | ")]
        if len(f) < 8:
            bad.append((part, i, "fields<8", raw[:100]))
            continue
        if len(f) > 8:  # an action text containing ' | '
            f = f[:7] + [" | ".join(f[7:])]
        rid, pg, ln, cls, ver, ms, eff, act = f
        try:
            ln = int(ln)
        except ValueError:
            bad.append((part, i, "ln not int", raw[:100]))
            continue
        if pg not in page_map:
            bad.append((part, i, f"unknown page {pg}", raw[:100]))
            continue
        if cls not in CLASSES:
            bad.append((part, i, f"bad class {cls}", raw[:100]))
        if ver not in VERS:
            bad.append((part, i, f"bad ver {ver}", raw[:100]))
        if eff not in EFFS:
            bad.append((part, i, f"bad eff {eff}", raw[:100]))
        lo, hi = page_map[pg]
        if not (lo - 3 <= ln <= hi + 3):
            bad.append((part, i, f"line {ln} outside page {pg} [{lo},{hi}]", raw[:100]))
        rows.append(dict(part=part, id=rid, pg=pg, ln=ln, cls=cls, ver=ver, ms=ms, eff=eff, act=act))

# duplicate IDs
idc = Counter(r["id"] for r in rows)
dups = {k: v for k, v in idc.items() if v > 1}

with open(os.path.join(SP, "ledger_all.tsv"), "w", encoding="utf-8") as o:
    o.write("part\tid\tpg\tln\tclass\tver\tms\teff\taction\n")
    for r in sorted(rows, key=lambda r: r["ln"]):
        o.write("\t".join(str(r[k]) for k in ("part", "id", "pg", "ln", "cls", "ver", "ms", "eff", "act")) + "\n")

by_page = defaultdict(list)
for r in rows:
    by_page[r["pg"]].append(r["ln"])

out = []
out.append(f"rows={len(rows)}  malformed={len(bad)}  duplicate_ids={len(dups)}")
out.append("class counts: " + ", ".join(f"{k}={v}" for k, v in Counter(r['cls'] for r in rows).most_common()))
out.append("ver counts:   " + ", ".join(f"{k}={v}" for k, v in Counter(r['ver'] for r in rows).most_common()))
out.append("milestones:   " + ", ".join(f"{k}={v}" for k, v in sorted(Counter(r['ms'] for r in rows).items())))
out.append("")
labels = list(page_map.keys())
zero = [p for p in labels if p not in by_page]
out.append(f"pages with rows: {len(labels) - len(zero)}/{len(labels)}; pages WITHOUT any row: {zero}")
out.append("")
out.append(f"Line gaps > {GAP_LINES} lines between consecutive cited units (possible missed requirement blocks):")
ngaps = 0
for p in labels:
    lo, hi = page_map[p]
    cited = sorted(set(by_page.get(p, [])))
    pts = [lo] + cited + [hi]
    for a, b in zip(pts, pts[1:]):
        if b - a > GAP_LINES:
            # skip gap if the lines in it are all blank/page-header furniture
            txt = [t for t in audit_lines[a:b - 1] if t.strip() and not t.startswith("e-POWER independent audit")
                   and not t.startswith("Nissan e-POWER project audit") and "SCIENTIFIC METHODS" not in t]
            if len(txt) > GAP_LINES // 2:
                ngaps += 1
                out.append(f"  page {p}: lines {a}-{b} ({b - a} lines, {len(txt)} text lines) first: {txt[0][:70] if txt else ''}")
out.append(f"gaps flagged: {ngaps}")
out.append("")
out.append("rows per page: " + " ".join(f"{p}:{len(by_page.get(p, []))}" for p in labels))
if dups:
    out.append("")
    out.append("duplicate ids: " + ", ".join(f"{k}x{v}" for k, v in sorted(dups.items())[:60]))
if bad:
    out.append("")
    out.append("MALFORMED:")
    for b in bad[:80]:
        out.append("  " + " | ".join(map(str, b)))
rep = "\n".join(out)
open(os.path.join(SP, "coverage_report.txt"), "w", encoding="utf-8").write(rep)
print(rep)
