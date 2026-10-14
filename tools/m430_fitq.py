#!/usr/bin/env python3
"""M430 (spec analyses/M430_spec.md Rev 2): single-key recompute of the held-out fit-quality leaves of the parked-soak fits from the live master, the cached frames and the config ambients
(the M429 recompute path = the same inputs as the pipeline).

  python tools/m430_fitq.py run [--out analyses/M430_result.json]   # recompute; gate G1 against the payload (every existing leaf identical except the new leaves and the two method strings)
  python tools/m430_fitq.py verify                                  # gate G3: the recompute is byte-identical to the spliced payload leaves
drive_master.csv, the raw files and the frame cache are only read."""
import hashlib, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import m429_soak as M
import soak_fitq

PACK_CHANGED = {"method", "soakFitQuality"}
DECAY_CHANGED = {"fitQuality"}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    A = json.load(open("summary_arrays.json", encoding="utf-8"))
    soak_fitq.CAPTURE = []
    dm, hsc, cool, oil, _cap = M.recompute()
    old_h, old_d = A["heatSoakCarryover"], A["interDriveCarryover"]["thermalDecay"]
    if cmd == "verify":
        ok = M.canon(old_h) == M.canon(hsc) and M.canon(old_d["coolant"]) == M.canon(cool) and M.canon(old_d["oil"]) == M.canon(oil)
        ok = ok and M.canon(old_d["battery"].get("fitQuality")) == M.canon(hsc.get("soakFitQuality"))
        print(json.dumps({"G3_singleKeyRecomputeIdenticalToPayload": ok}))
        sys.exit(0 if ok else 1)
    gates = [M.g1(old_h, hsc, PACK_CHANGED, "heatSoakCarryover"), M.g1(old_d["coolant"], cool, DECAY_CHANGED, "coolant"), M.g1(old_d["oil"], oil, DECAY_CHANGED, "oil")]
    res = {"_provenance": {"spec": "analyses/M430_spec.md", "specSha256": M.sha("analyses/M430_spec.md"), "masterMd5": hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest(),
                           "scriptSha256": M.sha(__file__), "soakFitqSha256": M.sha("tools/soak_fitq.py"), "producerSha256": M.sha("compute_summary_arrays.py"),
                           "label": "held-out, blocked-day cross-validated; model-derived; conditional on the pairing, the fold assignment and the manual driving-time ambient field; unvalidated"},
           "G1": gates, "heatSoakCarryover": hsc, "coolant": cool, "oil": oil}
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else "analyses/M430_result.json"
    pre = os.path.join(os.path.dirname(os.path.abspath(out)), "M430_prefilter_pairs.json")
    with open(pre, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"order": ["pack", "coolant", "oil"], "fits": list(soak_fitq.CAPTURE), "note": "the pairs BEFORE the residual-excess filter (initial excess > 3 C and residual excess > 0.5 C) as the producers see them: gap (h), initial and residual excess (C), arrival day; lets the exclusion counts be checked"}) + "\n")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(res, indent=1, ensure_ascii=False, default=float) + "\n")
    print(json.dumps({"G1": [{"block": g["block"], "ok": g["ok"], "differing": g["differingOutsideAllowed"]} for g in gates]}))
    if not all(g["ok"] for g in gates):
        sys.exit(1)


if __name__ == "__main__":
    main()
