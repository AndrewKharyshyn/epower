"""M621 (P-01) known-answer test: a changed master or payload makes release_identity --check fail; unchanged tree passes."""
import importlib.util, json, os, shutil, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
tmp = tempfile.mkdtemp(prefix="xt_rid_")
try:
    os.makedirs(os.path.join(tmp, "tools"))
    shutil.copy2(os.path.join(REPO, "tools", "release_identity.py"), os.path.join(tmp, "tools"))
    open(os.path.join(tmp, "drive_master.csv"), "w", newline="").write("a,b\n1,2\n")
    json.dump({"meta": {"totalDrives": 1}, "k": 1}, open(os.path.join(tmp, "summary_arrays.json"), "w"))
    json.dump({"snapshotId": "s1"}, open(os.path.join(tmp, "raw_manifest.json"), "w"))
    open(os.path.join(tmp, "CHANGELOG.md"), "w").write("## M1 (2026-01-01)\n")
    def run(*a): return subprocess.run([sys.executable, os.path.join(tmp, "tools", "release_identity.py"), *a], capture_output=True, text=True).returncode
    assert run() == 0 and run("--check") == 0
    open(os.path.join(tmp, "drive_master.csv"), "a", newline="").write("3,4\n"); assert run("--check") == 1, "master change not detected"
    run(); assert run("--check") == 0
    json.dump({"snapshotId": "s2"}, open(os.path.join(tmp, "raw_manifest.json"), "w")); assert run("--check") == 1, "raw snapshot change not detected"
    print("PASS test_m621_release_identity")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
