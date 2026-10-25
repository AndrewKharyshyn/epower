#!/usr/bin/env python3
"""M511 (audit 2026-10-25 A03, spec analyses/M511_spec.md Rev 2): recompute ONLY the key socBalancedFuel with the canonical-clean primary population
(eligibility.py) and the matched allAccumulatorSensitivity, check it against control C0 and the pre-registered escalation rules, and splice it
(additive leaf-splice pattern: compute only the changed key, deep-diff, splice).
C0: the same code run unfiltered must equal the STORED block leaf for leaf (methodology string excluded), else STOP (provenance drift is never mixed in).
Independent membership check: the excluded set must equal the accepted accumulator trips whose master flag is True, derived here from drive_master.csv.
Escalation (R5): more than 5 trips or more than 2 days excluded, headline outside the previous CI, sign of fleetDelta flipped, dateSpan changed.
Reads staged raw_only/ (master-key view of raw/). Never writes drive_master.csv or raw files.
Usage: python tools/m511_fuel_eligibility_splice.py [--dry-run]"""
import hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import pandas as pd
import compute_summary_arrays as cs

ARR = os.path.join(ROOT, "summary_arrays.json")
OUT = os.path.join(ROOT, "analyses", "M511_result.json")
NEW_KEYS = ("/eligibility", "/allAccumulatorSensitivity", "/methodology")
MAX_TRIPS, MAX_DAYS = 5, 2


def diff(a, b, p=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(p + "/" + k + " (missing)")
            else:
                out += diff(a[k], b[k], p + "/" + k)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, p + f"[{i}]")
    elif a != b:
        out.append(p)
    return out


def rt(x):
    return json.loads(json.dumps(x, default=float))


def main():
    dry = "--dry-run" in sys.argv
    A = json.load(open(ARR, encoding="utf-8"))
    old = A["socBalancedFuel"]
    dm_path = os.path.join(ROOT, "drive_master.csv")
    md5_before = hashlib.md5(open(dm_path, "rb").read()).hexdigest()
    dm = pd.read_csv(dm_path)
    if "eligibility" in old:
        print(json.dumps({"status": "unchanged", "note": "stored socBalancedFuel already carries the M511 eligibility block"})); return
    ctrl = rt(cs._soc_balanced_fuel(dm, None, "raw_only", _apply_eligibility=False))
    c0 = [p for p in diff(ctrl, old) if p != "/methodology"]
    if c0:
        print(json.dumps({"STOP": "C0 control does not reproduce the stored block (provenance drift, not an M511 effect)", "differences": c0[:20]}, indent=1)); sys.exit(2)
    new = rt(cs._soc_balanced_fuel(dm, None, "raw_only"))
    el, sens = new["eligibility"], new.get("allAccumulatorSensitivity")
    # independent membership: accepted accumulator trips with a True master flag
    acc = [x["file"] for x in [cs._hf_perdrive(f, None, "raw_only") and dict(file=f) for f in dm["file"]] if x]
    fl = dm.set_index("file")
    indep = sorted(f for f in acc if str(fl.loc[f, "ens_outlier_v2"]).strip().lower() == "true" or str(fl.loc[f, "ens_invalid"]).strip().lower() == "true")
    members_ok = indep == sorted(x["file"] for x in el["excludedFiles"]) and len(acc) == el["nAcceptedAccumulatorTrips"]
    # sensitivity must equal the pre-M511 block on every shared headline leaf
    sens_ok = True
    if sens is not None:
        sens_ok = (sens["socBalancedFleetL100"] == old["socBalancedFleetL100"] and sens["rawFleetL100"] == old["rawFleetL100"]
                   and sens["socBalancedFleetBoot"] == old["socBalancedFleetBoot"] and sens["nDrives"] == old["nDrives"] and sens["nDays"] == old["nDays"])
    # leaves of other payload keys must not move: only socBalancedFuel is replaced
    changed = diff(new, old)
    ci = old["socBalancedFleetBoot"]["ci95"]
    inside = ci[0] <= new["socBalancedFleetL100"] <= ci[1]
    sign_same = (old["socBalancedFleetDelta"] > 0) == (new["socBalancedFleetDelta"] > 0)
    esc = {"tooManyTrips": el["nExcludedByRule"] > MAX_TRIPS,
           "tooManyDays": len({x["date"] for x in el["excludedFiles"]}) > MAX_DAYS,
           "headlineOutsidePreviousCi": not inside, "signFlipped": not sign_same, "dateSpanChanged": new["dateSpan"] != old["dateSpan"]}
    res = {"milestone": "M511", "audit": "A03", "spec": "analyses/M511_spec.md (Rev 2)",
           "specSha256": hashlib.sha256(open(os.path.join(ROOT, "analyses", "M511_spec.md"), "rb").read()).hexdigest(),
           "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(), "masterMd5": md5_before,
           "control": "C0 passed: unfiltered run reproduces the stored socBalancedFuel leaf for leaf (methodology text excluded)",
           "membershipIndependentOk": bool(members_ok), "sensitivityEqualsPreM511Block": bool(sens_ok),
           "excluded": el["excludedFiles"], "nAccepted": el["nAcceptedAccumulatorTrips"], "nPrimary": new["nDrives"], "nDaysPrimary": new["nDays"],
           "before": {k: old[k] for k in ("nDrives", "nDays", "dateSpan", "rawFleetL100", "socBalancedFleetL100", "socBalancedFleetDelta", "socBalancedFleetBoot")},
           "after": {k: new[k] for k in ("nDrives", "nDays", "dateSpan", "rawFleetL100", "socBalancedFleetL100", "socBalancedFleetDelta", "socBalancedFleetBoot")},
           "headlineInsidePreviousCi95": bool(inside), "changedLeaves": changed, "escalation": esc, "escalate": bool(any(esc.values())),
           "rawFleetNote": "rawFleetL100 has no stored interval; compared as a delta only", "rawSource": "raw_only/ (staged master-key view of raw/)",
           "limits": "CAP_KWH 2.1 verified:false; fuel logged/app-calculated; eligibility-policy alignment, estimand unchanged"}
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1, ensure_ascii=False); f.write("\n")
    status = "unchanged" if not changed else "spliced"
    if not (members_ok and sens_ok) or res["escalate"]:
        print(json.dumps({"STOP": "membership/sensitivity check failed or escalation triggered; nothing spliced", "membersOk": members_ok, "sensOk": sens_ok, "escalation": esc}, default=float)); sys.exit(3)
    if not dry and changed:
        A["socBalancedFuel"] = new
        with open(ARR, "w", encoding="utf-8", newline="\n") as f:
            json.dump(A, f, ensure_ascii=False, indent=1)
    print(json.dumps({"status": status, "nChanged": len(changed), "excluded": [x["file"] for x in el["excludedFiles"]], "before": res["before"], "after": res["after"],
                      "insideOldCi": bool(inside), "masterMd5Unchanged": hashlib.md5(open(dm_path, "rb").read()).hexdigest() == md5_before}, default=float))


if __name__ == "__main__":
    main()
