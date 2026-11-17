"""M709 known-answer tests for tools/restart_census.py (spec analyses/M708_spec.md Rev 2): endpoint rule on a synthetic raw drive, DST-safe gap, pair exclusions and unlogged-use flags,
day-clustered bootstrap, the per-drive slow-polled rule of E5."""
import os, sys, tempfile
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import restart_census as RC

C = RC.COLS


def write_drive(path, rows):
    """rows: list of (time_str, T1, T2, T3, T4, speed). Header = the real column names."""
    h = ["time", C["T1"], C["T2"], C["T3"], C["T4"], C["spd_vcm"], C["soc"]]
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(",".join(h) + "\n")
        for t, a, b, c, d, v in rows:
            f.write(",".join([t] + ["" if x is None else str(x) for x in (a, b, c, d, v, 55)]) + "\n")


with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "20260601_120000.csv")
    # T1 first reads at 1 s, T2 at 3 s, T3 at 5 s (all before movement at 10 s); T4 first reads at 40 s: after movement AND outside the 30 s fallback, so no start
    rows = [("12:00:00.000", None, None, None, None, 0), ("12:00:01.000", 10, None, None, None, 0), ("12:00:03.000", None, 11, None, None, 0), ("12:00:05.000", None, None, 12, None, 0),
            ("12:00:07.000", 99, None, None, None, 0),                                   # a LATER T1 reading must not replace the earliest one
            ("12:00:10.000", None, None, None, None, 20), ("12:00:40.000", None, None, None, 13, 30),
            ("12:10:00.000", 14, 14, 14, 14, 30), ("12:10:30.000", 15, 16, 17, 107, 0),   # 107 = sentinel, dropped; the last valid T4 is 14
            ("12:11:00.000", None, None, None, None, 0)]
    rows = rows[:-1] + [("12:10:%02d.000" % (31 + i), None, None, None, None, 0) for i in range(25)] + rows[-1:]   # the speed channel needs >= 20 samples to count (as in the census rule)
    write_drive(p, rows)
    r = RC.read_drive(p)
    assert r["T1_s"] == 10.0 and r["T2_s"] == 11.0 and r["T3_s"] == 12.0 and r["T1_s_am"] == 0, "earliest native reading at or before first movement"
    assert not np.isfinite(r.get("T4_s", np.nan)), "T4 first reading at 40 s is outside both start rules"
    assert r["T1_e"] == 15.0 and r["T2_e"] == 16.0 and r["T3_e"] == 17.0, "end = last native reading within 60 s of log end"
    assert r["T4_e"] == 14.0, "the sentinel 107 is dropped"
    assert abs(r["dur_s"] - 660.0) < 1e-6 and abs(r["t_move0"] - 10.0) < 1e-6
    # start after movement: first reading within 30 s of log start is used and flagged
    p2 = os.path.join(td, "20260601_130000.csv")
    write_drive(p2, [("13:00:00.000", None, None, None, None, 0), ("13:00:05.000", None, None, None, None, 20), ("13:00:20.000", 8, 8, 8, 8, 25)]
                + [("13:10:%02d.000" % i, None, None, None, None, 0) for i in range(25)] + [("13:20:00.000", 9, 9, 9, 9, 0)])
    r2 = RC.read_drive(p2)
    assert r2["T1_s"] == 8.0 and r2["T1_s_am"] == 1 and r2["T1_e"] == 9.0, "start_after_move fallback within 30 s, flagged"
    # DST fall-back in Kyiv (2026-10-25 04:00 EEST -> 03:00 EET): local 23:30 -> next local 06:00 is 7.5 h of real time, 6.5 h on the naive clock
    u1, _ = RC._utc0("20261024233000", 23 * 3600 + 30 * 60)
    u2, _ = RC._utc0("20261025060000", 6 * 3600)
    assert abs((u2 - u1) / 3600 - 7.5) < 1e-9, "gap is computed on a UTC clock, not the naive local clock"
    # a file named just before midnight whose first row is after midnight moves to the next day
    u3, loc3 = RC._utc0("20260601235958", 2.0)
    assert loc3.startswith("2026-06-02 00:00:02")


def drive(key, utc0, dur, t_s, t_e, soc0=60.0, soc1=60.0, odo0=0.0, cool_s=None, cool_e=None):
    d = {"key": key, "utc0": utc0, "utc1": utc0 + dur, "soc_first": soc0, "soc_last": soc1, "odo_start": odo0, "odo_end": 0.0}
    for i, p in enumerate(RC.PROBES):
        d[p + "_s"], d[p + "_e"] = t_s[i], t_e[i]
    d["Tcool_s"], d["Tcool_e"] = cool_s, cool_e
    return d


