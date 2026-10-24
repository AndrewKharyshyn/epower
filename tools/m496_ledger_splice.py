#!/usr/bin/env python3
"""M496 (audit ST-01) additive splice of evidenceLedger: compute only the key with the changed _evidence_ledger(), deep-diff against the live payload,
splice only the leaves that differ (artifactIdentity of each row is kept), refuse any other difference. Usage: python tools/m496_ledger_splice.py [--dry-run]"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import compute_summary_arrays as C
P = os.path.join(ROOT, "summary_arrays.json")
A = json.load(open(P, encoding="utf-8"))
new = json.loads(json.dumps(C._evidence_ledger(A), default=float))
old = A["evidenceLedger"]
changed = []


def walk(o, n, path):
    if isinstance(o, dict) and isinstance(n, dict):
        for k in n:
            if k not in o:
                if k != "artifactIdentity":
                    raise SystemExit("STOP: new key %s.%s" % (path, k))
                continue
            if isinstance(o[k], (dict, list)) and isinstance(n[k], type(o[k])):
                walk(o[k], n[k], path + "." + k)
            elif o[k] != n[k]:
                o[k] = n[k]; changed.append(path + "." + k)
        extra = [k for k in o if k not in n and k != "artifactIdentity"]
        if extra:
            raise SystemExit("STOP: key removed %s %s" % (path, extra))
    elif isinstance(o, list) and isinstance(n, list):
        if len(o) != len(n):
            raise SystemExit("STOP: list length %s" % path)
        for i, (a, b) in enumerate(zip(o, n)):
            if isinstance(a, (dict, list)):
                walk(a, b, "%s[%d]" % (path, i))
            elif a != b:
                o[i] = b; changed.append("%s[%d]" % (path, i))
    else:
        raise SystemExit("STOP: type change at " + path)


walk(old, new, "evidenceLedger")
print(json.dumps({"changed": changed, "n": len(changed)}, indent=1))
if "--dry-run" not in sys.argv and changed:
    with open(P, "w", encoding="utf-8", newline="\n") as f:
        json.dump(A, f, ensure_ascii=False, indent=1)
