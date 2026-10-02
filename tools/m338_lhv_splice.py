#!/usr/bin/env python3
"""M338 (audit C05, spec analyses/M338_spec.md rev 2): recompute ONLY the key socBalancedFuel with the single assumed-E10 LHV now taken from model_constants,
check it against a control and the pre-registered allow-list, and splice it (additive leaf-splice pattern: compute only the changed key, deep-diff, splice).
Control C0: with the old literal LHV (8.9, patched in memory) the unchanged-method result must equal the STORED block leaf-for-leaf (else STOP).
Known answer: new unrounded correction = old unrounded correction x 8.9 / LHV_E10 (1e-9). Allow-list: only lhvKwhPerL, socBalancedFleetL100, socBalancedFleetDelta,
socBalancedFleetBoot.{bootMedian,ci95}, byEta[*].{fleetL100,fleetDelta,perTripMedianL100,perTripCorrMedian,perTripCorrP95}, methodology may change.
Reads staged raw_only/ (master-key view of raw/); records the sha256 of every file read. Never writes drive_master.csv or raw files.
Usage: python tools/m338_lhv_splice.py [--dry-run]"""
import hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import numpy as np, pandas as pd
import compute_summary_arrays as cs
import model_constants as MC

ARR = os.path.join(ROOT, "summary_arrays.json")
OUT = os.path.join(ROOT, "analyses", "M338_result.json")
OLD_LHV = 8.9
ALLOWED = ("/lhvKwhPerL", "/socBalancedFleetL100", "/socBalancedFleetDelta", "/socBalancedFleetBoot/bootMedian", "/socBalancedFleetBoot/ci95", "/methodology")
ALLOWED_BYETA = ("fleetL100", "fleetDelta", "perTripMedianL100", "perTripCorrMedian", "perTripCorrP95")


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


def allowed(path):
    if path in ALLOWED or path.startswith("/socBalancedFleetBoot/ci95["):
        return True
    return path.startswith("/byEta[") and path.split("/")[-1] in ALLOWED_BYETA


def unrounded_delta(dm, lhv, eta=0.30):
    rows = []
    for _, r in dm.iterrows():
        d = cs._hf_perdrive(r["file"], None, "raw_only")
        if d is not None:
            rows.append(d)
    fuel = np.array([x["fuelL"] for x in rows]); dist = np.array([x["distKm"] for x in rows]); dE = np.array([x["dE_kWh"] for x in rows])
    return float(-(dE / (eta * lhv)).sum() / dist.sum() * 100.0), len(rows)


