#!/usr/bin/env python3
"""M361 (spec analyses/M361_spec.md Rev 2): replace the notes of the two Records intake-air rows with the text from battery_temp_extremes.intake_note_texts (single source), keeping the ' Set on: ...' suffix.
Leaf string changes only (deep-diff asserts that nothing else in summary_arrays.json changes); values, drives and disclosures are untouched. Usage: python tools/m361_splice.py"""
import copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import pandas as pd
import battery_temp_extremes as B
A = json.load(open("summary_arrays.json", encoding="utf-8"))
dm = pd.read_csv("drive_master.csv", low_memory=False)
mn, mx = B.intake_note_texts(dm)
want = {"Battery intake air temperature min": mn, "Battery intake air temperature max": mx}
old = copy.deepcopy(A)
n = 0
for r in A["records"]:
    if r.get("metric") in want:
        tail = r["note"].split(" Set on: ", 1)
        r["note"] = want[r["metric"]] + ((" Set on: " + tail[1]) if len(tail) == 2 else "")
        n += 1
assert n == 2, n
def walk(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        assert set(a) == set(b), path
        for k in a: walk(a[k], b[k], f"{path}/{k}")
    elif isinstance(a, list) and isinstance(b, list):
        assert len(a) == len(b), path
        for i, (x, y) in enumerate(zip(a, b)): walk(x, y, f"{path}[{i}]")
    elif a != b:
        assert path.startswith("/records[") and path.endswith("/note"), (path, a, b)
walk(old, A)
with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
    json.dump(A, f, ensure_ascii=False, indent=1)
print("records notes updated:", n)
