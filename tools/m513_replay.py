#!/usr/bin/env python3
"""M513 (analyses/M513_spec.md Rev 2): sandbox replay of the cheap producers before their stamps are re-derived.
For each declared block that is cheap to re-run, copy the repository's top-level files + tools/ + tests/ to a temporary directory (raw files are NOT copied; XT_RAW_DIR points at the real raw/ read-only),
run the producer command there, and compare the block (canonical JSON) with the repository's block. Identical => the stamp may be re-derived for that block (the stamp's claim 'computed on this
master/config/inputs' is then reproduced); different => STOP for that block (nothing forced). The repository is never written. GTR and seasonalCharts are NOT replayed (a GTR re-run would trigger the
M466 flip/acknowledgement route): they use the git attestation (tools/m513_attest.py).
Output: analyses/M513_replay.json.   Usage: python tools/m513_replay.py [--only block[,block]]"""
import hashlib, json, os, shutil, subprocess, sys, tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "analyses", "M513_replay.json")
PY = sys.executable
CMDS = {
    "cohortMeta": [[PY, "tools/refresh_cohort_meta.py"]],
    "ambientTable": [[PY, "tools/build_ambient_table.py"]],
    "spreadFitProvenance": [[PY, "tools/record_spread_fit.py"]],
    "crossVehicle": [[PY, "crosscheck_vehicles.py"], [PY, "crosscheck_events.py"]],
    "assumptionsRegistry": [[PY, "patch_m284_data.py"]],
    "provenanceSensitivity": [[PY, "tools/f03_provenance_build.py"], [PY, "f03_provenance_flag.py"]],
}


def canon(o):
    return hashlib.md5(json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


EXTRA = {"provenanceSensitivity": ["analyses/F03_originals", "analyses/F03"], "spreadFitProvenance": ["analyses/M317_calibration.json", "analyses/M317_calibration_design2.json"]}
IGNORE = {"crossVehicle": [("_meta", "generated"), ("eventDetectors", "_meta", "generated"), ("pureElectric", "_meta", "generated"), ("turboPattern", "_meta", "generated"),
                           ("eventDetectors", "socHysteresis", "primary", "startRatioClustered")]}      # wall-clock stamps inside the block; startRatioClustered is added later by the M497 stage, not by the cross-vehicle producer


def paths(a, b, p=""):
    """First differing leaf paths of two JSON values (at most 12)."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            out += [f"{p}/{k} (missing)"] if (k not in a or k not in b) else paths(a[k], b[k], f"{p}/{k}")
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            out += paths(x, y, f"{p}[{i}]")
    elif a != b:
        out.append(p)
    return out[:12]


def sandbox(extra=()):
    d = tempfile.mkdtemp(prefix="xt_m513_")
    for f in os.listdir(ROOT):
        p = os.path.join(ROOT, f)
        if os.path.isfile(p):
            shutil.copy2(p, d)
    for sub in ("tools", "tests"):
        shutil.copytree(os.path.join(ROOT, sub), os.path.join(d, sub), ignore=shutil.ignore_patterns("__pycache__"))
    os.makedirs(os.path.join(d, "analyses"), exist_ok=True)
    for e in extra:
        (shutil.copytree if os.path.isdir(os.path.join(ROOT, e)) else shutil.copy2)(os.path.join(ROOT, e), os.path.join(d, e))
    return d


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else set(CMDS)
    real = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
    md5_master = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    res = {}
    for k, cmds in CMDS.items():
        if k not in only:
            continue
        d = sandbox(EXTRA.get(k, ()))
        env = dict(os.environ, XT_RAW_DIR=os.path.join(ROOT, "raw"), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        try:
            rcs, tail = [], ""
            for c in cmds:
                r = subprocess.run(c, cwd=d, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1500)
                rcs.append(r.returncode); tail = (r.stdout + r.stderr)[-400:]
                if r.returncode != 0:
                    break
            if any(rcs):
                res[k] = {"identical": False, "reason": "producer failed in the sandbox", "returncodes": rcs, "tail": tail}
                continue
            A = json.load(open(os.path.join(d, "summary_arrays.json"), encoding="utf-8"))
            a_, b_ = json.loads(json.dumps(A.get(k))), json.loads(json.dumps(real.get(k)))
            for path in IGNORE.get(k, []):
                for o_ in (a_, b_):
                    t_ = o_
                    for q in path[:-1]:
                        t_ = t_.get(q, {}) if isinstance(t_, dict) else {}
                    if isinstance(t_, dict):
                        t_.pop(path[-1], None)
            same = canon(a_) == canon(b_)
            res[k] = {"identical": bool(same), "diffPaths": [] if same else paths(b_, a_), "blockMd5Repo": canon(b_), "blockMd5Replay": canon(a_), "ignoredLeaves": [".".join(x) for x in IGNORE.get(k, [])], "commands": [" ".join(os.path.basename(x) if i == 0 else x for i, x in enumerate(c)) for c in cmds]}
        finally:
            shutil.rmtree(d, ignore_errors=True)
    out = {"masterMd5": md5_master, "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(), "blocks": res,
           "note": "replay in a temporary copy; the repository is not written; GTR and seasonalCharts are attested from git instead"}
    json.dump(out, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False)
    print(json.dumps({k: (v["identical"], v.get("reason")) for k, v in res.items()}))
    return 0 if all(v["identical"] for v in res.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
