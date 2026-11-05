#!/usr/bin/env python3
"""M578: pin the ordered drive-file list of the M544 evidence master. Finds in git history the drive_master.csv whose MD5 equals analyses/M544_evidence.json masterMd5, writes
analyses/M544_evidence_files.json {masterMd5, commit, nDrives, files, filesSha256}. Never typed by hand; tools/engine_on_blocks_stage.py checks the live master against it (fail closed).
Usage: python tools/m544_evidence_pin.py"""
import csv, hashlib, io, json, os, subprocess
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def files_sha256(files):
    return hashlib.sha256("\n".join(files).encode("utf-8")).hexdigest()


def main():
    ev = json.load(open(os.path.join(ROOT, "analyses", "M544_evidence.json"), encoding="utf-8"))
    log = subprocess.run(["git", "log", "--format=%H", "-n", "200", "--", "drive_master.csv"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    for c in log:
        blob = subprocess.run(["git", "show", c + ":drive_master.csv"], cwd=ROOT, capture_output=True, check=True).stdout
        if hashlib.md5(blob).hexdigest() == ev["masterMd5"]:
            files = [r["file"] for r in csv.DictReader(io.StringIO(blob.decode("utf-8")))]
            assert len(files) == ev["nDrivesMaster"], (len(files), ev["nDrivesMaster"])
            out = {"masterMd5": ev["masterMd5"], "commit": c, "nDrives": len(files), "filesSha256": files_sha256(files), "files": files}
            with open(os.path.join(ROOT, "analyses", "M544_evidence_files.json"), "w", encoding="utf-8", newline="\n") as f:
                json.dump(out, f, indent=1)
            print(json.dumps({k: out[k] for k in ("masterMd5", "commit", "nDrives", "filesSha256")}))
            return
    raise SystemExit("evidence master not found in git history")


if __name__ == "__main__":
    main()
