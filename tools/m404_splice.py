#!/usr/bin/env python3
"""M404 splice: one text leaf of summary_arrays.json (constantProvenance.CAP_KWH.note) <- summary_config.json auditMetadata.constantProvenance.CAP_KWH.note (the 'per-cell' wording correction).
STOP on any other change. Usage: M404_ARRAYS_SHA16=<sha16> python tools/m404_splice.py [--dry-run]"""
import hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
raw = open("summary_arrays.json", "rb").read()
if hashlib.sha256(raw).hexdigest()[:16] != os.environ.get("M404_ARRAYS_SHA16"):
    raise SystemExit("summary_arrays.json changed since the run started (or M404_ARRAYS_SHA16 not set)")
A = json.loads(raw.decode("utf-8"))
if json.dumps(A, ensure_ascii=False, indent=1) != raw.decode("utf-8"):
    raise SystemExit("serialisation round-trip differs: refusing to rewrite the file")
cfg = json.load(open("summary_config.json", encoding="utf-8"))
old = A["constantProvenance"]["CAP_KWH"]["note"]
new_note = cfg["auditMetadata"]["constantProvenance"]["CAP_KWH"]["note"]
print(json.dumps({"changed": old != new_note}))
if "--dry-run" not in sys.argv and old != new_note:
    A["constantProvenance"]["CAP_KWH"]["note"] = new_note
    with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(A, ensure_ascii=False, indent=1))
