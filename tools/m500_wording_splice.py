#!/usr/bin/env python3
"""M500 (audit CD-04) leaf splice: regenerates powerFade.cadenceSensitivity through the changed compute_summary_arrays._powerfade_cadence_block from the leaves already in the payload,
deep-diffs it against the live block and splices ONLY the leaves that differ (the statement and emulation.label wording); any other difference STOPS.
Usage: python tools/m500_wording_splice.py [--dry-run]"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import compute_summary_arrays as C

P = "summary_arrays.json"
raw = open(P, encoding="utf-8", newline="").read()
A = json.loads(raw)
LOCS = [("powerFade.cadenceSensitivity", lambda: A["powerFade"]["cadenceSensitivity"]), ("fadeModes.power.trend.cadenceSensitivity", lambda: A["fadeModes"]["power"]["trend"]["cadenceSensitivity"])]
changed = []


def walk(o, n, path):
    if isinstance(o, dict) and isinstance(n, dict):
        if set(o) != set(n):
            raise SystemExit("STOP: key set differs at %s: %s" % (path, sorted(set(o) ^ set(n))))
        for k in n:
            if isinstance(o[k], (dict, list)) and isinstance(n[k], type(o[k])):
                walk(o[k], n[k], path + "." + k)
            elif o[k] != n[k]:
                o[k] = n[k]
                changed.append(path + "." + k)
    elif isinstance(o, list) and isinstance(n, list):
        if len(o) != len(n):
            raise SystemExit("STOP: list length at " + path)
        for i, (a, b) in enumerate(zip(o, n)):
            if isinstance(a, (dict, list)):
                walk(a, b, "%s[%d]" % (path, i))
            elif a != b:
                o[i] = b
                changed.append("%s[%d]" % (path, i))
    elif o != n:
        raise SystemExit("STOP: type change at " + path)


for name, get in LOCS:
    cur = get()
    cs = {k: v for k, v in cur.items() if k not in ("emulation", "statement")}
    emu = C._powerfade_emulation_snapshot(int(cur["nClean"]))   # regenerated from analyses/M393_resistance_cadence.json (label wording changed at M500)
    new = json.loads(json.dumps(C._powerfade_cadence_block(cs, emu), default=float))
    walk(cur, new, name)
# the trend notes embed the cadence statement as their tail (compute_summary_arrays: cad_clause = ... + cs_block['statement']); replace that tail by the regenerated statement
STMT_START = "HV-current-density adjustment (M170) is partial:"
NOTE_LOCS = [("powerFade.note", lambda: A["powerFade"], lambda: A["powerFade"]["cadenceSensitivity"]["statement"]),
             ("fadeModes.power.trend.note", lambda: A["fadeModes"]["power"]["trend"], lambda: A["fadeModes"]["power"]["trend"]["cadenceSensitivity"]["statement"])]
for name, holder, stmt in NOTE_LOCS:
    h = holder()
    i = h["note"].find(STMT_START)
    if i < 0:
        raise SystemExit("STOP: statement tail not found in " + name)
    new_note = h["note"][:i] + stmt()
    if new_note != h["note"]:
        h["note"] = new_note
        changed.append(name)
allowed = {n + suffix for n, _ in LOCS for suffix in (".statement", ".emulation.label")} | {n for n, _, _ in NOTE_LOCS}
bad = [c for c in changed if c not in allowed]
print(json.dumps({"changed": changed, "outsideAllowList": bad}, indent=1))
if bad:
    raise SystemExit(1)
if "--dry-run" not in sys.argv and changed:
    with open(P, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(A, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