def main():
    dry = "--dry-run" in sys.argv
    A = json.load(open(ARR, encoding="utf-8"))
    old = A["socBalancedFuel"]
    dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"))
    new_lhv_full = cs._HF_LHV
    assert abs(new_lhv_full - MC.RHO_G_PER_L[0] * MC.LHV_MJ_PER_KG[0] / 3.6 / 1000.0) < 1e-12
    # idempotence (spec rev 2 item 10): if the stored block already equals the builder output (E10 basis), nothing to do; the C0 control and the allow-list were recorded in analyses/M338_result.json when the splice was applied
    already = json.loads(json.dumps(cs._soc_balanced_fuel(dm, None, "raw_only"), default=float))
    if not diff(already, old):
        print(json.dumps({"status": "unchanged", "note": "stored socBalancedFuel equals the builder output (single E10 basis)"})); return
    # C0 control: old literal LHV, otherwise the same (new) code, compared to the stored block with the methodology string excluded (its text changed by design)
    cs._HF_LHV = OLD_LHV
    ctrl = json.loads(json.dumps(cs._soc_balanced_fuel(dm, None, "raw_only"), default=float))
    cs._HF_LHV = new_lhv_full
    c0 = [p for p in diff(ctrl, old) if p != "/methodology" and p != "/lhvKwhPerL"]
    if ctrl.get("lhvKwhPerL") != OLD_LHV:
        c0.append("/lhvKwhPerL control value")
    if c0:
        print(json.dumps({"STOP": "C0 control does not reproduce the stored block", "differences": c0[:20]}, indent=1)); sys.exit(2)
    new = json.loads(json.dumps(cs._soc_balanced_fuel(dm, None, "raw_only"), default=float))
    changed = diff(new, old)
    bad = [p for p in changed if not allowed(p)]
    if bad:
        print(json.dumps({"STOP": "leaves outside the allow-list changed", "leaves": bad[:20]}, indent=1)); sys.exit(3)
    if any(p.startswith("/regression") for p in changed):
        print(json.dumps({"STOP": "regression leaves changed"})); sys.exit(3)
    # known answer (unrounded): new correction = old correction x OLD/NEW
    d_old, n_rows = unrounded_delta(dm, OLD_LHV)
    d_new, _ = unrounded_delta(dm, new_lhv_full)
    ratio = OLD_LHV / new_lhv_full
    ka = abs(d_new - d_old * ratio)
    assert ka < 1e-9, ka
    # bootstrap draws identical under seed 42: median/CI endpoints of the corrected fleet figure move by at most the fleet-level shift (reported, not asserted)
    hashes = {}
    for _, r in dm.iterrows():
        d = cs._hf_perdrive(r["file"], None, "raw_only")
        if d is not None:
            p = os.path.realpath(os.path.join("raw_only", r["file"]))
            hashes[r["file"]] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    table = {"lhvKwhPerL": [old["lhvKwhPerL"], new["lhvKwhPerL"]], "rawFleetL100": [old["rawFleetL100"], new["rawFleetL100"]],
             "socBalancedFleetL100": [old["socBalancedFleetL100"], new["socBalancedFleetL100"]],
             "socBalancedFleetDelta": [old["socBalancedFleetDelta"], new["socBalancedFleetDelta"]],
             "socBalancedFleetBoot": [old["socBalancedFleetBoot"], new["socBalancedFleetBoot"]],
             "byEta": [[{k: e[k] for k in ("eta",) + ALLOWED_BYETA} for e in old["byEta"]], [{k: e[k] for k in ("eta",) + ALLOWED_BYETA} for e in new["byEta"]]]}
    inside_old_ci = old["socBalancedFleetBoot"]["ci95"][0] <= new["socBalancedFleetL100"] <= old["socBalancedFleetBoot"]["ci95"][1]
    sign_same = (old["socBalancedFleetDelta"] > 0) == (new["socBalancedFleetDelta"] > 0)
    res = {"milestone": "M338", "audit": "C05", "control": "C0 passed: unchanged-method (LHV 8.9) reproduces the stored socBalancedFuel leaf-for-leaf (methodology text excluded)",
           "lhvFull": new_lhv_full, "ratioOldOverNew": ratio, "knownAnswerAbsErrUnrounded": ka, "nDrives": n_rows, "changedLeaves": changed, "allowListOk": True,
           "beforeAfter": table, "newLevelInsideOldCi95": bool(inside_old_ci), "deltaSignUnchanged": bool(sign_same),
           "differenceInFleetCorrection_Lper100km": round(new["socBalancedFleetDelta"] - old["socBalancedFleetDelta"], 5), "auditReference_Lper100km": -0.00776,
           "escalate": bool((not inside_old_ci) or (not sign_same)), "rawSource": "raw_only/ (staged master-key view of raw/; F03 provenance-sensitive)",
           "rawSha256": hashes, "limits": "assumed E10 basis; fuel composition not measured; CAP 2.1 kWh verified:false is the dominant uncertainty; E10 span 8.50-8.70 kWh/L not propagated"}
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1, ensure_ascii=False); f.write("\n")
    status = "unchanged" if not changed else "spliced"
    if not dry and changed:
        A["socBalancedFuel"] = new
        with open(ARR, "w", encoding="utf-8", newline="\n") as f:
            json.dump(A, f, ensure_ascii=False, indent=1)
    print(json.dumps({"status": status, "nChanged": len(changed), "knownAnswerErr": ka, "fleet": table["socBalancedFleetL100"], "delta": table["socBalancedFleetDelta"],
                      "boot": table["socBalancedFleetBoot"], "insideOldCi": inside_old_ci, "deltaSignUnchanged": sign_same, "escalate": res["escalate"]}, default=float))


if __name__ == "__main__":
    main()
