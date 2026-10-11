"""M400 (audit N01-N03, analyses/M400_spec.md): known-answer tests for the dissipation-event detectors on the full time grid.
Each case fails on the pre-M400 detectors (rows with a missing channel dropped before run detection, per-detector time origin, load.fillna(0))."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
import numpy as np, pandas as pd
import dissipation_events as DE
import dissipation_monitor as DM

C = {v: k for k, v in DE.COLS.items()}
MOT = {"rpm": 2500.0, "boost": -0.80, "load": 5.0, "fuel": 0.0, "thr": 2.0}


def drive(segments, n=200, drop_rows=(), blank=None, times=None):
    """1 Hz rows with a fuelled base state; segments override values; drop_rows = seconds with NO row; blank = {key: (start, end)} -> empty cells;
    times = optional explicit second for every kept row (irregular timestamps)."""
    base = {"rpm": 1800.0, "boost": 0.05, "load": 40.0, "soc": 65.0, "fuel": 3.0, "thr": 30.0, "speed": 50.0, "I": 0.0}
    rows, secs = [], []
    for t in range(n):
        if t in drop_rows:
            continue
        r = dict(base)
        for s, d, ov in segments:
            if s <= t < s + d:
                r.update(ov)
        for k, (a, b) in (blank or {}).items():
            if a <= t < b:
                r[k] = np.nan
        rows.append(r); secs.append(t)
    df = pd.DataFrame(rows)
    if times is not None:
        secs = list(times)
    out = pd.DataFrame({"time": [f"{t // 3600:02d}:{(t // 60) % 60:02d}:{t % 60:02d}.000" for t in secs]})
    for k, col in C.items():
        out[col] = df[k].to_numpy()
    return out.to_csv(index=False).encode("utf-8")


# N01: two 6 s runs separated by 20 missing seconds (rows absent) are two events, not one sustained 12 s event
g = DE.grid_from_csv_bytes(drive([(50, 6, MOT), (76, 6, MOT)], drop_rows=set(range(56, 76))))
for kind in ("PUB", "FUEL"):
    ev = DE.detect(g, kind)
    assert len(ev) == 2 and not any(e["sustained"] for e in ev), (kind, ev)
    assert ev[1]["t0_s"] - ev[0]["t0_s"] > 20, ev                      # the second run starts after the gap, on the shared clock
# a fully observed 12 s run is still one sustained event (contiguous masks unchanged)
ev = DE.detect(DE.grid_from_csv_bytes(drive([(50, 12, MOT)])), "PUB")
assert len(ev) == 1 and ev[0]["sustained"] and ev[0]["dur_s"] == 12 and ev[0]["end_s"] == ev[0]["t0_s"] + 12
# slope from timestamps: rpm rising 100 rpm per second on a 1 s grid -> +100/s, whatever the row positions
ramp = [(60 + i, 1, dict(MOT, rpm=2100.0 + 100.0 * i)) for i in range(10)]
e = DE.detect(DE.grid_from_csv_bytes(drive(ramp)), "PUB")[0]
assert abs(e["rpm_slope_per_s"] - 100.0) < 1e-6 and not e["sustained"], e

# N02: PUB missing its first 10 s of boost; both detectors report the event on the same drive clock and overlap
raw = drive([(50, 30, MOT)], blank={"boost": (0, 10)})
g = DE.grid_from_csv_bytes(raw)
pub, fu = DE.detect(g, "PUB"), DE.detect(g, "FUEL")
assert len(pub) == 1 and len(fu) == 1 and pub[0]["t0_s"] == fu[0]["t0_s"] == 50.0, (pub, fu)
assert DE.overlaps(pub[0], fu[0])
# unequal channel availability cannot create a false overlap: FUEL event at 50-80 s, PUB event at 120-150 s
raw = drive([(50, 30, dict(MOT, boost=0.05, load=40.0)), (120, 30, dict(MOT, fuel=3.0, thr=30.0))], blank={"boost": (0, 10)})
g = DE.grid_from_csv_bytes(raw)
pub, fu = DE.detect(g, "PUB"), DE.detect(g, "FUEL")
assert len(pub) == 1 and len(fu) == 1 and pub[0]["t0_s"] == 120.0 and fu[0]["t0_s"] == 50.0 and not DE.overlaps(pub[0], fu[0]), (pub, fu)

# N03: nine unknown load seconds inside a 10 s motored segment are NOT low load; coverage reports the unknown seconds
raw = drive([(50, 10, MOT)], blank={"load": (50, 59)})
g = DE.grid_from_csv_bytes(raw)
assert DE.detect(g, "PUB") == [], DE.detect(g, "PUB")
cov = DE.unknown_coverage(g, "PUB")
assert cov["unknown_s"] >= 6 and cov["observed_s"] + cov["unknown_s"] == cov["grid_s"], cov
assert DE.detect(g, "FUEL")[0]["dur_s"] == 10                          # the fuel indicator does not use load and still sees the spin
assert DE.unknown_coverage(DE.grid_from_csv_bytes(drive([(50, 10, MOT)])), "PUB")["unknown_s"] == 0
assert DE.unknown_coverage(DE.grid_from_csv_bytes(drive([(50, 10, MOT)])), "FUEL")["grid_s"] > 0

# monitor: records carry the detector version and the unknown coverage; a legacy (unversioned) state is rebuilt without flags and the change is reported
mk = lambda f, d, t: dict(file=f, date=d, time_start="10:00:00.0", T_pack_mean_avg=t)
store = {"a.csv": drive([(50, 6, MOT), (76, 6, MOT)], drop_rows=set(range(56, 76))), "b.csv": drive([(50, 30, MOT)])}
dm = pd.DataFrame([mk("a.csv", "2026-07-01", 30.0), mk("b.csv", "2026-07-02", 31.0)])
with tempfile.TemporaryDirectory() as td:
    sp = os.path.join(td, "mon.json")
    legacy = DM.update(dm, lambda f: store.get(f), sp)
    assert legacy["detector_version"] == DE.DETECTOR_VERSION and all(r["detector_version"] == DE.DETECTOR_VERSION for r in legacy["drives"].values())
    assert legacy["drives"]["a.csv"]["unknown_s"]["PUB"] > 0 and legacy["summary"]["unknown_s_total"]["PUB"] > 0
    # simulate a pre-M400 state: remove the version marks and put in the old merged event for a.csv
    st = json.load(open(sp, encoding="utf-8"))
    st.pop("detector_version")
    for r in st["drives"].values():
        r.pop("detector_version", None); r.pop("unknown_s", None); r.pop("grid_s", None)
    st["drives"]["a.csv"]["pub_events"] = [{"t0_s": 0.0, "dur_s": 12, "rpm_mean": 2500.0, "rpm_slope_per_s": 0.0, "soc_mean": 65.0, "speed_mean": 50.0, "I_mean": 0.0,
                                            "fuel_mean": 0.0, "sustained": True}]
    json.dump(st, open(sp, "w", encoding="utf-8"))
    new = DM.update(dm, lambda f: store.get(f), sp)
    assert new["bootstrap"] is True and new["last_update"]["n_flags"] == 0 and new["detector_version"] == DE.DETECTOR_VERSION
    ch = new["detector_change"]
    assert ch["legacy_sustained_events"] == 2 and ch["new_sustained_events"] == 1 and ch["drives_with_changed_sustained"] == 1, ch
    # an up-to-date state is left alone
    again = DM.update(dm, lambda f: store.get(f), sp)
    assert again["detector_change"] == ch
print("OK test_dissipation_events_m400")
