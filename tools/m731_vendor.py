#!/usr/bin/env python3
"""M731 (analyses/M731_spec.md Rev 2, section 4.1): vendors the scenario replay engine and its frozen inputs byte-exact FROM THE GIT BLOBS of the M717 freeze commit (not from the working tree) into
analyses/M731_frozen_engine/root/, a mini repository root: the engine modules' ROOT (parent of their tools/ directory) resolves to this folder, so they read the frozen inputs and never a live file.
Contents: tools/{scenario_engine,exposure_state,park_model,scenario_frame,restart_census,raw_resolver}.py; analyses/M713/{exposure_drives.csv,exposure_slices.npz,state_params.json,odometer_check.json};
analyses/M709/park_model.json; summary_config.json and summary_arrays.json reduced to the keys the engine reads (ambientByDrive, vehicle; seasonalLife.assumptions.monthlyTempC), taken from the same commit.
index.json records for every file the source git blob id (or the reduction rule) and the sha256 of the vendored bytes. Written once; `--check` re-verifies. Usage: python tools/m731_vendor.py [--check]"""
import hashlib, json, os, subprocess, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
COMMIT = "f7b5014"
DEST = os.path.join(ROOT, "analyses", "M731_frozen_engine")
FILES = ["tools/scenario_engine.py", "tools/exposure_state.py", "tools/park_model.py", "tools/scenario_frame.py", "tools/restart_census.py", "tools/raw_resolver.py",
         "analyses/M713/exposure_drives.csv", "analyses/M713/exposure_slices.npz", "analyses/M713/state_params.json", "analyses/M713/odometer_check.json", "analyses/M709/park_model.json"]


def git(*a):
    return subprocess.run(["git", "-C", ROOT] + list(a), capture_output=True, check=True).stdout


def build():
    out, idx = {}, {}
    for f in FILES:
        b = git("show", "%s:%s" % (COMMIT, f))
        out[f] = b
        idx[f] = {"gitBlob": git("rev-parse", "%s:%s" % (COMMIT, f)).decode().strip(), "sha256": hashlib.sha256(b).hexdigest()}
    cfg = json.loads(git("show", "%s:summary_config.json" % COMMIT).decode("utf-8"))
    red = {"ambientByDrive": cfg["ambientByDrive"], "vehicle": cfg["vehicle"]}
    b = (json.dumps(red, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
    out["summary_config.json"] = b
    idx["summary_config.json"] = {"reduction": "keys ambientByDrive and vehicle of summary_config.json at " + COMMIT, "sourceBlob": git("rev-parse", "%s:summary_config.json" % COMMIT).decode().strip(), "sha256": hashlib.sha256(b).hexdigest()}
    arr = json.loads(git("show", "%s:summary_arrays.json" % COMMIT).decode("utf-8"))
    red = {"seasonalLife": {"assumptions": {"monthlyTempC": arr["seasonalLife"]["assumptions"]["monthlyTempC"]}}}
    b = (json.dumps(red, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
    out["summary_arrays.json"] = b
    idx["summary_arrays.json"] = {"reduction": "seasonalLife.assumptions.monthlyTempC of summary_arrays.json at " + COMMIT, "sourceBlob": git("rev-parse", "%s:summary_arrays.json" % COMMIT).decode().strip(), "sha256": hashlib.sha256(b).hexdigest()}
    return out, {"milestone": "M731", "commit": COMMIT, "rootFolder": "analyses/M731_frozen_engine/root", "files": idx}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    root = os.path.join(DEST, "root")
    ipath = os.path.join(DEST, "index.json")
    if "--check" in argv:                                   # no git needed (CI clones are shallow): the vendored bytes against the sha256 recorded in index.json
        idx = json.load(open(ipath, encoding="utf-8")) if os.path.exists(ipath) else {"files": {}}
        ok = bool(idx["files"]) and all(os.path.exists(os.path.join(root, f)) and hashlib.sha256(open(os.path.join(root, f), "rb").read()).hexdigest() == r["sha256"] for f, r in idx["files"].items())
        print(json.dumps({"check": "M731 vendored engine", "matches": bool(ok)}))
        return 0 if ok else 1
    out, index = build()
    if os.path.exists(ipath):
        print("STOP: already vendored; a change is a new version")
        return 1
    for f, b in out.items():
        p = os.path.join(root, f)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as fh:
            fh.write(b)
    with open(ipath, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(index, indent=1) + "\n")
    print(json.dumps({"written": len(out), "dir": "analyses/M731_frozen_engine"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
