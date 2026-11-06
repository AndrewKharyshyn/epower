#!/usr/bin/env python3
"""M592: read-only re-check that the live payload block cellSpreadStep (M574 / M580) equals a fresh run of tools/m573_cell_spread_step.py on the current master and the current regime reader (M585).
Writes analyses/M592_m574_recheck.json; changes nothing else (no --splice, no looks-ledger write). Usage: python tools/m592_m574_recheck.py"""
import hashlib, json, os, subprocess, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


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
    md5 = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    led_before = open(os.path.join(ROOT, "analyses", "M580_looks.json"), "rb").read()
    tmp = os.path.join(tempfile.mkdtemp(), "m573_rerun.json")
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "m573_cell_spread_step.py"), "--skip-raw", "--out", tmp], check=True, cwd=ROOT)
    new = json.load(open(tmp, encoding="utf-8"))
    pl = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))["cellSpreadStep"]
    res = {"milestone": "M592", "masterMd5": md5, "rerunMasterMd5": new["masterMd5"], "sections": {}}
    sections = {"analysisFrame": (new["analysisFrame"], pl["analysisFrame"]), "cadence": (new["item5_cadence"], pl["cadence"]), "confirmatory": (new["confirmatory"], pl["confirmatory"])}
    for nm, (a, b) in sections.items():
        fa, fb = flat(a), flat(b)
        res["sections"][nm] = {"nCompared": int(sum(1 for k in fa if k in fb)), "mismatches": [[k, fa[k], fb[k]] for k in fa if k in fb and fa[k] != fb[k]], "onlyInRerun": [k for k in fa if k not in fb]}
    res["allEqual"] = all(not s["mismatches"] and not s["onlyInRerun"] for s in res["sections"].values())
    assert open(os.path.join(ROOT, "analyses", "M580_looks.json"), "rb").read() == led_before, "looks ledger changed: STOP"
    with open(os.path.join(ROOT, "analyses", "M592_m574_recheck.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1)
    print(json.dumps({k: (v["nCompared"], len(v["mismatches"]), len(v["onlyInRerun"])) for k, v in res["sections"].items()}), res["allEqual"])


if __name__ == "__main__":
    main()
