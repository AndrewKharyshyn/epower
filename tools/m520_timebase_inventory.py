#!/usr/bin/env python3
"""M520 Part C (analyses/M520_spec.md Rev 2): read-only inventory of dashboard strings in xtrail_summary.jsx that quote engine time (hours, 'engine-on time') and do not name a time base
(elapsed / RPM-supported / duration-scaled imputed / gridded / detector-defined). Writes analyses/M520_timebase_inventory.json. Changes nothing."""
import json, os, re, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
QUANT = re.compile(r"engine[- ]on (hours|time)|engine hours|hours of engine|ENGINE-ON (hours|time)", re.I)
BASE = re.compile(r"supported|elapsed|duration-scaled|imputed|gridded|detector|per-second|RPM above|rpm >|eng_rpm|time base|M512", re.I)
rows = []
for i, line in enumerate(open(os.path.join(ROOT, "xtrail_summary.jsx"), encoding="utf-8"), 1):
    if QUANT.search(line):
        rows.append({"line": i, "namesTimeBase": bool(BASE.search(line)), "text": line.strip()[:220]})
out = {"scope": "xtrail_summary.jsx lines quoting engine-on time/hours", "nQuoting": len(rows), "nWithoutNamedBase": sum(1 for r in rows if not r["namesTimeBase"]), "rows": rows,
       "note": "same-line heuristic only; a line without a named base may name it in an adjacent sentence. A wording change needs the basis of each channel confirmed (Director)."}
json.dump(out, open(os.path.join(ROOT, "analyses", "M520_timebase_inventory.json"), "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False)
print(json.dumps({k: out[k] for k in ("nQuoting", "nWithoutNamedBase")}))
for r in rows:
    if not r["namesTimeBase"]:
        print(r["line"], r["text"][:150])
