"""M324 (GateA2) known-answer tests for tools/signal_representation.py: record contents, additive/atomic/idempotent sidecar, fail-closed conflicts."""
import hashlib, json, os, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..", "..")
sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT); sys.argv = ["x"]
import signal_representation as sr, plausibility_gate as pg, corpus_manifest as cm

# hand-checkable 6-row fixture: cadence 50 ms except one 150 ms gap; Max on a 0.1 V grid, I with 0.5 A steps, V with float noise
HDR = 'time,"[BMS] HV Battery Current (A)","[BMS] Max Cell Voltage (V)","[BMS] Min Cell Voltage (V)",label\n'
ROWS = ["2026-09-01 10:00:00.000,10.5,3.5,3.601,a\n", "2026-09-01 10:00:00.050,-2.5,3.6,3.602,b\n", "2026-09-01 10:00:00.100,0,3.7,3.604,c\n",
        "2026-09-01 10:00:00.150,1.0,3.8,3.607,d\n", "2026-09-01 10:00:00.300,2.0,3.9,3.611,e\n", "2026-09-01 10:00:00.350,2.0000000000000004,,3.616,f\n"]
B = (HDR + "".join(ROWS)).encode()
rec = sr.build_record(B, pg.check_bytes(B, "fx.csv"))
assert rec["sha256"] == hashlib.sha256(B).hexdigest() and rec["n_rows"] == 6 and rec["timestamp_column"] == "time"
assert rec["header_fingerprint"] == hashlib.sha256("\n".join(["time", "[BMS] HV Battery Current (A)", "[BMS] Max Cell Voltage (V)", "[BMS] Min Cell Voltage (V)", "label"]).encode()).hexdigest()
assert rec["cadence_ms"] == {"median": 50.0, "p95": 130.0}, rec["cadence_ms"]       # diffs 50,50,50,150,50 -> p95 = 130 (linear interpolation)
assert rec["first_timestamp"].endswith("00.000") and rec["last_timestamp"].endswith("00.350")
assert "label" not in rec["channels"] and "time" not in rec["channels"], "non-numeric / timestamp columns are not channels"
mx = rec["channels"]["[BMS] Max Cell Voltage (V)"]
assert mx["n_nonnull"] == 5 and mx["n_distinct"] == 5 and mx["grid_step"] == 0.1 and mx["max_decimals"] == 1 and mx["share_on_0p1_grid"] == 1.0, mx
mn = rec["channels"]["[BMS] Min Cell Voltage (V)"]
assert mn["grid_step"] == 0.001 and mn["max_decimals"] == 3 and mn["share_on_0p1_grid"] == 0.0, mn
cur = rec["channels"]["[BMS] HV Battery Current (A)"]
assert cur["n_distinct"] == 5 and cur["grid_step"] == 1.0 and cur["min"] == -2.5 and cur["max"] == 10.5, cur   # distinct -2.5,0,1,2,10.5 (diffs 2.5,1,1,8.5); 2.0000000000000004 == 2.0 after 9-dp rounding
assert cur["max_decimals"] == 16, "decimals come from the raw text, so float noise is visible as max_decimals"
assert rec["gate"]["flags"] == ["R2_quantisation"] and rec["gate"]["version"] == pg.GATE_VERSION
# bytes norm hash == corpus_manifest._norm_hash (BOM + CRLF variants hash identically)
tmp = tempfile.mkdtemp()
try:
    f = os.path.join(tmp, "a.csv"); open(f, "wb").write(b"\xef\xbb\xbf" + B.replace(b"\n", b"\r\n") + b"\r\n")
    assert sr.norm_hash_bytes(open(f, "rb").read()) == cm._norm_hash(f) == rec["norm_hash"]
    # fewer than 5 distinct values: no grid statistic
    few = sr.build_record(b"time,x\n2026-09-01 10:00:00,1\n2026-09-01 10:00:01,2\n")
    assert few["channels"]["x"]["grid_step"] is None and few["cadence_ms"]["median"] == 1000.0

    # sidecar: additive, idempotent (byte-identical), atomic, fail-closed on conflict, explicit supersede
    out = os.path.join(tmp, "signal_representation.json")
    assert sr.write_entries(out, {"d1.csv": rec}) == (["d1.csv"], [], [])
    b1 = open(out, "rb").read()
    assert sr.write_entries(out, {"d1.csv": rec}) == ([], ["d1.csv"], []) and open(out, "rb").read() == b1, "re-run must be a byte-identical no-op"
    doc = json.loads(b1); assert doc["schema_version"] == 1 and list(doc["files"]) == ["d1.csv"]
    assert b1.decode().index('"files"') < b1.decode().index('"schema_version"'), "sorted keys"
    rec2 = dict(rec, sha256="0" * 64)
    try:
        sr.write_entries(out, {"d1.csv": rec2}); raise SystemExit("FAIL: sha conflict not detected")
    except sr.Conflict as e:
        assert "--supersede" in str(e)
    assert open(out, "rb").read() == b1, "conflict must not modify the file"
    sr.write_entries(out, {"d2.csv": rec})                                          # additive: d1 untouched
    assert json.load(open(out))["files"]["d1.csv"] == doc["files"]["d1.csv"]
    assert sr.write_entries(out, {"d1.csv": rec2}, supersede={"d1.csv"}) == ([], [], ["d1.csv"])
    cur_doc = json.load(open(out))["files"]["d1.csv"]
    assert cur_doc["sha256"] == "0" * 64 and cur_doc["superseded"][0]["sha256"] == rec["sha256"], "old entry is kept, not overwritten"
    # interrupted write leaves the previous file intact (atomic replace)
    before = open(out, "rb").read(); real = os.replace
    def boom(*a, **k): raise OSError("simulated crash before replace")
    os.replace = boom
    try:
        sr.write_entries(out, {"d3.csv": rec}); raise SystemExit("FAIL: crash not propagated")
    except OSError:
        pass
    finally:
        os.replace = real
    assert open(out, "rb").read() == before
    # a different schema_version is refused
    json.dump({"schema_version": 99, "files": {}}, open(out, "w"))
    try:
        sr.write_entries(out, {"x.csv": rec}); raise SystemExit("FAIL: schema mismatch accepted")
    except sr.Conflict:
        pass
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print("OK signal_representation: known-answer record, idempotent additive sidecar, atomic, fail-closed conflicts, supersede path")
