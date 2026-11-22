#!/usr/bin/env python3
"""M731 (analyses/M731_spec.md Rev 2.2, section 4.4): the fidelity checks of the vendored engine and of the band runner, on the frozen inputs only.
C-P2a: the vendored engine CLI (fresh interpreter, its own tools directory) reproduces ALL E_real keys of S2, S3a and S3b in the FROZEN copy of the scenario results (analyses/M717_frozen_sources/analyses__M713__scenario_results_production.json) exactly,
       so the union band [0.0316, 0.1476] is recovered. (The live analyses/M713 file is a later refresh and is not the reference.)
C-P2d: the runner with all twelve months in the window and the frozen S3b shift table reproduces the engine's S3b ahShare_T_lt10 interval exactly; and a window of January alone gives a different interval (the null-day mask acts).
C-P2b: the shift derivation recovers planted shifts (known-answer, tests/synthetic/test_winter_p2_band.py, not repeated here).
Writes analyses/M731_engine_check.json. Usage: python tools/winter_p2_band_check.py [--run-label LABEL]"""
import json, os, subprocess, sys, tempfile
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
VROOT = os.path.join(ROOT, "analyses", "M731_frozen_engine", "root")
OUT = os.path.join(ROOT, "analyses", "M731_engine_check.json")
FROZEN = os.path.join(ROOT, "analyses", "M717_frozen_sources", "analyses__M713__scenario_results_production.json")
NAMES = ["S2_balanced_owner_expected", "S3a_mild_winter", "S3b_cold_winter"]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    label = argv[argv.index("--run-label") + 1] if "--run-label" in argv else "run 1"
    wd = tempfile.mkdtemp(prefix="m731_chk_")
    fz = json.load(open(FROZEN, encoding="utf-8"))
    rec = {"label": label}
    outp = os.path.join(wd, "eng.json")
    r = subprocess.run([sys.executable, "-I", os.path.join(VROOT, "tools", "scenario_engine.py"), "--dir", os.path.join(VROOT, "analyses", "M713"), "--draws", "4000", "--scenarios", "S2_,S3a,S3b", "--out", outp],
                       capture_output=True, text=True, cwd=VROOT)
    if r.returncode != 0:
        rec["C-P2a"] = {"pass": False, "error": r.stderr[-500:]}
    else:
        eng = json.load(open(outp, encoding="utf-8"))
        per = {}
        for n in NAMES:
            a, b = eng[n]["E_real"], fz[n]["E_real"]
            per[n] = {"keys": len(b), "differing": [k for k in b if a.get(k) != b[k]]}
        rec["C-P2a"] = {"perScenario": per, "ahShareLt10": {n: eng[n]["E_real"]["ahShare_T_lt10"] for n in NAMES}, "union": [min(eng[n]["E_real"]["ahShare_T_lt10"][1] for n in NAMES), max(eng[n]["E_real"]["ahShare_T_lt10"][2] for n in NAMES)],
                        "pass": all(len(v["differing"]) == 0 for v in per.values())}
    runner = os.path.join(ROOT, "tools", "winter_p2_band_run.py")

    def run(window, tag):
        a = {"scenario": "S3b_cold_winter", "shifts": [[-6, -6, -3, 0, 0, 0, 0, 0, 0, 0, -3, -6]], "windowMonths": window, "draws": 4000, "out": os.path.join(wd, tag + ".npy")}
        json.dump(a, open(os.path.join(wd, tag + ".json"), "w"))
        p = subprocess.run([sys.executable, "-I", runner, os.path.join(wd, tag + ".json")], capture_output=True, text=True, cwd=ROOT)
        line = [l for l in p.stdout.splitlines() if l.startswith("RESULT ")]
        return json.loads(line[0][7:]) if line else {"error": p.stderr[-400:]}
    full, jan = run(None, "full"), run([1], "jan")
    rec["C-P2d"] = {"allMonths": full.get("ci"), "frozenS3b": fz["S3b_cold_winter"]["E_real"]["ahShare_T_lt10"], "januaryOnly": jan.get("ci")}
    rec["C-P2d"]["pass"] = bool(full.get("ci") == fz["S3b_cold_winter"]["E_real"]["ahShare_T_lt10"] and jan.get("ci") is not None and jan["ci"] != full["ci"])
    rec["allCriteriaPassed"] = bool(rec["C-P2a"].get("pass") and rec["C-P2d"]["pass"])
    log = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {"spec": "analyses/M731_spec.md", "runs": []}
    log["runs"].append(rec)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(log, ensure_ascii=False, indent=1, default=float) + "\n")
    print(json.dumps(rec, indent=1, default=float)[:2500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
