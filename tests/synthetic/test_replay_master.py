"""M417 (audit F11) tests for tools/replay_master.py: the sample tier rebuilds a pinned set of drives from raw and must reproduce every column analyze_bytes produces; the sample files are the sha256-verified
originals; the comparison can fail (known-answer negative controls); the full-tier check against the registered exceptions flags anything unregistered, larger or on another file; the committed full report
passes its own check."""
import copy, json, os, subprocess, sys
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import replay_master as R

# 1. comparison semantics (negative controls)
assert R.differs(1.0, 1.0 + 1e-6) and not R.differs(1.0, 1.0 + 1e-12)
assert R.differs("a", "b") and not R.differs("a", "a")
assert R.differs(None, 1.0) and R.differs(1.0, float("nan")) and not R.differs(float("nan"), None)
assert R.differs(True, False) and not R.differs(True, True)

# 2. pinned sample: 24 drives, every (drive_type, month) group represented, raw files equal the manifest sha256
smp = json.load(open(R.SAMPLE, encoding="utf-8"))["files"]
assert len(smp) == 24 and len(set(smp)) == 24
man = {r["canonical"]: r for r in json.load(open("raw_manifest.json", encoding="utf-8"))["files"]} if isinstance(json.load(open("raw_manifest.json", encoding="utf-8")).get("files"), list) else {}
import ingest_core as IC
import pandas as pd
dm = pd.read_csv("drive_master.csv", low_memory=False).set_index("file", drop=False)
assert set(smp) <= set(dm.index)
assert set(dm.loc[smp, "drive_type"]) == set(dm["drive_type"]), "every drive type must be in the sample"
raw_dir = R.raw_dir_default()
for k in smp:
    p = R.resolve(raw_dir, k)
    can = IC.master_key(os.path.basename(k))
    rec = man.get(k) or man.get(can) or next((v for v in man.values() if IC.digits(v["raw_name"]) == IC.digits(k)), None)
    assert rec is not None, "no manifest record for " + k
    assert R.sha256(p) == rec["sha256"], "sample raw file differs from raw_manifest.json: " + k

# 3. the sample tier itself: nothing differs
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "replay_master.py"), "--sample", "--no-write", "--raw-dir", raw_dir], capture_output=True, text=True, encoding="utf-8")
assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
rep = json.loads(r.stdout[r.stdout.index("{"):r.stdout.rindex("}") + 1])
assert rep["ok"] and rep["nDrives"] == 24 and rep["unexpected"] == []

# 4. the check against the registered full-tier exceptions
good = json.load(open(os.path.join(R.D, "replay_report_full.json"), encoding="utf-8"))
assert R.check_expected(good) == [], R.check_expected(good)
exp = R.load_expected()["full"]
def mutate(f):
    x = copy.deepcopy(good); f(x); return R.check_expected(x)
assert mutate(lambda x: x["columnsDiffering"].update({"gtc": {"nRowsDiffer": 1, "nNullPatternMismatch": 0, "maxAbsDiff": 0.1, "files": ["a"]}})), "unregistered column must fail"
assert mutate(lambda x: x["columnsDiffering"]["distance_km"].update(nRowsDiffer=2)), "more rows must fail"
assert mutate(lambda x: x["columnsDiffering"]["distance_km"].update(maxAbsDiff=9.0)), "larger difference must fail"
assert mutate(lambda x: x["columnsDiffering"]["distance_km"].update(files=["20260801_000000.csv"])), "other file must fail"
assert mutate(lambda x: x.update(publishedOnlyColumns=x["publishedOnlyColumns"][:-1])), "changed published-only columns must fail"
assert mutate(lambda x: x.update(rebuiltOnlyColumns=["new_col"])), "rebuilt-only column must fail"
assert mutate(lambda x: x.update(nRowsRebuilt=x["nRowsRebuilt"] - 1)), "row count mismatch must fail"
assert mutate(lambda x: x["columnsDiffering"]["I_offset_2p_A_applied"].update(maxAbsDiff=0.01)), "offset drift beyond its cap must fail"
assert set(good["columnsDiffering"]) <= set(exp["allowedDifferences"])

# 5. M427 (audit F02): the replay verifies the raw sha256 against the manifest record BEFORE analyzing; a changed byte in an unused channel, a missing, duplicate or non-canonical record must fail
import shutil, tempfile
k0 = smp[0]
p0 = R.resolve(raw_dir, k0)
files = json.load(open("raw_manifest.json", encoding="utf-8"))["files"]
assert R.verify_raw_identity(p0, k0, files) == R.sha256(p0), "the unmodified file must pass"
tmpd = tempfile.mkdtemp()
try:
    q = os.path.join(tmpd, os.path.basename(p0))
    raw_b = open(p0, "rb").read()
    open(q, "wb").write(raw_b + b"\n")                                  # appended newline: no channel the builder reads changes, the replay used to pass
    def must_fail(fn, why):
        try:
            fn()
        except RuntimeError:
            return
        raise AssertionError(why)
    must_fail(lambda: R.verify_raw_identity(q, k0, files), "a changed raw file must fail the hash check")
    must_fail(lambda: R.verify_raw_identity(p0, k0, [r for r in files if k0 not in (r.get("canonical"), r.get("record_id"), r.get("raw_name"))]), "a missing record must fail")
    must_fail(lambda: R.verify_raw_identity(p0, k0, files + [next(r for r in files if k0 in (r.get("canonical"), r.get("record_id"), r.get("raw_name")))]), "a duplicate record must fail")
    must_fail(lambda: R.verify_raw_identity(p0, k0, [dict(r, role="comparison_only") if k0 in (r.get("canonical"), r.get("record_id"), r.get("raw_name")) else r for r in files]), "a non-canonical role must fail")
finally:
    shutil.rmtree(tmpd, ignore_errors=True)
print("OK test_replay_master")
