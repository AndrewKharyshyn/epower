#!/usr/bin/env python3
"""M490 acceptance run (spec analyses/M490_spec.md Rev 2, acceptance A-E): the effect of the total-overlap support rule (regen_v2.touch_flags) on the per-drive caches and on every regeneration block the regen_v2 stage writes.
Nothing is written to summary_arrays.json or to regen_cache/. The OLD state is the stored payload and the stored cache (regen_cache/, built by the former per-piece rule); the NEW state is built into a scratch cache directory by the
current extractor and aggregated by the stage code in dry-run mode (a captured in-memory payload).
  Phase 1  (--build SCRATCH)     run the stage computation against a new cache directory SCRATCH; saves SCRATCH/new_blocks.json (regenCaptureV2, regenCaptureV2H, regenSocStandardized, regenDisplayV2)
  Phase 2  (--compare SCRATCH)   A  energy / charge / intervals byte-identical per variant per drive (touch excluded); B  touch flags: new superset of old (no true->false), flip counts per cadence stratum;
                                 C  every support count and support status in the stage blocks before / after (cells whose status changes are listed); E  stop flags; writes analyses/M490_results.json
Usage: python tools/m490_touch_effect.py --build SCRATCH_OLD  (with the former tools/regen_v2.py), then --build SCRATCH_NEW (M490 extractor), then --compare SCRATCH_OLD SCRATCH_NEW [--workers N]"""
import hashlib, json, os, sys

# the cache directory must be fixed BEFORE regen_v2_cache is imported: the extraction workers are spawned processes that re-import it and read XT_REGEN_CACHE_DIR
_argv = sys.argv[1:]
if "--build" in _argv:
    os.environ["XT_REGEN_CACHE_DIR"] = os.path.join(os.path.abspath(_argv[_argv.index("--build") + 1]), "cache")
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
for p_ in (ROOT, os.path.join(ROOT, "tools")):
    if p_ not in sys.path:
        sys.path.insert(0, p_)
import regen_v2_cache as K

BLOCKS = ["regenCaptureV2", "regenCaptureV2H", "regenSocStandardized", "regenDisplayV2"]


