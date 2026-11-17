#!/usr/bin/env python3
"""M508: list raw drive CSVs in raw/ that are not in raw_manifest.json (identity = the 14 timestamp digits of the file name). Read-only.
Used by the SessionStart hook (.claude/hooks/new-drives-check.sh): with new files it prints the standing instruction to start the `ingest-drive` skill; with none it prints nothing.
Usage: python tools/new_raw_files.py [--json] [--raw-dir DIR] [--manifest FILE]   (exit code 0 always; the hook must never block a session)"""
import json, os, re, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))


def digits(name):
    return re.sub(r"\D", "", os.path.basename(str(name)))


def new_files(raw_dir, manifest_path):
    man = json.load(open(manifest_path, encoding="utf-8"))
    known = set()
    for r in man.get("files", []):
        for k in ("canonical", "raw_name", "record_id"):
            if r.get(k):
                known.add(digits(r[k]))
    import raw_resolver as RR   # M707 (B3): one file per timestamp key; byte-identical aliases are one drive, differing bytes raise RawConflict (reported by main, never silently picked)
    res = RR.resolve(raw_dir, manifest_path)
    return [os.path.basename(p) for k, p in sorted(res.index.items(), key=lambda kv: os.path.basename(kv[1])) if k not in known]


def message(files):
    shown = ", ".join(files[:5]) + (" ..." if len(files) > 5 else "")
    return ("NEW RAW DRIVES DETECTED: %d file(s) in raw/ are not in raw_manifest.json (%s).\n"
            "Standing instruction (owner, 2026-10-25): before any other work, invoke the `ingest-drive` skill and follow it, including the ambient temperature protocol (it needs the driver-recorded ambients per drive "
            "before `run_ingest.py`; ask Andrii for them if missing). If these files are not meant to be ingested (e-4ORCE or comparison-only captures, copies, tests), say so and ask before doing anything." % (len(files), shown))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    raw_dir = argv[argv.index("--raw-dir") + 1] if "--raw-dir" in argv else os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw")
    manifest = argv[argv.index("--manifest") + 1] if "--manifest" in argv else os.path.join(ROOT, "raw_manifest.json")
    try:
        files = new_files(raw_dir, manifest)
    except Exception as e:          # never block a session
        if type(e).__name__ == "RawConflict":                   # M707 (B3): a conflict must be visible, not a silent "nothing new"
            print("RAW FILE CONFLICT in raw/: " + str(e) + ". Do not ingest until the owner decides which file is the drive (identical bytes are accepted as aliases automatically).")
            return 0
        print("new_raw_files: check skipped (%r)" % (e,), file=sys.stderr)
        return 0
    if "--json" in argv:
        print(json.dumps({"nNew": len(files), "files": files}))
    elif files:
        print(message(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
