#!/usr/bin/env python3
"""M728 (analyses/M728_spec.md Rev 2, section 4): writes the extractor registry analyses/M728_extractor_registry.json (version 2) that freezes the extractors of P2, P3, P4, P5 and P7.
Per prediction id: function name, version, column list, the freeze file sha256, the spec sha256 and the winter_score.py v3 sha256; `modules`: path -> sha256 (tools/winter_extractors.py UNCHANGED from M727, tools/winter_extractors_b.py, tools/winter_score.py);
`supersedes`: the sha256 of the M727 registry (analyses/M726_extractor_registry.json, kept as history); `bootstrap`: the generator (numpy default_rng, seed 42, integers). P1 and P6 are not covered (M732, M731).
The registry's own sha256 is recorded in the CHANGELOG; `winter_score.extractors_frozen(pid)` accepts a prediction only when it is listed, every module sha256 equals the registry and the registry sha256 appears in the CHANGELOG.
After the freeze no extractor is edited; a change is a new version with a new registry. Usage: python tools/winter_extractors_b_freeze.py [--check]"""
import hashlib, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_extractors as WE
import winter_extractors_b as WB

REG = os.path.join(ROOT, "analyses", "M728_extractor_registry.json")


def sha(p):
    return hashlib.sha256(open(os.path.join(ROOT, p), "rb").read()).hexdigest()


def build():
    freeze, spec, score = sha("analyses/M717_winter_predictions.json"), sha("analyses/M728_spec.md"), sha("tools/winter_score.py")
    preds = {}
    for pid, fn, mod, ver, cols in (("P2", "extract_p2", "winter_extractors", WE.VERSION, WE.COLUMNS["P2"]), ("P3", "extract_p3", "winter_extractors", WE.VERSION, WE.COLUMNS["P3"]),
                                    ("P5", "extract_p5", "winter_extractors", WE.VERSION, WE.COLUMNS["P5"]), ("P7", "extract_p7", "winter_extractors", WE.VERSION, WE.COLUMNS["P7"]),
                                    ("P4", "extract_p4", "winter_extractors_b", WB.VERSION, WB.COLUMNS["P4"])):
        preds[pid] = {"function": "tools/%s.py::%s" % (mod, fn), "version": ver, "columns": cols, "freezeFileSha256": freeze, "specSha256": spec if pid == "P4" else sha("analyses/M727_spec.md"), "winterScoreV3Sha256": score}
    return {"milestone": "M728", "spec": "analyses/M728_spec.md", "note": "extractors of P2, P3, P4, P5, P7 frozen; P1 (M732), P6 and the realised-ambient P2 band (M731) not covered",
            "predictions": sorted(preds), "perPrediction": preds, "bootstrap": "numpy.random.default_rng(42).integers; day-clustered percentile; 4000 draws; days in ascending date order",
            "modules": {"tools/winter_extractors.py": sha("tools/winter_extractors.py"), "tools/winter_extractors_b.py": sha("tools/winter_extractors_b.py"), "tools/winter_score.py": score},
            "supersedes": {"registry": "analyses/M726_extractor_registry.json", "sha256": sha("analyses/M726_extractor_registry.json")}}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    reg = build()
    if "--check" in argv:
        have = json.load(open(REG, encoding="utf-8")) if os.path.exists(REG) else None
        ok = have == reg
        print(json.dumps({"check": "extractor registry v2", "matches": ok}))
        return 0 if ok else 1
    if os.path.exists(REG):
        print("STOP: the registry exists; a change is a new version with a new registry")
        return 1
    with open(REG, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(reg, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"written": "analyses/M728_extractor_registry.json", "sha256": sha("analyses/M728_extractor_registry.json"), "predictions": reg["predictions"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
