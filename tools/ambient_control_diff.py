#!/usr/bin/env python3
"""M755 (spec analyses/M755_spec.md Rev 2, 8.3): compare the control arrays builds of the ambientByDrive reader fix and, with --splice, write the changed leaves into summary_arrays.json.

Inputs: A and A2 = the same arrays build run twice on the CURRENT code and config (their differing leaves are the run-to-run DRIFT list), B = the build with the shared ambient reader (same master, raw set, sidecars),
P = the published summary_arrays.json. Rules (fixed in the spec before any result existed):
  * expected-changed set = the leaves where B differs from A, minus the drift list, minus the artifact stamps (stamps are re-derived by their own stage, not copied);
  * a changed leaf may lie only inside the EXPECTED blocks (the blocks produced by the five reader sites and their dependents); a changed leaf anywhere else ESCALATES (exit 1, nothing written);
  * a changed leaf in an expected block where the PUBLISHED payload differs from A ESCALATES too (a one-off tool spliced it: decide per leaf), it is never skipped silently;
  * only leaves where published == A are spliced (a list whose length changes is replaced whole).
Usage: python tools/ambient_control_diff.py A.json A2.json B.json [--report FILE] [--splice] [--published summary_arrays.json]"""
import copy, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import exposure_control_diff as D

EXPECTED_BLOCKS = ("heatSoakCarryover", "interDriveCarryover", "linkedAdjacentDriveTable", "dailyFingerprints", "batteryTempRanges", "batteryVsAmbient", "auxLoadAmbient")
IGNORED_TOP = ("_artifactStamps",)


class Stop(Exception):
    pass


def top(path):
    return path.split("/")[1] if path.count("/") else path


def under(path, prefixes):
    return any(path == p or path.startswith(p + "/") for p in prefixes)


def get(o, path):
    for k in [p for p in path.split("/") if p != ""]:
        o = o[int(k)] if isinstance(o, list) else o[k]
    return o


def put(o, path, v):
    ks = [p for p in path.split("/") if p != ""]
    for k in ks[:-1]:
        o = o[int(k)] if isinstance(o, list) else o[k]
    k = ks[-1]
    if isinstance(o, list):
        o[int(k)] = v
    else:
        o[k] = v


def analyse(A, A2, B, P):
    """Returns the report dict (and the leaf lists) without writing anything."""
    drift = {p for p, *_ in D.diff(A, A2)}
    ch = [(p, k, a, b) for p, k, a, b in D.diff(A, B) if not under(p, drift) and top(p) not in IGNORED_TOP]
    pub_vs_a = {p for p, *_ in D.diff(P, A)}
    by_top = {}
    for p, *_ in ch:
        by_top[top(p)] = by_top.get(top(p), 0) + 1
    unexpected = sorted(t for t in by_top if t not in EXPECTED_BLOCKS)
    escalate_pub = [p for p, *_ in ch if top(p) in EXPECTED_BLOCKS and (p in pub_vs_a or any(q.startswith(p + "/") or p.startswith(q + "/") for q in pub_vs_a))]
    splice = [(p, k, a, b) for p, k, a, b in ch if top(p) in EXPECTED_BLOCKS and p not in escalate_pub]
    return {"driftLeaves": len(drift), "driftTopKeys": sorted({top(p) for p in drift}), "changedLeaves": len(ch), "changedByTopKey": dict(sorted(by_top.items(), key=lambda x: -x[1])),
            "unexpectedTopKeys": unexpected, "escalatePublishedDiffersFromA": escalate_pub[:200], "nEscalate": len(escalate_pub), "nSplice": len(splice)}, ch, splice


def apply_splice(P, B, splice_paths):
    """Write the B value at every spliced path into a copy of P; lists whose length changed are replaced whole (their path is the list itself)."""
    N = copy.deepcopy(P)
    for p in splice_paths:
        put(N, p, copy.deepcopy(get(B, p)))
    return N


def main(argv):
    a_, a2_, b_ = [json.load(open(argv[i], encoding="utf-8")) for i in (1, 2, 3)]
    pub_path = argv[argv.index("--published") + 1] if "--published" in argv else os.path.join(HERE, "..", "summary_arrays.json")
    raw = open(pub_path, encoding="utf-8", newline="").read()
    P = json.loads(raw)
    rep, ch, splice = analyse(a_, a2_, b_, P)
    rep["expectedBlocks"] = list(EXPECTED_BLOCKS)
    rep["table"] = [{"path": p, "kind": k, "published": a if not isinstance(a, (dict, list)) else None, "new": b if not isinstance(b, (dict, list)) else None} for p, k, a, b in splice[:2000]]
    if "--report" in argv:
        json.dump(rep, open(argv[argv.index("--report") + 1], "w", encoding="utf-8", newline="\n"), indent=1, default=str)
    print(json.dumps({k: v for k, v in rep.items() if k not in ("table", "escalatePublishedDiffersFromA")}, indent=1, default=str))
    if rep["unexpectedTopKeys"] or rep["nEscalate"]:
        print("STOP: a changed leaf lies outside the expected blocks or the published payload differs from build A at a changed leaf; nothing written")
        return 1
    if "--splice" in argv:
        N = apply_splice(P, b_, [p for p, *_ in splice])
        bad = [p for p, *_ in D.diff(P, N) if top(p) not in EXPECTED_BLOCKS]
        if bad:
            print("STOP: isolation diff found leaves outside the expected blocks:", bad[:5])
            return 1
        with open(pub_path, "w", encoding="utf-8", newline="") as f:
            f.write(json.dumps(N, ensure_ascii=False, indent=1) + ("\n" if raw.endswith("\n") else ""))
        print("spliced %d leaves" % len(splice))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
