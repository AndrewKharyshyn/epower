#!/usr/bin/env python3
"""Post-ingestion splices as ONE ingestion stage (M377a, analyses/M377_spec.md Rev 2 P1). The arrays rebuild drops additive keys and labels written
after M356 by one-off splice tools; this stage re-applies them in order, each through its own deep-diff-guarded tool:
  tools/m361_splice.py          records intake-air notes (leaf strings)
  tools/m362_splice.py --splice engine-start distribution fields (computed from the live corpus, additive)
  tools/m363_splice.py          comparisonCube / engineStartRate label strings
  crawlStopGo.phaseEnergy.blindAudit (+ seasonal copies) restored from analyses/M356_blindaudit_record.json (M377b P4; labelled historical record)
  fuelAnalytics.fuel12.m366Shift restored from analyses/M366_shift_record.json (frozen historical record carrying basis / milestone / basisNDrives; only that key may change)
Idempotent (a second run leaves summary_arrays.json byte-identical). Any tool failure stops the stage (non-zero exit). Never writes drive_master.csv.
Usage: python tools/post_splices.py"""
import copy, hashlib, json, os, subprocess, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
STEPS = [["tools/m361_splice.py"], ["tools/m362_splice.py", "--splice"], ["tools/m363_splice.py"]]


def restore_m366_shift(path="summary_arrays.json", record="analyses/M366_shift_record.json"):
    rec = json.load(open(record, encoding="utf-8"))
    for k in ("basis", "milestone", "basisNDrives"):
        assert rec.get(k), f"M366 shift record lacks {k}"
    raw = open(path, "rb").read()
    A = json.loads(raw.decode("utf-8"))
    old = copy.deepcopy(A)
    F = A["fuelAnalytics"]["fuel12"]
    if "m366Shift" not in F:
        F["m366Shift"] = rec
        action = "restored"
    else:
        cur = F["m366Shift"]
        extras = {k: v for k, v in rec.items() if k in ("basis", "milestone", "basisNDrives")}
        body = {k: v for k, v in cur.items() if k not in extras}
        assert body == {k: v for k, v in rec.items() if k not in extras}, "fuel12.m366Shift differs from the frozen record beyond basis/milestone/basisNDrives: STOP"
        for k, v in extras.items():
            if cur.get(k) != v:
                cur[k] = v
        action = "unchanged" if A == old else "basis fields added"
    # deep-diff: only fuelAnalytics.fuel12.m366Shift may differ
    chk = copy.deepcopy(A)
    del chk["fuelAnalytics"]["fuel12"]["m366Shift"]
    base = copy.deepcopy(old)
    base["fuelAnalytics"]["fuel12"].pop("m366Shift", None)
    assert chk == base, "m366 restore changed something else: STOP"
    if A != old:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(A, ensure_ascii=False, indent=1))
    return action


ADDITIVE_LEAVES = {"CrawlStopGo": ("/phaseEnergy/blindAudit",)}      # M384: leaves this stage adds after the builders ran (registry of tools/parity_compare.py)


def restore_blind_audit(path="summary_arrays.json", record="analyses/M356_blindaudit_record.json"):
    """crawlStopGo.phaseEnergy.blindAudit (+ the three seasonal copies): frozen M356-era records carrying basisNDrives / basisMilestone / basisNote (M377b P4).
    Restored when absent; when present the body must equal the record; only these four keys may change."""
    R = json.load(open(record, encoding="utf-8"))["blocks"]
    for r in R.values():
        for k in ("basisNDrives", "basisMilestone", "basisNote"):
            assert r.get(k), f"blind-audit record lacks {k}"
    A = json.loads(open(path, "rb").read().decode("utf-8"))
    old = copy.deepcopy(A)
    targets = {"top": A["crawlStopGo"]["phaseEnergy"], **{c: A["seasonalCharts"]["charts"]["CrawlStopGo"]["data"][c]["phaseEnergy"] for c in ("all", "warm", "shoulder")}}
    done = []
    for k, pe in targets.items():
        if "blindAudit" not in pe:
            pe["blindAudit"] = copy.deepcopy(R[k]); done.append(k)
        else:
            ex = ("basisNDrives", "basisMilestone", "basisNote")
            assert {x: v for x, v in pe["blindAudit"].items() if x not in ex} == {x: v for x, v in R[k].items() if x not in ex}, f"phaseEnergy.blindAudit ({k}) differs from the frozen record: STOP"
            if any(pe["blindAudit"].get(x) != R[k][x] for x in ex):
                pe["blindAudit"].update({x: R[k][x] for x in ex}); done.append(k + "(basis fields)")
    chk = copy.deepcopy(A)
    for pe in [chk["crawlStopGo"]["phaseEnergy"]] + [chk["seasonalCharts"]["charts"]["CrawlStopGo"]["data"][c]["phaseEnergy"] for c in ("all", "warm", "shoulder")]:
        pe.pop("blindAudit", None)
    base = copy.deepcopy(old)
    for pe in [base["crawlStopGo"]["phaseEnergy"]] + [base["seasonalCharts"]["charts"]["CrawlStopGo"]["data"][c]["phaseEnergy"] for c in ("all", "warm", "shoulder")]:
        pe.pop("blindAudit", None)
    assert chk == base, "blind-audit restore changed something else: STOP"
    if A != old:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(A, ensure_ascii=False, indent=1))
    return "restored " + ",".join(done) if done else "unchanged"


def main():
    env = dict(os.environ, PYTHONUTF8="1")
    for step in STEPS:
        r = subprocess.run([sys.executable, *step], cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8")
        print(f"[post_splices] {' '.join(step)} -> rc={r.returncode}: {(r.stdout.strip().splitlines() or [''])[-1][:160]}")
        if r.returncode != 0:
            sys.stderr.write(r.stdout[-800:] + r.stderr[-800:])
            sys.exit(r.returncode)
    print("[post_splices] fuel12.m366Shift:", restore_m366_shift())
    print("[post_splices] phaseEnergy.blindAudit:", restore_blind_audit())


if __name__ == "__main__":
    main()
