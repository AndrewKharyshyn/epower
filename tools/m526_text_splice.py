#!/usr/bin/env python3
"""M526 (analyses/M526_spec.md Rev 1.1): correct or qualify stale corpus-size statements in payload TEXT leaves (9 leaves) and in the producer / splice constants that would restore them.
Text only: no numeric leaf, no key. Idempotent. Deep diff asserts that only the listed leaves changed.
Usage: python tools/m526_text_splice.py [--dry-run] [--check]"""
import copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

LPB_OLD = ("Motored is NOT proxied this way -- at RPM>1400 it is only ~2.5% of the boost-classified population, so load-based motored recall (up to 78.9%) carries 30%+ contamination from fuelled leakage and is not reliable enough to report.")
LPB_NEW = ("Motored is NOT proxied this way -- at RPM>1400 the boost-classified motored share is small (the live hours share is shown in the RPM Distribution section; an earlier hand-typed value in this text had no traceable basis), so load-based motored recall (up to 78.9%, historical M89 calibration, basis not traceable in the CHANGELOG, not recomputed on the current corpus) carries 30%+ contamination from fuelled leakage and is not reliable enough to report.")
LIM_OLD = "The headline corpus figures, drive-type split and RPM empirical-grounding sample (410 drives, refreshed M281) are current."
LIM_NEW = "The headline corpus figures and the drive-type split are current; the RPM empirical-grounding OPT-band occupancy of the earlier one-off 410-drive pass (M281) is superseded by the live rpmOptBand (M525)."
NE_OLD = "M295: re-derived on the live 446-drive payload (was frozen at the 410 basis:"
NE_NEW = "M295: re-derived on the 446-drive payload of that milestone (the corpus is larger now; was frozen at the 410 basis:"
MD5_OLD = "Cohort counts in this block already matched the live 446-drive corpus;"
MD5_NEW = "Cohort counts in this block already matched the 446-drive corpus of that milestone (M294);"
REC_OLD = "even at the current 320-drive corpus -- verified by a successful full recompute"
REC_NEW = "even at the 320-drive corpus of the M216 verification -- verified by a successful full recompute"

# payload leaves: (path, old, new)
LEAVES = [(("generatorTractionRecon", "limitations", 4), LIM_OLD, LIM_NEW),
          (("rpmDistribution", "params", "loadProxyBasis"), LPB_OLD, LPB_NEW)]
LEAVES += [(("seasonalCharts", "charts", "RpmDistribution", "data", c, "params", "loadProxyBasis"), LPB_OLD, LPB_NEW) for c in ("all", "warm", "shoulder", "cold")]
LEAVES += [(("seasonalCharts", "_meta", "nativeEquivalence", "note"), NE_OLD, NE_NEW),
           (("seasonalCharts", "_meta", "md5RestampNote"), MD5_OLD, MD5_NEW),
           (("socHysteresisV2", "recomputePolicy"), REC_OLD, REC_NEW)]

# source constants that would restore the old text (producer / one-off splice constants). The producer lines are split across string literals, so they are matched piecewise.
SRC = [
    ("tools/m373_p2_splice.py", "figures, drive-type split and RPM empirical-grounding sample (410 drives, refreshed M281) are current.",
     "figures and the drive-type split are current; the RPM empirical-grounding OPT-band occupancy of the earlier one-off 410-drive pass (M281) is superseded by the live rpmOptBand (M525)."),
    ("m295_payload.py", "re-derived on the live 446-drive payload (was frozen at the 410 basis:", "re-derived on the 446-drive payload of that milestone (the corpus is larger now; was frozen at the 410 basis:"),
    ("compute_summary_arrays.py", "'Motored is NOT proxied this way -- at RPM>1400 it is '\n                    'only ~2.5% of the boost-classified population, so '\n                    'load-based motored recall (up to 78.9%) carries '\n                    '30%+ contamination from fuelled leakage and is not '\n                    'reliable enough to report.',",
     "'Motored is NOT proxied this way -- at RPM>1400 the boost-classified '\n                    'motored share is small (the live hours share is shown in the '\n                    'RPM Distribution section; an earlier hand-typed value in this '\n                    'text had no traceable basis), so load-based motored recall '\n                    '(up to 78.9%, historical M89 calibration, basis not traceable '\n                    'in the CHANGELOG, not recomputed on the current corpus) carries '\n                    '30%+ contamination from fuelled leakage and is not '\n                    'reliable enough to report.',"),
    ("compute_summary_arrays.py", "RSS to <2GB even at the current 320-drive corpus -- verified by '", "RSS to <2GB even at the 320-drive corpus of the M216 verification -- verified by '"),
]


def _get(o, path):
    for k in path:
        o = o[k]
    return o


def _set(o, path, v):
    for k in path[:-1]:
        o = o[k]
    o[path[-1]] = v


def leaf_diff(A, new):
    """leaves (as key paths) where `new` differs from `A` and that are not in the allowed list (deep comparison of everything else)."""
    allowed = {tuple(p) for p, _, _ in LEAVES}
    out = []
    def walk(a, b, p):
        if isinstance(a, dict) and isinstance(b, dict):
            for k in set(a) | set(b):
                if k not in a or k not in b:
                    out.append(p + (k,))
                else:
                    walk(a[k], b[k], p + (k,))
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                out.append(p)
            else:
                for i, (x, y) in enumerate(zip(a, b)):
                    walk(x, y, p + (i,))
        elif a != b:
            out.append(p)
    walk(A, new, ())
    return [p for p in out if p not in allowed]


def splice(A):
    new = copy.deepcopy(A)
    changed = []
    for path, old, new_s in LEAVES:
        s = _get(new, path)
        if old in s:
            assert s.count(old) == 1, ("old text not unique", path)
            _set(new, path, s.replace(old, new_s)); changed.append(path)
        else:
            assert new_s in s, ("neither old nor new text found", path)
    bad = leaf_diff(A, new)
    return new, changed, bad


def patch_sources(dry):
    done = []
    for path, old, new_s in SRC:
        fp = os.path.join(ROOT, path)
        b = open(fp, "rb").read().decode("utf-8")
        crlf = "\r\n" in b
        o, n = (old.replace("\n", "\r\n"), new_s.replace("\n", "\r\n")) if crlf else (old, new_s)
        if o in b:
            assert b.count(o) == 1, (path, "old text not unique")
            if not dry:
                open(fp, "wb").write(b.replace(o, n).encode("utf-8"))
            done.append(path)
        else:
            assert n in b, (path, "neither old nor new text found")
    return done


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    os.chdir(ROOT)
    raw = open("summary_arrays.json", "r", encoding="utf-8", newline="").read()
    A = json.loads(raw)
    new, changed, bad = splice(A)
    if "--check" in argv:
        ok = not changed and not bad
        print(json.dumps({"check": "m526 text leaves", "alreadyApplied": ok}))
        return 0 if ok else 1
    src = patch_sources("--dry-run" in argv)
    print(json.dumps({"leavesChanged": len(changed), "outsideAllowList": [list(map(str, p)) for p in bad], "sourcesPatched": src}))
    if bad:
        return 1
    if "--dry-run" not in argv and changed:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1) + (chr(10) if raw.endswith(chr(10)) else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
