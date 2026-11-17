"""M710 (R4) known-answer tests: raw_temp_pass native pack start (pack_temp_start_native_c / _n / pack_temp_start_after_move) beside the unchanged legacy composite pack_temp_start_c.
Rule (spec analyses/M708_spec.md Rev 2 section 2): per probe the EARLIEST valid reading, at or before first movement and within 60 s of log start; else the first reading within 30 s (flag)."""
import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, ROOT)
import raw_temp_pass as R

A = R.ALIASES


def write(path, rows):
    h = ["time", A["T1"][0], A["T2"][0], A["T3"][0], A["T4"][0], A["spd_vcm"][0]]
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(h) + "\n")
        for t, a, b, c, d, v in rows:
            f.write(",".join([t] + ["" if x is None else str(x) for x in (a, b, c, d, v)]) + "\n")


def pad(hh, mm, start_s, n=25):
    return [("%s:%s:%02d.000" % (hh, mm, start_s + i), None, None, None, None, 0) for i in range(n)]


# unit: first movement and the start rule
assert R.first_move_rel([(0.0, 0.0), (5.0, 20.0)], [], 0.0) is None, "fewer than 20 VCM samples: the VCM speed is not used"
assert R.first_move_rel([(float(i), 0.0 if i < 7 else 10.0) for i in range(30)], [], 0.0) == 7.0
assert R.first_move_rel([(float(i), 0.0) for i in range(25)], [(3.5, 12.0)], 0.0) == 3.5, "a gap in VCM speed is filled from the OBD speed"
assert R.native_pack_start({"T1": (2.0, 10.0), "T2": (4.0, 12.0), "T3": None, "T4": None}, 10.0) == (11.0, 2, 0)
assert R.native_pack_start({"T1": (2.0, 10.0), "T2": (25.0, 12.0)}, 10.0) == (11.0, 2, 1), "a reading after movement but within 30 s is used and flagged"
assert R.native_pack_start({"T1": (40.0, 10.0)}, 10.0) == (None, 0, 0), "after movement and after 30 s: no start"
assert R.native_pack_start({"T1": (40.0, 10.0)}, None) == (10.0, 1, 0), "a log that never moves: any reading within 60 s counts (census rule)"
assert R.native_pack_start({"T1": (70.0, 10.0)}, None) == (None, 0, 0), "never later than 60 s even when the log never moves"

with tempfile.TemporaryDirectory() as td:
    # slow-polled style drive: T1 at 1 s, T2-T4 first read at 14 s (a 10 s hold at 12 s sees only T1; the native rule waits for all probes)
    p = os.path.join(td, "20260901_100000.csv")
    rows = [("10:00:00.000", None, None, None, None, 0), ("10:00:01.000", 20, None, None, None, 0), ("10:00:07.000", 20, None, None, None, 0),
            ("10:00:14.000", None, 18, 18, 18, 0), ("10:00:20.000", None, None, None, None, 15)] + pad("10", "01", 0) + [("10:05:00.000", 22, 21, 21, 21, 30)]
    write(p, rows)
    o = R.process_file(p)
    assert o["pack_temp_start_native_c"] == 18.5 and o["pack_temp_start_native_n"] == 4 and o["pack_temp_start_after_move"] == 0, o
    # legacy composite: the median of the first 30 s of the 10 s-hold composite is T1-weighted (20.0 while only T1 is fresh), i.e. warmer than the native mean 18.5
    assert o["pack_temp_start_c"] > o["pack_temp_start_native_c"], (o["pack_temp_start_c"], o["pack_temp_start_native_c"])
    # fast-polled drive: all probes in the first seconds: both definitions agree
    q = os.path.join(td, "20260901_110000.csv")
    write(q, [("11:00:00.000", None, None, None, None, 0), ("11:00:01.000", 10, 10, 10, 10, 0), ("11:00:09.000", None, None, None, None, 20)] + pad("11", "00", 20) + [("11:05:00.000", 12, 12, 12, 12, 30)])
    o2 = R.process_file(q)
    assert o2["pack_temp_start_native_c"] == 10.0 and o2["pack_temp_start_native_n"] == 4 and o2["pack_temp_start_c"] == 10.0
    # start after movement within 30 s: flagged
    r3 = os.path.join(td, "20260901_120000.csv")
    write(r3, [("12:00:00.000", None, None, None, None, 0), ("12:00:05.000", None, None, None, None, 20), ("12:00:20.000", 9, 9, 9, 9, 25)] + pad("12", "01", 0) + [("12:10:00.000", 9, 9, 9, 9, 0)])
    o3 = R.process_file(r3)
    assert o3["pack_temp_start_native_c"] == 9.0 and o3["pack_temp_start_after_move"] == 1
    # no probe at all: blanks, not zeros
    s4 = os.path.join(td, "20260901_130000.csv")
    write(s4, [("13:00:00.000", None, None, None, None, 0)] + pad("13", "00", 1) + [("13:05:00.000", None, None, None, None, 0)])
    o4 = R.process_file(s4)
    assert o4["pack_temp_start_native_c"] is None and o4["pack_temp_start_native_n"] == 0 and o4["pack_temp_start_after_move"] == 0
print("test_m710_native_start: ok")
