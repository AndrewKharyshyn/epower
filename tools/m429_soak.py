#!/usr/bin/env python3
"""M429 (spec analyses/M429_spec.md Rev 2, audit F06): single-key recompute of the parked-soak blocks from the live master, the cached frames and the config ambients (the same inputs as the pipeline).

  python tools/m429_soak.py run    [--out analyses/M429_result.json]   # recompute heatSoakCarryover + interDriveCarryover.thermalDecay.{coolant,oil}; gate G1 against the payload
  python tools/m429_soak.py verify                                      # gate G3: the recompute is byte-identical to the spliced payload leaves
drive_master.csv, the raw files and the frame cache are only read."""
import hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import pandas as pd
import compute_summary_arrays as C
import drive_raw_cache as drc

sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
canon = lambda o: json.dumps(o, sort_keys=True, ensure_ascii=False, default=float)
# leaves that M429 is allowed to change (spec section 5, G2); everything else of the three blocks must reproduce exactly (G1)
PACK_CHANGED = {"soakTauCI", "method", "soakTauCiMethod", "soakDecayRateK", "soakDecayRateKCI", "soakHalfLifeCI", "soakTauMethodTable", "soakTauLeaveOneDay", "soakTauGapSplit"}
DECAY_CHANGED = {"tauCI", "tauCiMethod", "decayRateK", "decayRateKCI", "halfLifeCI", "methodTable", "leaveOneDay", "gapSplit"}


def recompute():
    import soak_tau
    soak_tau.CAPTURE = []
    dm = pd.read_csv("drive_master.csv", low_memory=False)
    cfg = json.load(open("summary_config.json", encoding="utf-8"))
    amb = cfg.get("ambientByDrive")
    stage = os.path.join(ROOT, "raw_only")
    fl = drc.make_frame_loader(raw_dir=stage)

    def loader(fn):
        with open(os.path.join(stage, fn), "rb") as f:
            return f.read()
    traj = C._battery_temp_traj(dm, loader, frame_loader=fl)
    hsc = C._heat_soak_carryover(dm, traj, amb)
    pf = C._linked_adjacent_drive_table(dm, traj, amb, frame_loader=fl)
    cool = C._carryover_thermal_decay(pf, "arrivalCoolantC", "prevEndCoolantC", "arrivalAmbientC")
    oil = C._carryover_thermal_decay(pf, "arrivalOilC", "prevEndOilC", "arrivalAmbientC")
    return dm, hsc, cool, oil, list(soak_tau.CAPTURE)


def _frozen_previous():
    """The intervals as published before M429, read from the frozen historical file (a re-run after the splice must not overwrite them with the new values)."""
    rows = json.load(open("analyses/M429_published_rule.json", encoding="utf-8"))["rows"]
    return {"soakTauCI": rows["pack"]["tauCI"], "coolantTauCI": rows["coolant"]["tauCI"], "oilTauCI": rows["oil"]["tauCI"], "source": "analyses/M429_published_rule.json"}


def out_path(argv):
    return argv[argv.index("--out") + 1] if "--out" in argv else "analyses/M429_result.json"


def g1(old, new, changed, name):
    """Every leaf outside the allowed set reproduces exactly; the allowed set is the only difference in keys and values."""
    bad = [k for k in sorted(set(old) | set(new)) if k not in changed and canon(old.get(k)) != canon(new.get(k))]
    return {"block": name, "ok": not bad, "differingOutsideAllowed": bad, "nKeysOld": len(old), "nKeysNew": len(new)}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    dm, hsc, cool, oil, cap = recompute()
    md5 = hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest()
    old_h = A["heatSoakCarryover"]
    old_d = A["interDriveCarryover"]["thermalDecay"]
    if cmd == "verify":
        ok = canon(old_h) == canon(hsc) and canon(old_d["coolant"]) == canon(cool) and canon(old_d["oil"]) == canon(oil)
        bat = old_d["battery"]
        ok = ok and bat.get("tauCI") == hsc.get("soakTauCI") and bat.get("tauCiMethod") == hsc.get("soakTauCiMethod")
        print(json.dumps({"G3_singleKeyRecomputeIdenticalToPayload": ok}))
        sys.exit(0 if ok else 1)
    gates = [g1(old_h, hsc, PACK_CHANGED, "heatSoakCarryover"), g1(old_d["coolant"], cool, DECAY_CHANGED, "coolant"), g1(old_d["oil"], oil, DECAY_CHANGED, "oil")]
    res = {"_provenance": {"spec": "analyses/M429_spec.md", "specSha256": sha("analyses/M429_spec.md"), "masterMd5": md5, "scriptSha256": sha(__file__), "soakTauSha256": sha("tools/soak_tau.py"),
                           "producerSha256": sha("compute_summary_arrays.py"),
                           "label": "model-derived; conditional on the pairing and the manual driving-time ambient field; unvalidated"},
           "G1": gates, "previousPayload": _frozen_previous(),
           "heatSoakCarryover": hsc, "coolant": cool, "oil": oil}
    pairs_path = os.path.join(os.path.dirname(os.path.abspath(out_path(sys.argv))), "M429_pairs.json")
    with open(pairs_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"order": ["pack", "coolant", "oil"], "fits": cap, "note": "the fitted pairs (ln(resid/init excess) vs parking gap) of the three soak fits as the producers build them; arrival day = following drive's start day, departure day = previous drive's end day"}) + "\n")
    out = out_path(sys.argv)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(res, indent=1, ensure_ascii=False, default=float) + "\n")
    print(json.dumps({"G1": [{"block": g["block"], "ok": g["ok"], "differing": g["differingOutsideAllowed"]} for g in gates]}))
    if not all(g["ok"] for g in gates):
        sys.exit(1)


if __name__ == "__main__":
    main()
