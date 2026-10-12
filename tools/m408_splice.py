#!/usr/bin/env python3
"""M408 splice (analyses/M408_spec.md): leaf-level text update of summary_arrays.json after the producer fixes in compute_summary_arrays.py.
Only string leaves change; nothing numeric. Each old phrase is replaced by the producer's new phrase at an exact, expected number of leaves:
  powerFade.note and fadeModes.power.trend.note   'no statistically detectable power fade'      -> 'a trend is not resolved'
  fadeModes.power.whyNotProjected                  'the measured trend is statistically indistinguishable from zero' -> 'the estimated trend is not resolved from zero in this window'
  officialDisclosureCorrelation.{resistance,rows[2]}.note   'is the measured TREND'              -> 'is the estimated TREND'
  _retractedLifeEol                                'no degradation trend is detectable'          -> 'no degradation trend is resolved in this window'
STOP on any other change. drive_master.csv is not read. Usage: M408_ARRAYS_SHA16=<sha16> python tools/m408_splice.py [--dry-run]"""
import copy, hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)
DRY = "--dry-run" in sys.argv
raw = open("summary_arrays.json", "rb").read()
exp = os.environ.get("M408_ARRAYS_SHA16")
if not exp or hashlib.sha256(raw).hexdigest()[:16] != exp:
    raise SystemExit("summary_arrays.json changed since the run started (or M408_ARRAYS_SHA16 not set)")
A = json.loads(raw.decode("utf-8"))
if json.dumps(A, ensure_ascii=False, indent=1) != raw.decode("utf-8"):
    raise SystemExit("serialisation round-trip differs: refusing to rewrite the file")
SUBS = [("The 95 % day-cluster interval spans zero: no statistically detectable power fade in this window.",
         "The 95 % day-cluster interval spans zero: a trend is not resolved in this window.", 2),
        ("and the measured trend is statistically indistinguishable from zero, so any extrapolation",
         "and the estimated trend is not resolved from zero in this window, so any extrapolation", 1),
        ("What IS comparable is the measured TREND", "What IS comparable is the estimated TREND", 2),
        ("that no degradation trend is detectable;", "that no degradation trend is resolved in this window;", 1)]
counts = [0] * len(SUBS)
paths = []


def walk(o, p):
    if isinstance(o, dict):
        return {k: walk(v, p + "/" + k) for k, v in o.items()}
    if isinstance(o, list):
        return [walk(v, p + "/%d" % i) for i, v in enumerate(o)]
    if isinstance(o, str):
        for i, (a, b, _) in enumerate(SUBS):
            if a in o:
                o = o.replace(a, b)
                counts[i] += 1
                paths.append(p)
    return o


new = walk(copy.deepcopy(A), "")
bad = [(s[0][:50], c, s[2]) for s, c in zip(SUBS, counts) if c != s[2]]
if bad:
    raise SystemExit("unexpected leaf counts: %r" % bad)


def diff(a, b, p=""):
    if type(a) is not type(b):
        return [p]
    if isinstance(a, dict):
        return [x for k in a for x in diff(a[k], b[k], p + "/" + k)] if a.keys() == b.keys() else [p + " keys"]
    if isinstance(a, list):
        return [x for i, (u, v) in enumerate(zip(a, b)) for x in diff(u, v, p + "/%d" % i)] if len(a) == len(b) else [p + " len"]
    return [p] if a != b else []


changed = diff(A, new)
if sorted(changed) != sorted(paths):
    raise SystemExit("change set differs from the substituted leaves")
print(json.dumps({"changedLeaves": changed}, indent=1))
if not DRY and changed:
    with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(new, ensure_ascii=False, indent=1))
