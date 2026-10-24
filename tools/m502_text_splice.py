#!/usr/bin/env python3
"""M502 (audit ST-10) leaf splice of wording in summary_arrays.json: replaces the declared old fragments by the new ones wherever they occur in string leaves (each pair must be found at least once), and
sets evidenceLedger.rows[4].evidenceClass to 'derived' (the resistance proxy is a derived quantity, not a measurement). Idempotent. Usage: python tools/m502_text_splice.py [--dry-run]"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
P = "summary_arrays.json"
raw = open(P, encoding="utf-8", newline="").read()
A = json.loads(raw)
PAIRS = [
    ("this sample size, a genuine null result -- this does not contradict",
     "this sample size (not resolved; an absence of detection, not evidence of no effect) -- this does not contradict"),
    ("which CONFIRMS the first-order model is an adequate description at this sample size -- a genuine null result reported as such, not evidence of a failed check.",
     "so the second-order model is not preferred at this sample size; that is an absence of detected improvement, not proof that the first-order model is adequate, and not evidence of a failed check."),
    ("a resolvable fade trend at this corpus size/window, a genuine null result. Both",
     "a resolvable fade trend at this corpus size/window, a trend is not resolved in this window (an absence of detection, not evidence of no change). Both"),
]
found = {i: [] for i in range(len(PAIRS))}


def walk(o, path):
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, str):
                for i, (old, new) in enumerate(PAIRS):
                    if old in v:
                        o[k] = v = v.replace(old, new)
                        found[i].append(path + "." + k)
            else:
                walk(v, path + "." + k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            if isinstance(v, str):
                for j, (old, new) in enumerate(PAIRS):
                    if old in v:
                        o[i] = v = v.replace(old, new)
                        found[j].append("%s[%d]" % (path, i))
            else:
                walk(v, "%s[%d]" % (path, i))


walk(A, "")
changed = [p for v in found.values() for p in v]
row = A["evidenceLedger"]["rows"][4]
if "esistance" in row["topic"] and row["evidenceClass"] != "derived":
    row["evidenceClass"] = "derived"
    changed.append("evidenceLedger.rows[4].evidenceClass")
print(json.dumps({"changed": changed, "n": len(changed)}, indent=1))
if "--dry-run" not in sys.argv and changed:
    with open(P, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(A, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
