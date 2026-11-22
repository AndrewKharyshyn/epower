#!/usr/bin/env python3
"""M732 (analyses/M732_spec.md Rev 2, section 4): writes the extractor registry analyses/M732_extractor_registry.json (version 5). It is the v4 registry content (tools/winter_extractors_d_freeze.build) rebuilt with the new winter_score.py (version 6), plus P1: tools/winter_p1.py, the frozen-basis fidelity
check (analyses/M732_fidelity_check.json) and the replay check. `supersedes`: the sha256 of the M736 registry (kept as history). After the freeze no extractor is edited; a change is a new version with a new registry.
Usage: python tools/winter_extractors_e_freeze.py [--check]"""
import json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_extractors_d_freeze as Dd
import winter_extractors_c_freeze as C
import winter_p1 as W1

REG = os.path.join(ROOT, "analyses", "M732_extractor_registry.json")


def build():
    reg = Dd.build()
    sp = C.sha("analyses/M732_spec.md")
    reg["milestone"], reg["spec"] = "M732", "analyses/M732_spec.md"
    reg["note"] = "registry v5: P1, P2, P3, P4, P5, P6, P7 frozen; P1 adds the free-run chain and the park-model pair cells (tools/winter_p1.py); P2 handling as v4"
    for v in reg["perPrediction"].values():
        v["winterScoreV6Sha256"] = v.pop("winterScoreV5Sha256")
    freeze = C.sha("analyses/M717_winter_predictions.json")
    reg["perPrediction"]["P1"] = {"function": "tools/winter_p1.py::extract_p1 (+ build_sidecar)", "version": W1.VERSION, "columns": W1.COLUMNS["P1"], "freezeFileSha256": freeze, "specSha256": sp, "winterScoreV6Sha256": C.sha("tools/winter_score.py")}
    reg["predictions"] = sorted(reg["perPrediction"])
    for m in ("tools/winter_p1.py", "analyses/M732_fidelity_check.json", "analyses/M732_replay_check.json", "analyses/M732/p1_basis_replay_sidecar.csv", "analyses/M736_extractor_registry.json"):
        reg["modules"][m] = C.sha(m)
    reg["supersedes"] = {"registry": "analyses/M736_extractor_registry.json", "sha256": C.sha("analyses/M736_extractor_registry.json")}
    return reg


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    reg = build()
    if "--check" in argv:
        have = json.load(open(REG, encoding="utf-8")) if os.path.exists(REG) else None
        ok = have == reg
        print(json.dumps({"check": "extractor registry v5", "matches": ok}))
        return 0 if ok else 1
    if os.path.exists(REG):
        print("STOP: the registry exists; a change is a new version with a new registry")
        return 1
    with open(REG, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(reg, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"written": "analyses/M732_extractor_registry.json", "sha256": C.sha("analyses/M732_extractor_registry.json"), "predictions": reg["predictions"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
