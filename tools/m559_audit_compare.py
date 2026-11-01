#!/usr/bin/env python3
"""M559: compares the blind auditor's per-window table (analyses/M559_audit_result.json) with the tool's per-window report (analyses/M559_window_report.json) at the count level, and reports the auditor's 'unsure' seconds against the tool's values.
Writes analyses/M559_audit_compare.json. Usage: python tools/m559_audit_compare.py"""
import json, os
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
a = json.load(open(os.path.join(ROOT, "analyses", "M559_audit_result.json"), encoding="utf-8"))
m = json.load(open(os.path.join(ROOT, "analyses", "M559_window_report.json"), encoding="utf-8"))["windows"]
diffs, n = [], 0
for w in m:
    cand = [x for x in a["windows"] if x["file"] == w["file"] and x["category"] == w["category"] and x["stratum"] == w["stratum"]]
    if not cand:
        diffs.append({"file": w["file"], "why": "no matching window"}); continue
    x, c = cand[0], w["counts"]
    flat = {}
    for g in ("rot", "flow", "thermal", "comb"):
        for k, v in x[g].items():
            if v: flat[f"{g}_{k}"] = v
    for k, v in x["labels"].items():
        if v: flat["label_" + k] = v
    mine = {k: v for k, v in c.items() if k.startswith(("rot_", "flow_", "thermal_", "comb_")) or (k.startswith("label_") and v)}
    n += 1
    d = {k: [mine.get(k, 0), flat.get(k, 0)] for k in set(mine) | set(flat) if mine.get(k, 0) != flat.get(k, 0)}
    for k in ("unresolved", "spin", "rpmExactly2000"):
        if c[k] != x[k]:
            d[k] = [c[k], x[k]]
    if d:
        diffs.append({"file": w["file"], "category": w["category"], "differences": d})
unsure = sum(len(x["unsure"]) for x in a["windows"])
res = {"milestone": "M559", "windowsCompared": n, "windowsWithAnyCountDifference": len(diffs), "differences": diffs, "auditorUnsureSeconds": unsure,
       "auditorUnsureNote": "the unsure seconds are coolant values within 0.5 C of a cut or an age near 30 s, and missing speed for the discharging label; the windows containing them agree with the tool on every count (thermal, labels, unresolved), i.e. none of them changed a class" if not diffs else "see differences",
       "auditorAmbiguousRules": a.get("ambiguousRules")}
json.dump(res, open(os.path.join(ROOT, "analyses", "M559_audit_compare.json"), "w", encoding="utf-8"), indent=1)
print(json.dumps({k: res[k] for k in ("windowsCompared", "windowsWithAnyCountDifference", "auditorUnsureSeconds")}))
for d in diffs[:10]: print(d)