def build(scratch, workers):
    assert os.path.abspath(K.CACHE_DIR) == os.path.join(os.path.abspath(scratch), "cache"), K.CACHE_DIR
    os.makedirs(K.CACHE_DIR, exist_ok=True)
    import regen_v2_stage as S
    cap = {}
    orig = S.diff
    S.diff = lambda a, b, p="": (cap.setdefault("N", b), orig(a, b, p))[1]
    rc = S.main(["--dry-run"])
    N = cap["N"]
    json.dump({k: N.get(k) for k in BLOCKS}, open(os.path.join(scratch, "blocks.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(json.dumps({"stageReturn": rc, "blocks": [k for k in BLOCKS if N.get(k) is not None]}))
    return rc


def walk(o, p=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from walk(v, p + "/" + k)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from walk(v, "%s[%d]" % (p, i))
    else:
        yield p, o


SUPPORT_KEYS = ("Ns", "Np", "Sec", "Pd", "Zs", "nStrict", "nIntervals", "nDrives", "nDays", "days", "drives", "intervals", "nZeroCharge", "status", "supported", "thin", "intervalShare", "support", "nSupport")


def compare_caches(old_s, new_s):
    OLD_DIR, new_dir = os.path.join(old_s, "cache"), os.path.join(new_s, "cache")
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    cad = dm["ev_rpm_dt_med_s"].map(lambda x: "unknown" if not np.isfinite(x) else ("fast" if x < 1.0 else "slow"))
    cad = dict(zip(dm["file"], cad))
    out = {"variants": {}, "energyIdentical": True, "monotone": True}
    for v in sorted(os.listdir(new_dir)):
        vd = os.path.join(new_dir, v)
        if not os.path.isdir(vd):
            continue
        rec = {"nDrives": 0, "nIdenticalIntervalsAndEnergy": 0, "energyDiffs": [], "flips": {"fast": 0, "slow": 0, "unknown": 0}, "flagsOld": {"fast": 0, "slow": 0, "unknown": 0}, "flagsNew": {"fast": 0, "slow": 0, "unknown": 0}, "trueToFalse": 0}
        for fn in sorted(f for f in os.listdir(vd) if f.endswith(".npz") and not f.endswith(".off.npz")):
            name = fn[:-4]
            op = os.path.join(OLD_DIR, v, fn)
            if not os.path.exists(op):
                rec.setdefault("missingOld", []).append(name)
                continue
            with np.load(op, allow_pickle=False) as zo, np.load(os.path.join(vd, fn), allow_pickle=False) as zn:
                rec["nDrives"] += 1
                if "iv_t0" not in zo.files:
                    continue
                same = True
                for k in zo.files:
                    if k in ("hdr", "bin_touch"):
                        continue
                    if k not in zn.files or not np.array_equal(zo[k], zn[k], equal_nan=True):
                        same = False; rec["energyDiffs"].append([name, k])
                if same:
                    rec["nIdenticalIntervalsAndEnergy"] += 1
                to, tn = zo["bin_touch"].astype(bool), zn["bin_touch"].astype(bool)
                c = cad.get(name, "unknown")
                rec["flagsOld"][c] += int(to.sum()); rec["flagsNew"][c] += int(tn.sum())
                rec["flips"][c] += int((tn & ~to).sum()); rec["trueToFalse"] += int((to & ~tn).sum())
        out["variants"][v] = rec
        out["energyIdentical"] &= not rec["energyDiffs"]
        out["monotone"] &= rec["trueToFalse"] == 0
    return out


def compare_blocks(old_s, new_s):
    old = json.load(open(os.path.join(old_s, "blocks.json"), encoding="utf-8"))
    new = json.load(open(os.path.join(new_s, "blocks.json"), encoding="utf-8"))
    res = {}
    for b in BLOCKS:
        a, c = dict(walk(old.get(b))), dict(walk(new.get(b)))
        changed = sorted(k for k in a if k in c and a[k] != c[k])
        added = sorted(k for k in c if k not in a)
        removed = sorted(k for k in a if k not in c)
        # value-like leaves (ratios, intervals) versus support-like leaves: classify by the last path component
        last = lambda p: p.rsplit("/", 1)[-1].split("[")[0]
        support_changed = [k for k in changed if last(k) in SUPPORT_KEYS]
        other_changed = [k for k in changed if last(k) not in SUPPORT_KEYS]
        status_changed = [k for k in changed if last(k) in ("status", "supported", "thin")]
        res[b] = {"nLeaves": len(a), "nChanged": len(changed), "nAdded": len(added), "nRemoved": len(removed), "nSupportLeavesChanged": len(support_changed), "nOtherLeavesChanged": len(other_changed),
                  "statusLeavesChanged": status_changed[:60], "otherChangedSample": other_changed[:40], "addedSample": added[:10], "removedSample": removed[:10], "supportChangedSample": support_changed[:20]}
    return res


def main(argv):
    if "--build" in argv:
        return build(argv[argv.index("--build") + 1], int(argv[argv.index("--workers") + 1]) if "--workers" in argv else 5)
    if "--compare" not in argv:
        print(__doc__); return 2
    old_s, new_s = argv[argv.index("--compare") + 1], argv[argv.index("--compare") + 2]
    caches = compare_caches(old_s, new_s)
    blocks = compare_blocks(old_s, new_s)
    stop = []
    if not caches["energyIdentical"]:
        stop.append("A: intervals / energy arrays differ between the old and the new cache")
    if not caches["monotone"]:
        stop.append("B: a touch flag changed true -> false")
    for b, r in blocks.items():
        if r["statusLeavesChanged"]:
            stop.append("C/E: support status leaves changed in %s" % b)
    res = {"_provenance": "GENERATED by tools/m490_touch_effect.py (spec analyses/M490_spec.md Rev 2); old = the stage run with the former extractor (git HEAD tools/regen_v2.py) into its own cache directory, new = the same run with the M490 extractor; identical environment, nothing written to regen_cache/ or summary_arrays.json",
           "masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(), "specSha256": hashlib.sha256(open("analyses/M490_spec.md", "rb").read()).hexdigest(),
           "caches": caches, "blocks": blocks, "stopConditions": stop}
    with open("analyses/M490_results.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
    print(json.dumps({"energyIdentical": caches["energyIdentical"], "monotone": caches["monotone"], "variants": {v: {k: r[k] for k in ("nDrives", "nIdenticalIntervalsAndEnergy", "flips", "trueToFalse")} for v, r in caches["variants"].items()},
                      "blocks": {b: {k: r[k] for k in ("nChanged", "nSupportLeavesChanged", "nOtherLeavesChanged")} for b, r in blocks.items()}, "stop": stop}, indent=1)[:4000])
    return 1 if stop else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
