#!/usr/bin/env python3
"""M593: leaf splice of the two regimeRule strings of the powerFade cadence-sensitivity block (1.05 s -> 1.10 s, the builder constant POWERFADE_FAST_S now equals tools/regime_reader.THRESHOLD_S).
The block was recomputed in memory with the new constant (compute_drive_summary_v6._powerfade_cadence_specs) and compared leaf by leaf with the payload: the ONLY differing leaf is regimeRule (any other difference STOPS).
Usage: python tools/m593_splice.py [--dry-run]"""
import copy, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import pandas as pd
import compute_drive_summary_v6 as D
import ah_throughput as AH

OLD, NEW = "fast: master I_sample_period_s < 1.05 s (M379a); slow otherwise", "fast: master I_sample_period_s < %.2f s (M379a, threshold M578); slow otherwise" % D.POWERFADE_FAST_S
OLD_CUT = float(OLD.split("< ")[1].split(" s")[0])
PATHS = (("powerFade", "cadenceSensitivity", "regimeRule"), ("fadeModes", "power", "trend", "cadenceSensitivity", "regimeRule"))


def flat(o, p=""):
    r = {}
    if isinstance(o, dict):
        for k, v in o.items():
            r.update(flat(v, p + "/" + str(k)))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            r.update(flat(v, p + "[%d]" % i))
    else:
        r[p] = o
    return r


def main():
    dry = "--dry-run" in sys.argv
    dm = pd.read_csv("drive_master.csv")
    ld = AH.raw_loader()
    cur = D._powerfade_cadence_specs(dm, ld)
    new_cut = D.POWERFADE_FAST_S
    D.POWERFADE_FAST_S = OLD_CUT
    old = D._powerfade_cadence_specs(dm, ld)
    fo, fn = flat(old), flat(cur)
    diff = [k for k in fo if fo[k] != fn.get(k)]
    # the drives whose stratum changes (period in [1.05, 1.10)) and whether they are in the clean complete-case set (nClean) of the specs
    keep = ~dm["ens_outlier_v2"].fillna(False).astype(bool) if "ens_outlier_v2" in dm.columns else pd.Series(True, index=dm.index)
    rcol = "vreg_R_pack_mohm" if "vreg_R_pack_mohm" in dm.columns else "vsag_R_pack_mohm"
    icol = "vreg_I_p95_A" if rcol == "vreg_R_pack_mohm" else "vsag_I_mean_A"
    inclean = keep & dm[[rcol, "T_pack_mean_avg", icol, "date"]].notna().all(axis=1)
    mv = dm[(dm["I_sample_period_s"] >= OLD_CUT) & (dm["I_sample_period_s"] < new_cut)]
    movers = [{"file": r.file, "periodS": round(float(r.I_sample_period_s), 3), "regimeUnderOldCut": "slow", "regimeUnderNewCut": "fast", "inCleanSet": bool(inclean[r.Index])} for r in mv.itertuples()]
    chk = {"milestone": "M593", "masterMd5": __import__("hashlib").md5(open("drive_master.csv", "rb").read()).hexdigest(), "nLeavesCompared": len(fo), "differingLeaves": diff, "nCleanOldSpecs": old.get("nClean"), "nCleanNewSpecs": cur.get("nClean"),
           "driveStratumMovers": movers, "newRegimeRule": cur.get("regimeRule"), "oldRegimeRule": old.get("regimeRule")}
    if not dry:
        with open("analyses/M593_splice_check.json", "w", encoding="utf-8", newline="\n") as f:
            json.dump(chk, f, indent=1)
    print(json.dumps({k: chk[k] for k in ("nLeavesCompared", "differingLeaves", "driveStratumMovers")}))
    if diff != ["/regimeRule"]:
        raise SystemExit("M593 STOP: the specs block differs in more than regimeRule: %s" % diff)
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    new = copy.deepcopy(A)
    for path in PATHS:
        o = new
        for k in path[:-1]:
            o = o[k]
        if o[path[-1]] != OLD:
            raise SystemExit("M593 STOP: unexpected leaf at %s: %r" % ("/".join(path), o[path[-1]]))
        o[path[-1]] = NEW
    fa_, fn_ = flat(A), flat(new)
    changed = [k for k, v in fa_.items() if fn_[k] != v]
    assert len(changed) == 2, changed
    print("leaves to change:", changed)
    if not dry:
        with open("summary_arrays.json", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(new, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
