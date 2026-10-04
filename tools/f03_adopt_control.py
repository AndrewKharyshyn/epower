#!/usr/bin/env python3
"""F03 re-anchoring, step 2 (Director ruling analyses/M366_spec.md): adopt the control-build values into summary_arrays.json by a three-way leaf merge.
PUBLISHED = current summary_arrays.json, BASELINE = builder output on the current raw/, CONTROL = builder output on the sha256-verified originals (tools/f03_control_build.py).
A leaf is set to the control value ONLY where control != baseline AND published == baseline. Top-level keys where BASELINE != PUBLISHED (post-step patched blocks) are NOT taken from the control: the post steps recompute them.
Any other disagreement is a held CONFLICT, reported, never applied; a conflict stops the milestone for review. generatedAt timestamps and _artifactStamps are skipped.
Usage: python tools/f03_adopt_control.py BASELINE.json CONTROL.json [--apply]  -> analyses/F03_originals/M366_adopt_report.json"""
import copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
OUT = os.path.join(ROOT, "analyses", "F03_originals", "M366_adopt_report.json")
canon = lambda o: json.dumps(o, sort_keys=True, ensure_ascii=False, default=float)


def merge(pub, base, ctl, path, rep):
    if isinstance(base, dict) and isinstance(ctl, dict) and isinstance(pub, dict):
        for k in sorted(set(base) | set(ctl)):
            if k == "generatedAt":
                continue
            if k not in base or k not in ctl or k not in pub:
                if (k in base) != (k in ctl) or ((k in base) and (k not in pub)):
                    rep["conflicts"].append({"path": f"{path}/{k}", "kind": "key presence differs between published/baseline/control"})
                continue
            merge(pub[k], base[k], ctl[k], f"{path}/{k}", rep)
    elif isinstance(base, list) and isinstance(ctl, list) and isinstance(pub, list):
        if not (len(base) == len(ctl) == len(pub)):
            if canon(base) != canon(ctl):
                rep["conflicts"].append({"path": path, "kind": f"list lengths published/baseline/control {len(pub)}/{len(base)}/{len(ctl)}"})
            return
        for i in range(len(base)):
            merge(pub[i], base[i], ctl[i], f"{path}[{i}]", rep)
    else:
        if canon(base) == canon(ctl):
            return
        if canon(pub) == canon(base):
            rep["adopted"] += 1
            rep["_sets"].append((path, ctl))
        else:
            rep["conflicts"].append({"path": path, "published": pub if not isinstance(pub, str) else pub[:100], "baseline": base if not isinstance(base, str) else base[:100], "control": ctl if not isinstance(ctl, str) else ctl[:100]})


def setpath(root, path, val):
    import re
    toks = re.findall(r"/([^/\[\]]+)|\[(\d+)\]", path)
    cur = root
    for i, (k, idx) in enumerate(toks):
        last = i == len(toks) - 1
        key = int(idx) if idx != "" else k
        if last:
            cur[key] = val
        else:
            cur = cur[key]


def main():
    apply = "--apply" in sys.argv
    B = json.load(open(sys.argv[1], encoding="utf-8")); C = json.load(open(sys.argv[2], encoding="utf-8"))
    P = json.load(open("summary_arrays.json", encoding="utf-8"))
    skip = sorted(k for k in set(B) & set(C) & set(P) if canon(B[k]) != canon(P[k]))
    rep = {"milestone": "M366", "adopted": 0, "conflicts": [], "_sets": [], "skippedPostStepKeys": skip, "keysOnlyInControl": sorted(set(C) - set(P)), "keysOnlyInPublished": sorted(set(P) - set(C))}
    for k in sorted(set(B) & set(C) & set(P)):
        if k == "_artifactStamps" or k in skip:
            continue
        merge(P[k], B[k], C[k], f"/{k}", rep)
    sets = rep.pop("_sets")
    rep["byKey"] = {}
    for p, _ in sets:
        kk = p.split("/")[1].split("[")[0]
        rep["byKey"][kk] = rep["byKey"].get(kk, 0) + 1
    rep["applied"] = bool(apply and not rep["conflicts"])
    json.dump(rep, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False, default=float)
    print(json.dumps({"adopted": rep["adopted"], "conflicts": len(rep["conflicts"]), "skippedPostStepKeys": skip, "keysOnlyInControl": rep["keysOnlyInControl"], "applied": rep["applied"]}, indent=1))
    if apply and not rep["conflicts"]:
        for p, v in sets:
            setpath(P, p, v)
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            json.dump(P, f, ensure_ascii=False, indent=1)
        print("applied", len(sets), "leaves")
    elif rep["conflicts"]:
        print("CONFLICTS (first 8):"); [print(" ", c) for c in rep["conflicts"][:8]]


if __name__ == "__main__":
    main()
