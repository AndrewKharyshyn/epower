"""M427 (external audit F15) known-answer test: drive-file discovery does not depend on the calendar year. The shared pattern admits 2026 and 2027 drive exports, excludes the e4ORCE exports (named by role),
and every default that used to be 2026*.csv uses it."""
import fnmatch, inspect, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import corpus_manifest as cm
import compute_drive_summary_v6 as v6
g = cm.RAW_GLOB
assert "2026" not in g
for n in ("2026-12-31_23-59-59.csv", "20261231_235959.csv", "2027-01-01_00-00-05.csv", "20270101_000005.csv", "2031-03-04_10-00-00.csv"):
    assert fnmatch.fnmatch(n, g), n
for n in ("e4ORCE_20270102_000000.csv", "raw_manifest.json", "drive_master.csv", "readme.csv", "ambient_samples.json"):
    assert not fnmatch.fnmatch(n, g), n
assert inspect.signature(v6.build_master_from_raw).parameters["pattern"].default == g
assert inspect.signature(v6.run_pipeline).parameters["pattern"].default == g
src = open(os.path.join(ROOT, "tools", "ingest_core.py"), encoding="utf-8").read()
assert "cm.RAW_GLOB" in src and '"2026*.csv"' not in src
assert "2026*.csv" not in open(os.path.join(ROOT, "master_refit_audit.py"), encoding="utf-8").read().replace("# ", "")
print("OK test_year_rollover")
