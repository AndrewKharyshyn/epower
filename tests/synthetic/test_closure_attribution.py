"""M398 known-answer tests (analyses/M398_spec.md): the attributed re-pin of the GTR closure pin after recalibration drift. Each condition has a case that passes and a case that STOPs without writing a pin."""
import json, os, shutil, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
import numpy as np, pandas as pd
import m372_closure_common as CM

RECAL = ["I_offset_A_applied", "net_draw_kwh_corr"]
ids = [f"2026-09-{i:02d}_10-00-00.csv" for i in range(1, 13)]
prev = pd.DataFrame({"file": ids, "g2t": np.linspace(1.0, 2.0, 12).round(5), "trac": np.linspace(3.0, 4.0, 12).round(5), "date": ["2026-09-%02d" % i for i in range(1, 13)]})


def cur_from(prev, shift=0.0):
    d = prev.copy()
    d["g2t"] = (d["g2t"] + shift).round(5)
    new = pd.DataFrame({"file": ["2026-10-01_09-00-00.csv"], "g2t": [1.5], "trac": [3.5], "date": ["2026-10-01"]})        # a NEW id is never compared
    return pd.concat([d, new], ignore_index=True)


def master(offset, extra_changed=None):
    m = pd.DataFrame({"file": ids, "I_offset_A_applied": [offset] * 12, "net_draw_kwh_corr": [str(i) for i in range(12)], "soc_start": ["60"] * 12, "distance_km": ["5"] * 12}).astype(str)
    if extra_changed:
        m[extra_changed] = "99"
    return m


rec = {"path": "analyses/closure_baselines/x.csv", "sha256": "0", "nDrives": 12, "master": "headmd5"}
old_m, new_m = master("-0.3839"), master("-0.3824")

# 1. identity: exact -> nothing to attribute; drift -> reported with magnitudes
diff, mag, miss, n, ncols = CM.identity_drift(cur_from(prev), prev)
assert diff == [] and miss == [] and n == 12
diff, mag, miss, n, ncols = CM.identity_drift(cur_from(prev, 0.0001), prev)
assert diff == [("g2t", 12)] and abs(mag["g2t"]["maxAbs"] - 0.0001) < 1e-9 and mag["g2t"]["colSumRelChange"] > 0
assert CM.identity_drift(cur_from(prev).iloc[3:], prev)[2][:3] == ids[:3]                      # previous IDs missing from the current rows are reported, never compared as NaN

# 2. all four conditions hold -> evidence returned
ev = CM.attribute_recalibration_drift(cur_from(prev, 0.0001), prev, rec, cur_from(prev), old_m, new_m, RECAL, "headmd5")
assert ev["rule"] == "M398" and ev["hybridRunIdentityExact"] and ev["masterColumnsChangedOnPreviousIds"] == ["I_offset_A_applied"] and ev["driftColumns"]["g2t"]["nDrivesChanged"] == 12


def stops(fn, needle):
    try:
        fn()
    except SystemExit as e:
        assert needle in str(e), str(e)
        return
    raise AssertionError("expected a STOP containing: " + needle)


# 3. each condition failing separately STOPs
stops(lambda: CM.attribute_recalibration_drift(cur_from(prev, 0.0001), prev, dict(rec, master="other"), cur_from(prev), old_m, new_m, RECAL, "headmd5"), "not the committed pre-ingestion master")
stops(lambda: CM.attribute_recalibration_drift(cur_from(prev, 0.0001), prev, rec, cur_from(prev), old_m, master("-0.3824", extra_changed="soc_start"), RECAL, "headmd5"), "other than the recalibration columns")
stops(lambda: CM.attribute_recalibration_drift(cur_from(prev, 0.0001), prev, rec, cur_from(prev, 0.0002), old_m, new_m, RECAL, "headmd5"), "does NOT reproduce the pinned file exactly")
stops(lambda: CM.attribute_recalibration_drift(cur_from(prev, 0.01), prev, rec, cur_from(prev), old_m, new_m, RECAL, "headmd5"), "exceeds the pre-registered tolerance")
stops(lambda: CM.attribute_recalibration_drift(cur_from(prev, 0.0001), prev, rec, cur_from(prev).iloc[1:], old_m, new_m, RECAL, "headmd5"), "does NOT reproduce")        # hybrid missing an ID
stops(lambda: CM.attribute_recalibration_drift(cur_from(prev, 0.0001), prev, rec, cur_from(prev), old_m.iloc[1:], new_m, RECAL, "headmd5"), "missing from the pre-ingestion or current master")

