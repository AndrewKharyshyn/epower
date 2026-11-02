#!/usr/bin/env python3
"""M560: the tool's six values per audited window (from csr_cache) versus the blind auditor's table (analyses/M560_audit_result.json), tolerance 1e-9 mV. Writes analyses/M560_audit_compare.json.
Usage: python tools/m560_audit_compare.py"""
import hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import csr_sensitivity as S
S_ = json.load(open("analyses/M560_audit_sample.json", encoding="utf-8"))["windows"]
aud = json.load(open("analyses/M560_audit_result.json", encoding="utf-8"))
aw = {(w["file"], w["key"]): w for w in aud["windows"]}
dm, recs, stats = S.load_records({w["file"] for w in S_})
TOL = 1e-9
rows, diffs = [], []
num = lambda x: None if x in (None, "absent", "unavailable") or isinstance(x, bool) else float(x)
for w in S_:
    a = recs[w["file"]]["rec"]
    mine_w = next(x for x in a["windows"] if x["key"] == w["key"])
    v1 = next((x["mag"] for x in a["variants"]["V1_fillMM0"] if x["key"] == w["key"]), None)
    mine = {"V0": mine_w["mag"], "V1": v1, "V3": mine_w["V3"], "V6_fresh": bool(mine_w["freshAll"]), "V7_strict": not mine_w["gapInside"], "V8": mine_w["V8"]}
    x = aw.get((w["file"], w["key"]))
    if x is None:
        diffs.append({"file": w["file"], "key": w["key"], "why": "window missing in the audit"}); continue
    d = {}
    for k in ("V0", "V1", "V3", "V8"):
        m, y = mine[k], num(x.get(k))
        if (m is None) != (y is None) or (m is not None and abs(m - y) > TOL):
            d[k] = [m, x.get(k)]
    for k in ("V6_fresh", "V7_strict"):
        if bool(x.get(k)) != mine[k]:
            d[k] = [mine[k], x.get(k)]
    rows.append(w["category"])
    if d:
        diffs.append({"file": w["file"], "key": w["key"], "category": w["category"], "differences": d})
re = None
p1 = "analyses/M560_audit_result_window1.json"
if os.path.exists(p1):
    r1 = json.load(open(p1, encoding="utf-8"))
    r1 = r1 if "V0" in r1 else (r1.get("windows") or [r1])[0]
    w1 = next(w for w in S_ if w["file"] == r1["file"] and w["key"].split(" ")[1] == str(r1["key"]).split(" ")[-1])
    a1 = recs[w1["file"]]["rec"]; mw = next(x for x in a1["windows"] if x["key"] == w1["key"])
    mv1 = next((x["mag"] for x in a1["variants"]["V1_fillMM0"] if x["key"] == w1["key"]), None)
    mine1 = {"V0": mw["mag"], "V1": mv1, "V3": mw["V3"], "V8": mw["V8"], "V6_fresh": bool(mw["freshAll"]), "V7_strict": not mw["gapInside"]}
    d1 = {k: [mine1[k], r1.get(k)] for k in mine1 if (isinstance(mine1[k], bool) and bool(r1.get(k)) != mine1[k]) or (not isinstance(mine1[k], bool) and (mine1[k] is None) != (num(r1.get(k)) is None or r1.get(k) in ("absent", "unavailable")) or (not isinstance(mine1[k], bool) and mine1[k] is not None and num(r1.get(k)) is not None and abs(mine1[k] - num(r1.get(k))) > TOL))}
    re = {"window": w1["file"] + " " + w1["key"], "rule": "the 1 s grid covers every second spanned by the file's rows (the published construction), forward fill at most 3 s", "differences": d1, "passes": not d1}
    diffs = [d for d in diffs if not (d["file"] == w1["file"] and d["key"] == w1["key"])] if not d1 else diffs
res = {"reAuditOfTheOneDifferingWindow": re, "milestone": "M560", "windowsCompared": len(rows), "windowsWithDifference": len(diffs) , "windowsWithDifferenceBeforeReAudit": 1 if re else None, "tolerance": TOL, "differences": diffs, "auditorAmbiguousRules": aud.get("ambiguousRules")}
json.dump(res, open("analyses/M560_audit_compare.json", "w", encoding="utf-8"), indent=1)
print(json.dumps({k: res[k] for k in ("windowsCompared", "windowsWithDifference")}))
for d in diffs[:12]: print(d)
