"""M582a (analyses/M582_spec.md Rev 1) known-answer tests: header parser, class rule, file-name mapping, block construction on a synthetic frame, language rule, and the tie-out of the real master
(fixture pinned to master MD5 1574a8156a36c6ea4ea1dfdaafc7cc72, not to live counts)."""
import hashlib, json, os, sys, tempfile
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import pid_epoch as P

IAT, MPC = P.IAT, P.MPC
# ---- class rule and header parser
assert P.classify(True, False) == "A" and P.classify(False, True) == "B" and P.classify(False, False) == "C" and P.classify(True, True) == "D"
cols = ["time", "Speed (km/h)", IAT, "[VCM] Motor RPM (rpm)", "Unnamed: 4", "Unnamed: 5"]
nc, nn, iat, mpc, h, nv = P.parse_columns(cols)
assert (nc, nn, iat, mpc, nv) == (6, 4, True, False, 1) and len(h) == 12
assert P.parse_columns(list(reversed(cols)))[4] == h                      # the hash does not depend on the column order
assert P.parse_columns(cols + ["Unnamed: 9"])[4] == h and P.parse_columns(cols + ["[VCM] Foo"])[4] != h
assert P.parse_columns(["x", MPC])[3] is True and P.parse_columns(["x", MPC])[2] is False
# ---- file-name mapping (both master name styles)
assert P.raw_name("20260513_182950.csv") == "2026-05-13 18-29-50.csv" and P.raw_name("2026-11-04_08-01-15.csv") == "2026-11-04 08-01-15.csv" and P.raw_name("weird.csv") is None
# ---- read_row on a temporary raw directory (header only, non-null fraction, encoding errors tolerated, unmatched file STOPs)
with tempfile.TemporaryDirectory() as tmp:
    with open(os.path.join(tmp, "2026-11-04 08-01-15.csv"), "wb") as f:
        f.write(("time,Speed,%s,Unnamed: 3\n0,1,,\n1,2,5.0,\n2,3,,\n3,4,7.0,\n" % MPC).encode("utf-8"))
    r = P.read_row("2026-11-04_08-01-15.csv", tmp)
    assert r["pidSetClass"] == "B" and r["mpcPresent"] is True and r["iatPresent"] is False and abs(r["mpcNonNullFraction"] - 0.5) < 1e-9 and r["nNamedColumns"] == 3 and r["nColumns"] == 4
    try:
        P.read_row("20990101_000000.csv", tmp)
    except SystemExit as e:
        assert "STOP" in str(e)
    else:
        raise AssertionError("an unmatched master file must STOP")