# 3b. Director (M398): non-numeric drift STOPs; cumulative drift against the ORIGINAL pin is bounded and recorded
prev_t = prev.assign(kind=["a"] * 12)
cur_t = cur_from(prev_t, 0.0001); cur_t.loc[0, "kind"] = "b"
stops(lambda: CM.attribute_recalibration_drift(cur_t, prev_t, rec, cur_from(prev_t), old_m, new_m, RECAL, "headmd5"), "non-numeric closure columns differ")
far = prev.assign(g2t=(prev["g2t"] - 0.002).round(5))
stops(lambda: CM.attribute_recalibration_drift(cur_from(prev, 0.0001), prev, rec, cur_from(prev), old_m, new_m, RECAL, "headmd5", orig=far), "cumulative drift against the original pin")
near = prev.assign(g2t=(prev["g2t"] - 0.0001).round(5))
ev2 = CM.attribute_recalibration_drift(cur_from(prev, 0.0001), prev, rec, cur_from(prev), old_m, new_m, RECAL, "headmd5", orig=near)
assert ev2["cumulativeVsOriginalPin"]["g2t"]["maxAbs"] > 1e-4 and "5-dp" in ev2["nDrivesChangedConvention"] and ev["cumulativeVsOriginalPin"] is None

# 4. re-pin: unique file per master, record keeps history and evidence, earlier pin file untouched; manual path keeps its name
with tempfile.TemporaryDirectory() as td:
    old_root, old_rec = CM.ROOT, CM.RECORD
    CM.ROOT, CM.RECORD = td, os.path.join(td, "analyses", "gtr_closure_record.json")
    os.makedirs(os.path.join(td, "analyses"), exist_ok=True)
    open(os.path.join(td, "drive_master.csv"), "wb").write(b"file,x\nA,1\n")
    try:
        d = cur_from(prev, 0.0001)
        r1 = CM.repin_previous(d, prev, rec, "auto (M398): test", evidence=ev)
        p1 = r1["previousPerDrive"]["path"]
        assert "_recal_" in p1 and r1["previousPerDrive"]["nDrives"] == 12 and r1["attribution"]["rule"] == "M398" and r1["repinnedFrom"] == rec and r1["previousPerDrive"]["master"]
        assert r1["originalPin"] == rec                                                                          # first pin of the chain
        assert os.path.exists(os.path.join(td, p1)) and json.load(open(CM.RECORD, encoding="utf-8"))["previousPerDrive"]["path"] == p1
        got = pd.read_csv(os.path.join(td, p1))
        assert list(got["file"]) == ids and (got["g2t"].values == d["g2t"].values[:12]).all()                    # subset of the previous IDs on the NEW values; the new id is not in the pin
        open(os.path.join(td, "drive_master.csv"), "wb").write(b"file,x\nA,2\n")                                 # another master -> another file name, the first pin file survives
        r2 = CM.repin_previous(d, prev, r1["previousPerDrive"], "auto (M398): test 2", evidence=ev)
        assert r2["originalPin"] == rec                                                                          # the chain keeps pointing at the first pin
        assert r2["previousPerDrive"]["path"] != p1 and os.path.exists(os.path.join(td, p1))
        r3 = CM.repin_previous(d, prev, rec, "manual")                                                            # the Director override path keeps its old name and note
        assert r3["previousPerDrive"]["path"].endswith("_recal.csv") and "attribution" not in r3
    finally:
        CM.ROOT, CM.RECORD = old_root, old_rec

# 5. the unchanged identity assertion still STOPs on drift and passes on identity (writes the drift report before stopping)
with tempfile.TemporaryDirectory() as td:
    old_root = CM.ROOT
    CM.ROOT = td
    os.makedirs(os.path.join(td, "analyses"), exist_ok=True)
    try:
        assert CM.assert_previous_identity(cur_from(prev), prev)["nIdentical"] == 12
        stops(lambda: CM.assert_previous_identity(cur_from(prev, 0.0001), prev), "differ from the pinned file")
        rep = json.load(open(os.path.join(td, "analyses", "M377c_identity_drift.json"), encoding="utf-8"))
        assert rep["nPrevious"] == 12 and rep["columns"]["g2t"]["nDrivesChanged"] == 12
    finally:
        CM.ROOT = old_root
print("OK closure attribution: exact identity, four conditions (each STOPs separately), unique re-pin, history kept, manual path unchanged")
