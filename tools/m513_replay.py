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
    "powerFadeTemperatureSpecs": [[PY, "tools/m499_temp_spec.py", "--splice"]],
}


CHECKS = {"powerFadeEquivalence": [PY, "tools/powerfade_equivalence.py", "--check"], "engineRuntime": [PY, "tools/engine_runtime.py", "--check"],
          "resistanceJointSensitivity": [PY, "tools/resistance_joint_matrix.py", "--check"]}      # read-only recomputation of the block from the tracked sidecar(s), compared with the payload by the tool itself
SIDECAR_OF = {"powerFadeEquivalence": "powerfade_density.csv", "powerFadeTemperatureSpecs": "powerfade_density.csv", "engineRuntime": "engine_runtime_sidecar.csv", "resistanceJointSensitivity": "resistance_joint_sidecar.csv"}


def sidecar_matches_manifest(path):
    """Every sidecar row (raw sha256 recorded when the row was computed) equals the sha256 of the same canonical file in raw_manifest.json: the sidecar was built on the identity the live manifest records."""
    import re, pandas as pd
    man = json.load(open(os.path.join(ROOT, "raw_manifest.json"), encoding="utf-8"))
    sha = {re.sub(r"\D", "", r["canonical"]): r["sha256"] for r in man["files"] if r.get("role") == "canonical"}
    s = pd.read_csv(os.path.join(ROOT, path), dtype=str, keep_default_na=False)
    rows = s[s["raw_sha256"] != ""]
    ok = sum(1 for _, r in rows.iterrows() if sha.get(re.sub(r"\D", "", r["file"])) == r["raw_sha256"])
    return {"sidecar": path, "nRowsWithSha": int(len(rows)), "nMatchManifest": int(ok), "matches": bool(len(rows) > 0 and ok == len(rows)), "nRowsTotal": int(len(s))}


def canon(o):
    return hashlib.md5(json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


EXTRA = {"provenanceSensitivity": ["analyses/F03_originals", "analyses/F03"], "spreadFitProvenance": ["analyses/M317_calibration.json", "analyses/M317_calibration_design2.json"], "powerFadeTemperatureSpecs": ["analyses/M499_spec.md"]}
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
    only = set(argv[argv.index("--only") + 1].split(",")) if "--only" in argv else set(CMDS) | set(CHECKS)
    real = json.load(open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8"))
    md5_master = hashlib.md5(open(os.path.join(ROOT, "drive_master.csv"), "rb").read()).hexdigest()
    res = {}
    for k, c in CHECKS.items():
        if k not in only:
            continue
        r = subprocess.run(c, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1500)
        res[k] = {"identical": r.returncode == 0, "mode": "tool --check (read-only recomputation from the tracked sidecar, compared with the payload)", "returncode": r.returncode, "tail": (r.stdout + r.stderr)[-300:],
                  "rawIdentityEvidence": sidecar_matches_manifest(SIDECAR_OF[k])}
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
            # M518: the producer rebuilds its own stamp from a clone; the declared-dependency fields (declaredIdentity, stampLineage, dependencies) of the repository stamp must survive in the sandbox copy
            if k in (real.get("_artifactStamps") or {}) and (real["_artifactStamps"][k] or {}).get("declaredIdentity"):
                so, sn = real["_artifactStamps"][k], (A.get("_artifactStamps") or {}).get(k) or {}
                lineage_ok = all(sn.get(f) == so.get(f) for f in ("declaredIdentity", "stampLineage", "dependencies"))
                res_lineage = bool(lineage_ok)
                same = bool(same) and res_lineage
            res[k] = {"identical": bool(same), "rawIdentityEvidence": (sidecar_matches_manifest(SIDECAR_OF[k]) if k in SIDECAR_OF else None), "diffPaths": [] if same else paths(b_, a_), "blockMd5Repo": canon(b_), "blockMd5Replay": canon(a_), "ignoredLeaves": [".".join(x) for x in IGNORE.get(k, [])], "commands": [" ".join(os.path.basename(x) if i == 0 else x for i, x in enumerate(c)) for c in cmds]}
        finally:
            shutil.rmtree(d, ignore_errors=True)
    out = {"masterMd5": md5_master, "scriptSha256": hashlib.sha256(open(__file__, "rb").read()).hexdigest(), "blocks": res,
           "note": "replay in a temporary copy; the repository is not written; GTR and seasonalCharts are attested from git instead"}
    json.dump(out, open(OUT, "w", encoding="utf-8", newline="\n"), indent=1, ensure_ascii=False)
    print(json.dumps({k: (v["identical"], v.get("reason")) for k, v in res.items()}))
    return 0 if all(v["identical"] for v in res.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
