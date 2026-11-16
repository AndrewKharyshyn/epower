"""Known-answer tests for tools/rpm_window_cache.py and tools/oem_crosscheck.py (M705 spec Rev 1)."""
import os, sys, json
import numpy as np, pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
os.chdir(ROOT)
import rpm_window_cache as W
import oem_crosscheck as OC


def grid(rpm, speed=None):
    n = len(rpm)
    return pd.DataFrame({"rpm": np.asarray(rpm, float), "speed": np.full(n, 30.0) if speed is None else np.asarray(speed, float)})


def seg(*parts):
    out = []
    for v, n in parts:
        out += [v] * n
    return np.array(out, float)


def entry(rpm, speed=None):
    H, meta, rr, zone, revm, valid = W.build_entry(grid(rpm, speed), None)
    W.gate(H, rr, zone, revm, valid)
    return H, meta


def test_planted_window_shares_are_exact_for_both_thresholds():
    rpm = seg((0, 100), (2000, 1000), (1000, 500), (4400, 100), (0, 50))      # 1000 s at 2000, 500 s at 1000, 100 s at 4400
    H, meta = entry(rpm)
    v = W.VARIANTS.index((400, 0, 0, 0))
    assert W.window_sum(H[v], *W.WINDOWS["C1_150"]) == 1000 and W.window_sum(H[v], *W.WINDOWS["C2_100"]) == 100
    assert int(H[v].sum()) == 1600 and int(meta[1, 0, 0]) == 1600
    assert W.window_sum(H[W.VARIANTS.index((300, 0, 0, 0))], 0, 6000) == 1600


def test_edges_are_lower_inclusive_upper_exclusive_and_the_threshold_is_strict():
    rpm = seg((1850, 5), (2150, 5), (1500, 5), (1499, 5), (400, 5), (401, 5), (300, 5), (0, 3))
    H, _ = entry(rpm)
    v4 = H[W.VARIANTS.index((400, 0, 0, 0))]; v3 = H[W.VARIANTS.index((300, 0, 0, 0))]
    assert W.window_sum(v4, 1850, 2150) == 5                           # 1850 in, 2150 out
    assert W.window_sum(v4, 0, 1500) == 5 + 5                          # 1499 and 401 (400 exactly is not engine-on at the 400 threshold)
    assert W.window_sum(v3, 0, 1500) == 5 + 5 + 5                      # at the 300 threshold 400 is on, 300 exactly is not
    assert int(v4.sum()) == 5 * 5 and int(v3.sum()) == 5 * 6


def test_ramp_exclusion_short_runs_censored_edges_and_nan_break():
    rpm = seg((1000, 100), (0, 20), (1000, 8), (0, 20), (1000, 60))        # a run at the drive start (censored), a run shorter than 2r, an interior run
    H, meta = entry(rpm)
    v0 = H[W.VARIANTS.index((400, 0, 0, 0))]; v5 = H[W.VARIANTS.index((400, 5, 0, 0))]
    assert int(v0.sum()) == 168
    # r = 5: run 1 (100 s) loses 10 s, run 2 (8 s <= 10) is fully excluded, run 3 (60 s) loses 10 s
    assert int(v5.sum()) == 90 + 0 + 50
    ri = list(W.RAMPS).index(5)
    assert int(meta[1, ri, 1]) == 1                                    # one fully excluded run
    assert int(meta[1, ri, 2]) >= 2                                    # censored edges (drive start, drive end) are counted
    nan = seg((1000, 40), (np.nan, 1), (1000, 40))                     # a NaN second breaks the run into two runs
    Hn, mn = entry(nan)
    assert int(Hn[W.VARIANTS.index((400, 5, 0, 0))].sum()) == 2 * (40 - 10)


def test_gate_stops_on_a_corrupted_histogram():
    rpm = seg((2000, 200), (0, 20))
    H, meta, rr, zone, revm, valid = W.build_entry(grid(rpm), None)
    H[W.VARIANTS.index((400, 0, 0, 0))][zone[0], 2000 // W.BIN] -= 1
    try:
        W.gate(H, rr, zone, revm, valid)
    except SystemExit as e:
        assert "STOP gate" in str(e)
    else:
        raise AssertionError("the gate did not stop")


def test_share_ratio_of_sums_support_floor_and_zero_cell_note():
    drives = [{"date": "2026-09-%02d" % (1 + i // 2), "n": 10, "d": 100} for i in range(24)]       # 12 days, 24 drives
    s = OC.share(drives, lambda x: x["n"], lambda x: x["d"])
    assert abs(s["pct"] - 10.0) < 1e-9 and s["drives"] == 24 and s["days"] == 12 and s["ci95"][0] <= 10.0 <= s["ci95"][1]
    assert "not estimable" in OC.share(drives[:6], lambda x: x["n"], lambda x: x["d"])["status"]
    z = OC.share(drives, lambda x: 0, lambda x: x["d"])
    assert z["pct"] == 0.0 and "no occupancy observed in 24 drives on 12 days" in z["note"]


def test_not_comparable_record_and_no_consistent_label():
    src = OC.sources()
    assert "notComparable80" in src and src["notComparable80"]["id"] == "S3"
    p = os.path.join(ROOT, "analyses", "M705_study.json")
    if os.path.exists(p):
        txt = open(p, encoding="utf-8").read().lower()
        assert "consistent" not in txt and "margin" not in txt


def test_speed_zone_assignment_and_a_drive_without_speed():
    rpm = seg((2000, 30))
    sp = np.concatenate([np.full(10, 10.0), np.full(10, 50.0), np.full(10, np.nan)])
    H, _ = entry(rpm, sp)
    v = H[W.VARIANTS.index((400, 0, 0, 0))]
    assert int(v[0].sum()) == 10 and int(v[2].sum()) == 10 and int(v[W.NZONE - 1].sum()) == 10


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
    print("PASS test_m705_rpm_windows")