# ---- block construction on a synthetic frame: runs, within-day contrast, Q3 readiness
rows = []
for i in range(12):
    day = "2026-11-%02d" % (1 + i // 3)
    cls = "A" if i < 4 else "B"
    rows.append({"file": "d%02d.csv" % i, "date": day, "time_start": "%02d:00:00" % (8 + i % 3), "I_sample_period_s": 0.8 if cls == "A" else 0.97})
dm = pd.DataFrame(rows)
side = pd.DataFrame({"file": dm["file"], "pidSetClass": ["A"] * 4 + ["B"] * 8, "iatNonNullFraction": [0.01] * 4 + [float("nan")] * 8, "mpcNonNullFraction": [float("nan")] * 4 + [0.06] * 8, "pidSetHash": ["h1"] * 4 + ["h2"] * 8})
reg = pd.DataFrame({"file": dm["file"], "regime": ["fast"] * 12})
b = P.build_block(dm, side, reg, "md5x")
assert b["counts"]["A"]["drives"] == 4 and b["counts"]["B"]["drives"] == 8 and b["counts"]["C"]["drives"] == 0 and b["counts"]["B"]["periodS"]["median"] == 0.97
assert [x["cls"] for x in b["runs"]] == ["A", "B"] and b["q3Readiness"]["runDrives"] == 8 and b["q3Readiness"]["runDays"] == 3 and b["q3Readiness"]["status"].startswith("not identified")
assert [d["day"] for d in b["withinDayContrast"]["days"]] == ["2026-11-02"] and b["withinDayContrast"]["days"][0]["A"]["n"] == 1 and b["withinDayContrast"]["days"][0]["B"]["n"] == 2
assert "no cadence effect and no causal mechanism is claimed" in b["statement"] and "post hoc" in b["disclosure"]
# the floors are met: 10 drives on 5 days in the final B run
rows2 = [{"file": "e%02d.csv" % i, "date": "2026-12-%02d" % (1 + i // 2), "time_start": "0%d:00:00" % (8 + i % 2), "I_sample_period_s": 0.97} for i in range(12)]
dm2 = pd.DataFrame(rows2)
b2 = P.build_block(dm2, pd.DataFrame({"file": dm2["file"], "pidSetClass": ["B"] * 12, "iatNonNullFraction": [float("nan")] * 12, "mpcNonNullFraction": [0.06] * 12, "pidSetHash": ["h"] * 12}), pd.DataFrame({"file": dm2["file"], "regime": ["fast"] * 12}), "md5y")
assert b2["q3Readiness"]["runDrives"] == 12 and b2["q3Readiness"]["runDays"] == 6 and b2["q3Readiness"]["status"] == "testable under M577 Rev 2"
# a final run of class A is not a class B run
b3 = P.build_block(dm, side.assign(pidSetClass=["B"] * 4 + ["A"] * 8), reg, "md5z")
assert b3["q3Readiness"]["runDrives"] == 0

# ---- language rule fires on causal wording and stays silent on the shipped statement
import language_gate as L
for bad in ("the sampling period is shorter because of the VCM PID", "PID effect on the period", "the epoch was identified", "caused by the Motor Power Consumption PID"):
    assert "M582-pidset-wording" in L.scan_text(bad), bad
for ok_ in (P.STATEMENT, P.DISCLOSURE, "no cadence effect and no causal mechanism is claimed; the epoch is not identified"):
    assert "M582-pidset-wording" not in L.scan_text(ok_), ok_

# ---- tie-out of the real master (only on the pinned master)
if hashlib.md5(open("drive_master.csv", "rb").read()).hexdigest() == "1574a8156a36c6ea4ea1dfdaafc7cc72":
    A = json.load(open("summary_arrays.json", encoding="utf-8"))["pidEpoch"]
    c = A["counts"]
    assert [c[k]["drives"] for k in "ABCD"] == [606, 14, 7, 5] and A["nDrives"] == 632
    assert c["B"]["periodS"]["median"] == 0.97 and c["A"]["periodS"]["median"] == 1.283
    assert A["q3Readiness"]["runDrives"] == 13 and A["q3Readiness"]["runDays"] == 3 and A["q3Readiness"]["status"].startswith("not identified")
    assert [x["day"] for x in A["earlyClassB"]] == ["2026-05-13"] and len(A["classC"]) == 7 and len(A["classD"]) == 5
    wd = A["withinDayContrast"]["days"]
    assert [d["day"] for d in wd] == ["2026-11-03"] and wd[0]["A"]["n"] == 2 and wd[0]["B"]["n"] == 3 and abs(wd[0]["A"]["median"] - 0.802) < 1e-9 and abs(wd[0]["B"]["median"] - 0.968) < 1e-9
    side = pd.read_csv("pid_epoch.csv")
    assert len(side) == 632 and side["pidSetClass"].value_counts().to_dict() == {"A": 606, "B": 14, "C": 7, "D": 5}
    reg = pd.read_csv("cadence_regime.csv")
    assert list(side["file"]) == list(pd.read_csv("drive_master.csv", low_memory=False)["file"]) and len(reg) == 632
print("test_m582_pid_epoch: OK")
