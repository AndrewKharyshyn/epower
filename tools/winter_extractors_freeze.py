#!/usr/bin/env python3
"""M727 (analyses/M727_spec.md section 4 and 8.4): writes the extractor registry analyses/M726_extractor_registry.json that freezes the extractors of P2, P3, P5 and P7.
Per prediction id: function name, version, column list, the freeze file sha256, the spec sha256 and the winter_score.py v2 sha256; `modules`: path -> sha256 (tools/winter_extractors.py, tools/winter_score.py); the registry's own sha256 is then recorded in the CHANGELOG by hand
(the changelog_draft entry); `winter_score.extractors_frozen(pid)` accepts a prediction only when it is listed, every module sha256 equals the registry and the registry sha256 appears in the CHANGELOG. After the freeze no extractor is edited; a change is a new version with a new registry.
Usage: python tools/winter_extractors_freeze.py [--check]"""
import hashlib, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_extractors as WE

REG = os.path.join(ROOT, "analyses", "M726_extractor_registry.json")


def sha(p):
    return hashlib.sha256(open(os.path.join(ROOT, p), "rb").read()).hexdigest()


def build():
    freeze, spec, score = sha("analyses/M717_winter_predictions.json"), sha("analyses/M727_spec.md"), sha("tools/winter_score.py")
    fns = {"P2": "extract_p2", "P3": "extract_p3", "P5": "extract_p5", "P7": "extract_p7"}
    preds = {pid: {"function": "tools/winter_extractors.py::" + fn, "version": WE.VERSION, "columns": WE.COLUMNS[pid], "freezeFileSha256": freeze, "specSha256": spec, "winterScoreV2Sha256": score} for pid, fn in fns.items()}
    return {"milestone": "M727", "spec": "analyses/M727_spec.md", "note": "extractors of P2, P3, P5, P7 frozen; P1, P4, P6 not covered (M728)", "predictions": sorted(fns), "perPrediction": preds,
            "modules": {"tools/winter_extractors.py": sha("tools/winter_extractors.py"), "tools/winter_score.py": score}}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    reg = build()
    if "--check" in argv:
        have = json.load(open(REG, encoding="utf-8")) if os.path.exists(REG) else None
        ok = have == reg
        print(json.dumps({"check": "extractor registry", "matches": ok}))
        return 0 if ok else 1
    if os.path.exists(REG):
        print("STOP: the registry exists; a change is a new version with a new registry")
        return 1
    with open(REG, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(reg, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"written": "analyses/M726_extractor_registry.json", "sha256": sha("analyses/M726_extractor_registry.json"), "predictions": reg["predictions"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
