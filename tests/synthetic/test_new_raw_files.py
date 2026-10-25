"""M508 tests of tools/new_raw_files.py: a raw file that is not in the manifest is reported, known files (by the 14 timestamp digits, both name forms) are not, errors never block."""
import json, os, subprocess, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import new_raw_files as N

with tempfile.TemporaryDirectory() as td:
    raw = os.path.join(td, "raw"); os.makedirs(raw)
    man = {"files": [{"canonical": "20260511_185709.csv", "raw_name": "2026-05-11_18-57-09.csv", "record_id": "20260511_185709.csv", "role": "canonical"},
                     {"canonical": "20260512_111617.csv", "raw_name": "2026-05-12 11-16-17.csv", "record_id": "20260512_111617.csv", "role": "canonical"}]}
    mp = os.path.join(td, "m.json"); json.dump(man, open(mp, "w", encoding="utf-8"))
    for f in ("2026-05-11_18-57-09.csv", "2026-05-12 11-16-17.csv", "notes.txt"):
        open(os.path.join(raw, f), "w", encoding="utf-8").write("x")
    assert N.new_files(raw, mp) == []                                     # both name forms are known; non-CSV ignored
    open(os.path.join(raw, "2026-10-26_07-00-00.csv"), "w", encoding="utf-8").write("x")
    open(os.path.join(raw, "2026-10-26 08-30-00.csv"), "w", encoding="utf-8").write("x")
    assert N.new_files(raw, mp) == ["2026-10-26 08-30-00.csv", "2026-10-26_07-00-00.csv"]
    msg = N.message(N.new_files(raw, mp))
    assert "ingest-drive" in msg and "2 file(s)" in msg and "ambient" in msg
    # command line: the message is printed with new files, nothing without, exit code 0 on a bad manifest
    r = subprocess.run([sys.executable, "tools/new_raw_files.py", "--raw-dir", raw, "--manifest", mp], capture_output=True, text=True)
    assert r.returncode == 0 and "NEW RAW DRIVES DETECTED" in r.stdout
    os.remove(os.path.join(raw, "2026-10-26_07-00-00.csv")); os.remove(os.path.join(raw, "2026-10-26 08-30-00.csv"))
    r = subprocess.run([sys.executable, "tools/new_raw_files.py", "--raw-dir", raw, "--manifest", mp], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == ""
    r = subprocess.run([sys.executable, "tools/new_raw_files.py", "--raw-dir", raw, "--manifest", os.path.join(td, "missing.json")], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == ""
# smoke on the real repository (the result depends on whether new drives were added and not yet ingested, so it is not asserted)
real = N.new_files(os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"), os.path.join(ROOT, "raw_manifest.json"))
assert isinstance(real, list)
print("test_new_raw_files: OK")