H = 3600.0
E = pd.DataFrame([
    drive("A", 0.0, 600, [20] * 4, [30, 30, 31, 31]),
    drive("B", 600 + 0.1 * H, 600, [30, 30, 30, 31], [25] * 4),                          # 6 min gap: change -0.25 (same-probe mean)
    drive("C", 1200 + 0.1 * H + 8 * H, 600, [20] * 4, [22] * 4, soc0=63.0),              # 8 h gap, SoC +3.0 points -> flagged unlogged use
    drive("D", 1800 + 0.1 * H + 8 * H + 2 * H, 600, [np.nan] * 4, [22] * 4),             # no probe reading at the start -> excluded
    drive("E", 2400 + 0.1 * H + 10 * H + 300 * H, 600, [20] * 4, [20] * 4),              # gap > 168 h -> excluded
    drive("F", 3000 + 0.1 * H + 10 * H + 300 * H + 0.5 * H, 600, [20] * 4, [20] * 4, odo0=5.0),   # app-counter step 5 km -> excluded
])
E["day"] = ["2026-06-01", "2026-06-01", "2026-06-02", "2026-06-02", "2026-06-20", "2026-06-20"]
P = RC.build_pairs(E, {k: 15.0 for k in E["key"]})
ex = RC.exclusion_counts(P)
assert ex["pairsTotal"] == 5 and ex["noFreshProbeAtAnEndpoint"] == 1 and ex["gapOver168h"] == 1 and ex["odoStepAbsGt1km_appCounter"] == 1 and ex["eligible"] == 2, ex
AB = P[P["pair_id"] == "A|B"].iloc[0]
assert AB["elig"] and abs(AB["d_same"] - (np.mean([30, 30, 30, 31]) - np.mean([30, 30, 31, 31]))) < 1e-9 and AB["gc"] == "<10 min"
BC = P[P["pair_id"] == "B|C"].iloc[0]
assert BC["flagged"] and BC["mp_soc"] and BC["elig"], "SoC +3 points in a gap = evidence of unlogged use: kept (flagged) in the census"
assert abs(BC["dsoc"] - 3.0) < 1e-9
# unflagged control: the same pair without the SoC rise
E2 = E.copy()
E2.loc[2, "soc_first"] = 60.0
assert not RC.build_pairs(E2, {k: 15.0 for k in E2["key"]}).query("pair_id == 'B|C'")["flagged"].iloc[0]
# cool-hot rule: gap >= 6 h and engine coolant >= 15 C above the recorded ambient at restart
E3 = E2.copy()
E3.loc[2, "Tcool_s"] = 40.0
assert RC.build_pairs(E3, {k: 15.0 for k in E3["key"]}).query("pair_id == 'B|C'")["mp_coolHot"].iloc[0]

# day-clustered bootstrap: constant data -> zero-width interval; deterministic with the seed; whole days are the unit
b = RC.boot_mean(["d1", "d1", "d2", "d3"], [1.0, 1.0, 1.0, 1.0])
assert b["est"] == 1.0 and b["lo"] == 1.0 and b["hi"] == 1.0 and b["nDays"] == 3 and b["n"] == 4
x = np.r_[np.full(50, 0.0), np.full(50, 2.0)]
days = ["a%d" % (i // 5) for i in range(100)]
b1, b2 = RC.boot_mean(days, x), RC.boot_mean(days, x)
assert b1 == b2 and b1["lo"] < 1.0 < b1["hi"] and b1["nDays"] == 20

# E5: slow-polled per drive = median T2-T4 period strictly above 10 s; ledger-minus-native difference by regime
with tempfile.TemporaryDirectory() as td:
    L = pd.DataFrame({"file": ["20260601_000000.csv", "20260601_010000.csv"], "pack_temp_start_c": [31.0, 30.0]})
    L.to_csv(os.path.join(td, "ledger.csv"), index=False)
    EE = pd.DataFrame({"key": ["20260601000000", "20260601010000"], "day": ["2026-06-01"] * 2, "file": L["file"],
                       "T1_s": [30.0, 30.0], "T2_s": [30.0, 30.0], "T3_s": [29.0, 30.0], "T4_s": [29.0, 30.0],
                       "T1_dt_med": [6.0, 6.0], "T2_dt_med": [12.0, 8.0], "T3_dt_med": [12.0, 8.0], "T4_dt_med": [12.0, 8.0], "T1_n": [10, 10], "T2_n": [5, 5], "T3_n": [5, 5], "T4_n": [5, 5]})
    res, D = RC.e5_start_bias(EE, os.path.join(td, "ledger.csv"))
    assert res["slowPerDrive"]["est"] == 1.5 and res["fastPerDrive"]["est"] == 0.0 and bool(D["slow"].iloc[0]) and not bool(D["slow"].iloc[1])
print("test_restart_census: ok")
