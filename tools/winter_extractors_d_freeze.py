#!/usr/bin/env python3
"""M736 (analyses/M736_spec.md Rev 1, section 3): writes the extractor registry analyses/M736_extractor_registry.json (version 4). It is the v3 registry content rebuilt with the new winter_score.py (version 5), plus tools/winter_p2_v4.py and the M735 check file
(path-carry bound and offsets are read from it) and tools/winter_extractors_c_freeze.py's inputs unchanged; P2 gains the v4 handling. `supersedes`: the sha256 of the M731 registry (kept as history). P1 (M732) is not covered.
The registry's own sha256 is recorded in the CHANGELOG; after the freeze no extractor is edited. Usage: python tools/winter_extractors_d_freeze.py [--check]"""
import json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_extractors_c_freeze as C

REG = os.path.join(ROOT, "analyses", "M736_extractor_registry.json")


def build():
    reg = C.build()
    sp = C.sha("analyses/M736_spec.md")
    reg["milestone"], reg["spec"] = "M736", "analyses/M736_spec.md"
    reg["note"] = "registry v4: P2, P3, P4, P5, P6, P7 frozen; P2 adds the path-carry bound and the offset-adjusted sensitivity (tools/winter_p2_v4.py); P1 (M732) not covered"
    for pid, v in reg["perPrediction"].items():
        v["winterScoreV5Sha256"] = v.pop("winterScoreV4Sha256")
        if pid == "P2":
            v["function"] += " + tools/winter_p2_v4.py::p2_v4"
            v["specSha256"] = sp
    for m in ("tools/winter_p2_v4.py", "analyses/M735_p2_window_check.json", "analyses/M731_extractor_registry.json"):
        reg["modules"][m] = C.sha(m)
    reg["supersedes"] = {"registry": "analyses/M731_extractor_registry.json", "sha256": C.sha("analyses/M731_extractor_registry.json")}
    return reg


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    reg = build()
    if "--check" in argv:
        have = json.load(open(REG, encoding="utf-8")) if os.path.exists(REG) else None
        ok = have == reg
        print(json.dumps({"check": "extractor registry v4", "matches": ok}))
        return 0 if ok else 1
    if os.path.exists(REG):
        print("STOP: the registry exists; a change is a new version with a new registry")
        return 1
    with open(REG, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(reg, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"written": "analyses/M736_extractor_registry.json", "sha256": C.sha("analyses/M736_extractor_registry.json"), "predictions": reg["predictions"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
