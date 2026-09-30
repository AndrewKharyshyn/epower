"""M308 known-answer tests for tools/plausibility_gate.py and its quarantine in tools/ingest_core.py."""
import os, sys, tempfile, shutil, json, subprocess
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, os.path.join(ROOT, "tools")); sys.argv = ["x"]
import plausibility_gate as pg

HDR = "time,[BMS] HV Battery Current (A),[BMS] Max Cell Voltage (V),[BMS] Min Cell Voltage (V)\n"

def mk(vmax, vmin):
    n = max(len(vmax), len(vmin))
    rows = "".join(f"2026-09-01 10:00:{i:02d},10.5,{vmax[i] if i < len(vmax) else ''},{vmin[i] if i < len(vmin) else ''}\n" for i in range(n))
    return (HDR + rows).encode()

fine = [3.601, 3.602, 3.604, 3.607, 3.611, 3.616, 3.622]
# (c) synthetic boundaries, R1
assert pg.check_bytes(mk([2.5] + fine, [2.5] + fine))["flags"] == [], "2.5 V is inside"
assert pg.check_bytes(mk([4.3] + fine, fine))["flags"] == [], "4.3 V is inside"
r = pg.check_bytes(mk([2.49] + fine, fine)); assert [f["rule"] for f in r["flags"]] == ["R1_cell_voltage_range"], r
r = pg.check_bytes(mk([4.31] + fine, fine)); assert [f["rule"] for f in r["flags"]] == ["R1_cell_voltage_range"], r
r = pg.check_bytes(mk([53.0] + fine, fine)); assert r["flags"][0]["nOutOfRange"] == 1 and r["flags"][0]["max"] == 53.0
# R2: step >= 0.05 with >= 5 distinct values flags; step 0.049 does not; fewer than 5 distinct values never flags R2
coarse = [3.5, 3.6, 3.7, 3.8, 3.9]
r = pg.check_bytes(mk(coarse, coarse)); assert [f["rule"] for f in r["flags"]] == ["R2_quantisation"], r
r = pg.check_bytes(mk([3.5, 3.549, 3.598, 3.647, 3.696], coarse[:1])); assert r["flags"] == [], r
r = pg.check_bytes(mk([3.5, 3.6, 3.7, 3.8], [3.5])); assert r["flags"] == [], "< 5 distinct values: R2 not applied"
# group-voltage columns are out of scope (Amendment 1): a 7.8 V G01 column must not flag
g = (HDR.strip() + ",G01 Cell Voltage  (V)\n" + "".join(f"2026-09-01 10:00:{i:02d},10.5,{fine[i]},{fine[i]},7.8\n" for i in range(7))).encode()
assert pg.check_bytes(g)["flags"] == [], "G01 group column must be ignored"
# file without cell-voltage columns: nothing to check, no flags
n = pg.check_bytes(b"time,[BMS] HV Battery Current (A)\n2026-09-01 10:00:00,1.0\n"); assert n["flags"] == [] and n["checked"] is False

# (a)/(b) real corpus files (raw/ is in the repo): known-bad set must flag, hash-verified samples must pass
RAW = os.path.join(ROOT, "raw")
bad = ["2026-06-09 13-20-41.csv", "2026-06-10 09-41-00.csv", "2026-06-11 06-11-20.csv", "2026-06-18 12-46-11.csv",
       "2026-06-27 08-52-19.csv", "2026-07-23 11-37-24.csv"]           # 0.1 V quantised + 53.0 V value (R1+R2)
r1_only = ["2026-05-15 22-22-40.csv", "2026-05-23 11-33-05.csv", "2026-06-25 12-28-50.csv"]   # 53.0 V value only
good = ["2026-09-22 07-45-42.csv", "2026-09-22 11-55-57.csv", "2026-09-21 07-36-37.csv", "2026-09-19 09-36-29.csv",
        "2026-09-05 10-48-41.csv"]                                    # hash-verified, incl. G01 group column era
for f in bad:
    rules = sorted(x["rule"] for x in pg.check_path(os.path.join(RAW, f))["flags"])
    assert rules == ["R1_cell_voltage_range", "R2_quantisation"], (f, rules)
for f in r1_only:
    rules = [x["rule"] for x in pg.check_path(os.path.join(RAW, f))["flags"]]
    assert rules == ["R1_cell_voltage_range"], (f, rules)
for f in good:
    assert pg.check_path(os.path.join(RAW, f))["flags"] == [], f

# ingest_core quarantines (fail closed): scratch copy with a known-bad file treated as NEW; nothing may be written
tmp = tempfile.mkdtemp()
try:
    for d in ("tools",):
        shutil.copytree(os.path.join(ROOT, d), os.path.join(tmp, d), ignore=shutil.ignore_patterns("__pycache__"))
    for f in os.listdir(ROOT):
        p = os.path.join(ROOT, f)
        if os.path.isfile(p) and f.endswith((".py", ".json", ".csv", ".sh")) and f != "STATE.md":
            shutil.copy(p, tmp)
    # drop the bad drive's master row and manifest record so the raw file is NEW
    import re
    key = "20260609132041"
    lines = open(os.path.join(tmp, "drive_master.csv"), newline="").read().split("\n")
    keep = [l for i, l in enumerate(lines) if i == 0 or key not in re.sub(r"\D", "", l.split(",")[0])]
    open(os.path.join(tmp, "drive_master.csv"), "w", newline="").write("\n".join(keep))
    man = json.load(open(os.path.join(tmp, "raw_manifest.json")))
    man["files"] = [r for r in man["files"] if key not in re.sub(r"\D", "", (r["raw_name"] or ""))]
    json.dump(man, open(os.path.join(tmp, "raw_manifest.json"), "w"))
    os.symlink(RAW, os.path.join(tmp, "raw"))
    before = {f: open(os.path.join(tmp, f), "rb").read() for f in ("drive_master.csv", "raw_manifest.json", "summary_arrays.json", "summary_config.json")}
    p = subprocess.run([sys.executable, "tools/ingest_core.py"], cwd=tmp, capture_output=True, text=True,
                       env={**os.environ, "XT_RAW_DIR": os.path.join(tmp, "raw")})
    if p.returncode != 1:
        sys.stderr.write("RC=%s\nSTDOUT:\n%s\nSTDERR:\n%s\n" % (p.returncode, p.stdout[-1500:], p.stderr[-1500:]))
    assert p.returncode == 1
    rep = json.load(open(os.path.join(tmp, "tools", "ingest_core_report.json")))
    assert rep["status"] == "quarantined" and rep["quarantined"][0]["file"].startswith("2026-06-09"), rep
    for f, b in before.items():
        assert open(os.path.join(tmp, f), "rb").read() == b, f"{f} changed although the file was quarantined"
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("OK plausibility gate: boundaries, group-column scope, 9 known-bad flag, 5 hash-verified pass, ingest_core quarantines and writes nothing")
