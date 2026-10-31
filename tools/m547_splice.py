#!/usr/bin/env python3
"""M547 (analyses/M547_spec.md Rev 2.1): two payload TEXT leaves in summary_arrays.json follow the builder wording change (AUD29-F02 altitude verdict, AUD29-F19 peak commanded torque note). Byte-level replacement, idempotent, text only; a deep diff must show only the two declared leaves.
Usage: python tools/m547_splice.py [--dry-run] [--check]"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EDITS = [
    (("lowSpeedDissipation", "relief", "verdict"),
     "Elevation is a WEAK, marginally significant predictor of dissipation time and does NOT significantly predict the SoC ceiling. Totals are carried by a handful of drives. Consistent with, but not established by, the data.",
     "The logged altitude proxy shows a weak association with dissipation time and with the trip maximum SoC (nominal, unadjusted Spearman p-values over drives, not clustered by day or route and not multiplicity-adjusted). Totals are carried by a handful of drives. Consistent with, but not established by, the data; no causal terrain conclusion."),
    (("records", "Peak motor torque", "note"),
     "Highest commanded traction torque. The single front motor is the only path to the wheels, so this is the drivetrain's full output ceiling, not one axle's share.",
     "Highest commanded traction torque. The single front motor is the only path to the wheels, so this is the peak commanded (target) torque of that motor, not one axle's share; it is not a measured shaft torque or a verified output ceiling."),
]


def diff_paths(a, b, p=()):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) | set(b):
            out += [p + (k,)] if (k not in a or k not in b) else diff_paths(a[k], b[k], p + (k,))
    elif isinstance(a, list) and isinstance(b, list):
        out += [p] if len(a) != len(b) else [q for i, (x, y) in enumerate(zip(a, b)) for q in diff_paths(x, y, p + (i,))]
    elif a != b:
        out.append(p)
    return out


def get(o, path):
    for k in path:
        if k == "Peak motor torque":      # records is a list of {metric, ...}
            o = next(r for r in o if r.get("metric") == k)
        else:
            o = o[k]
    return o


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    raw = open("summary_arrays.json", "rb").read().decode("utf-8")
    A = json.loads(raw)
    new_raw, changed = raw, []
    for path, old, new in EDITS:
        cur = get(A, path)
        if old in cur:
            enc_old, enc_new = json.dumps(old, ensure_ascii=False)[1:-1], json.dumps(new, ensure_ascii=False)[1:-1]
            assert new_raw.count(enc_old) == 1, ("old text not unique", path)
            new_raw = new_raw.replace(enc_old, enc_new)
            changed.append(list(path))
        else:
            assert new in cur, ("neither old nor new text", path)
    B = json.loads(new_raw)
    n_diff = len(diff_paths(A, B)) if changed else 0
    if "--check" in argv:
        print(json.dumps({"check": "m547 payload text leaves", "alreadyApplied": not changed}))
        return 0 if not changed else 1
    print(json.dumps({"leavesChanged": changed, "diffPaths": n_diff}))
    if n_diff != len(changed):
        return 1
    if "--dry-run" not in argv and changed:
        open("summary_arrays.json", "wb").write(new_raw.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
