#!/usr/bin/env python3
"""M466 stage C: compare the 489-basis START ladder control (tools/m320_ladder.py run on tools/m318_run.py tables --n-first 489, today's code, raw/ originals; XT_M320_KAT_REF = the matching control block)
with the published 489-basis start ladder (git --prev-ref) and with the shipped 606-basis ladder. Writes analyses/M466_ladder_control.json.
Usage: python tools/m466_ladder_compare.py --prev-ref 3eb3f3c~1"""
import argparse, json, os, subprocess
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT)


def flat(o, p=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from flat(v, p + "/" + k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from flat(v, p + "[%d]" % i)
    elif isinstance(o, (int, float)) and not isinstance(o, bool):
        yield p, float(o)


ap = argparse.ArgumentParser()
ap.add_argument("--prev-ref", required=True)
a = ap.parse_args()
ctl = json.load(open("analyses/M466_c_control/ladder489_start.json", encoding="utf-8"))["block"]
pub = json.loads(subprocess.run(["git", "show", a.prev_ref + ":summary_arrays.json"], capture_output=True, check=True).stdout.decode("utf-8"))["socHysteresisV2"]["tempLadder"]["start"]
now = json.load(open("summary_arrays.json", encoding="utf-8"))["socHysteresisV2"]["tempLadder"]["start"]
lv = lambda b: [{k: x[k] for k in ("name", "value", "dayWeightedSnapped", "nEvents", "nDays", "role")} for x in b["levels"]]
fa, fb = dict(flat(pub)), dict(flat(ctl))
com = sorted(p for p in set(fa) & set(fb) if not p.startswith("/provenance"))
diff = [(p, fa[p], fb[p]) for p in com if fa[p] != fb[p]]
out = {"prevRef": a.prev_ref, "levels": {"published489": lv(pub), "control489": lv(ctl), "shipped606": lv(now)},
       "levelsReproduced": lv(pub) == lv(ctl), "needsDirector": {"published489": pub["needsDirector"], "control489": ctl["needsDirector"], "shipped606": now["needsDirector"]},
       "numericLeaves": {"common": len(com), "identical": len(com) - len(diff), "maxAbsDiff": max([abs(x[1] - x[2]) for x in diff] or [0.0]), "largest": [{"path": p, "published": u, "control": v} for p, u, v in sorted(diff, key=lambda t: -abs(t[1] - t[2]))[:6]]},
       "reading": "Control = first 489 master rows, today's code and raw/ originals. If the levels are reproduced the collapse of the shipped start ladder to one level is not produced by code or by the M366 provenance change on the old drives; it follows from the added drives (new-data effect, associational, model-derived)."}
with open("analyses/M466_ladder_control.json", "w", encoding="utf-8", newline="\n") as f:
    json.dump(out, f, indent=1, ensure_ascii=False)
print(json.dumps(out, ensure_ascii=False)[:1800])
