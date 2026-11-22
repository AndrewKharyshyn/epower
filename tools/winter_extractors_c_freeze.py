#!/usr/bin/env python3
"""M731 (analyses/M731_spec.md Rev 2.2, section 5): writes the extractor registry analyses/M731_extractor_registry.json (version 3) that freezes the extractors of P2 (with the realised-ambient band), P3, P4, P5, P6 and P7.
Per prediction id: function name, version, columns, the freeze file sha256, the spec sha256 and the winter_score.py v4 sha256. `modules`: path -> sha256 of tools/winter_extractors.py (UNCHANGED from M727), tools/winter_extractors_b.py (UNCHANGED from M728),
tools/winter_p6.py, tools/winter_p2_band.py, tools/winter_p2_band_run.py, tools/winter_score.py, the vendored engine (index and every vendored file) and the two frozen-basis check files (the P6 tolerance is read from the first). `supersedes`: the sha256 of the M728 registry (kept as history).
P1 (M732) is not covered. The registry's own sha256 is recorded in the CHANGELOG; `winter_score.extractors_frozen(pid)` accepts a prediction only when it is listed, every module sha256 equals the registry and the registry sha256 appears in the CHANGELOG.
After the freeze no extractor is edited; a change is a new version with a new registry. Usage: python tools/winter_extractors_c_freeze.py [--check]"""
import hashlib, json, os, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_extractors as WE
import winter_extractors_b as WB
import winter_p6 as W6
import winter_p2_band as W2

REG = os.path.join(ROOT, "analyses", "M731_extractor_registry.json")
VDIR = "analyses/M731_frozen_engine"


def sha(p):
    return hashlib.sha256(open(os.path.join(ROOT, p), "rb").read()).hexdigest()


def vendored_files():
    out = []
    for d, _, fs in os.walk(os.path.join(ROOT, VDIR)):
        for f in fs:
            out.append(os.path.relpath(os.path.join(d, f), ROOT).replace("\\", "/"))
    return sorted(x for x in out if "__pycache__" not in x and not x.endswith(".pyc"))


def build():
    freeze, spec, score = sha("analyses/M717_winter_predictions.json"), sha("analyses/M731_spec.md"), sha("tools/winter_score.py")
    rows = (("P2", "tools/winter_extractors.py::extract_p2 + tools/winter_p2_band.py::realised_band", WE.VERSION, WE.COLUMNS["P2"] + W2.COLUMNS["P2band"], "analyses/M727_spec.md"),
            ("P3", "tools/winter_extractors.py::extract_p3", WE.VERSION, WE.COLUMNS["P3"], "analyses/M727_spec.md"),
            ("P4", "tools/winter_extractors_b.py::extract_p4", WB.VERSION, WB.COLUMNS["P4"], "analyses/M728_spec.md"),
            ("P5", "tools/winter_extractors.py::extract_p5", WE.VERSION, WE.COLUMNS["P5"], "analyses/M727_spec.md"),
            ("P6", "tools/winter_p6.py::extract_p6 (+ sidecar p6_row)", W6.VERSION, W6.COLUMNS["P6"], "analyses/M731_spec.md"),
            ("P7", "tools/winter_extractors.py::extract_p7", WE.VERSION, WE.COLUMNS["P7"], "analyses/M727_spec.md"))
    preds = {}
    for pid, fn, ver, cols, sp in rows:
        preds[pid] = {"function": fn, "version": ver, "columns": cols, "freezeFileSha256": freeze, "specSha256": spec if pid in ("P6", "P2") else sha(sp), "winterScoreV4Sha256": score}
    mods = {m: sha(m) for m in ("tools/winter_extractors.py", "tools/winter_extractors_b.py", "tools/winter_p6.py", "tools/winter_p2_band.py", "tools/winter_p2_band_run.py", "tools/winter_score.py",
                                "analyses/M731_consistency_check.json", "analyses/M731_engine_check.json")}
    mods.update({f: sha(f) for f in vendored_files()})
    return {"milestone": "M731", "spec": "analyses/M731_spec.md", "note": "extractors of P2 (with the realised-ambient band), P3, P4, P5, P6, P7 frozen; P1 (M732) not covered", "predictions": sorted(preds), "perPrediction": preds,
            "bootstrap": "numpy.random.default_rng(42).integers; day-clustered percentile; 4000 draws; days in ascending date order", "modules": mods,
            "supersedes": {"registry": "analyses/M728_extractor_registry.json", "sha256": sha("analyses/M728_extractor_registry.json")}}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    reg = build()
    if "--check" in argv:
        have = json.load(open(REG, encoding="utf-8")) if os.path.exists(REG) else None
        ok = have == reg
        print(json.dumps({"check": "extractor registry v3", "matches": ok}))
        return 0 if ok else 1
    if os.path.exists(REG):
        print("STOP: the registry exists; a change is a new version with a new registry")
        return 1
    with open(REG, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(reg, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"written": "analyses/M731_extractor_registry.json", "sha256": sha("analyses/M731_extractor_registry.json"), "predictions": reg["predictions"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
