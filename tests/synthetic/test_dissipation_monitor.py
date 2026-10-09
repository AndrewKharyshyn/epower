"""M394 known-answer tests: unfuelled-spin event detection (PUB / FUEL), sustained vs transient, and the report-only monitor flags (analyses/M394_spec.md)."""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
import numpy as np, pandas as pd
import dissipation_events as DE
import dissipation_monitor as DM

C = {v: k for k, v in DE.COLS.items()}


def drive(segments, with_fuel=True, with_boost=True, n=200):
    """segments: list of (start_s, dur_s, dict) overriding the base (fuelled generation at 1800 rpm) values; 1 Hz rows."""
    base = {"rpm": 1800.0, "boost": 0.05, "load": 40.0, "soc": 65.0, "fuel": 3.0, "thr": 30.0, "speed": 50.0, "I": 0.0}
    rows = []
    for t in range(n):
        r = dict(base)
        for s, d, ov in segments:
            if s <= t < s + d:
                r.update(ov)
        rows.append(r)
    df = pd.DataFrame(rows)
    out = pd.DataFrame({"time": [f"{t // 3600:02d}:{(t // 60) % 60:02d}:{t % 60:02d}.000" for t in range(n)]})
    for k, col in C.items():
        if (k == "fuel" or k == "thr") and not with_fuel:
            continue
        if k == "boost" and not with_boost:
            continue
        out[col] = df[k]
    return out.to_csv(index=False).encode("utf-8")


MOT = {"rpm": 2500.0, "boost": -0.80, "load": 5.0, "fuel": 0.0, "thr": 2.0}

# 1. a 30 s steady unfuelled spin is a sustained event for both detectors
g = DE.grid_from_csv_bytes(drive([(50, 30, dict(MOT, soc=60.0))]))
pub, fu = DE.detect(g, "PUB"), DE.detect(g, "FUEL")
assert len(pub) == 1 and pub[0]["sustained"] and pub[0]["dur_s"] == 30 and abs(pub[0]["soc_mean"] - 60.0) < 1e-6 and abs(pub[0]["rpm_mean"] - 2500.0) < 1e-6
assert len(fu) == 1 and fu[0]["sustained"] and DE.overlaps(pub[0], fu[0])
# 2. an engine spin-down / start ramp is an event but NOT sustained (falling rpm), a short blip is not sustained
ramp = [(60 + i, 1, dict(MOT, rpm=2400.0 - 150.0 * i, boost=-0.8)) for i in range(12)]
g2 = DE.grid_from_csv_bytes(drive(ramp))
ev = DE.detect(g2, "FUEL")
assert ev and all(not e["sustained"] for e in ev) and ev[0]["rpm_slope_per_s"] < -30
assert DE.detect(DE.grid_from_csv_bytes(drive([(50, 5, MOT)])), "PUB")[0]["sustained"] is False
assert DE.detect(DE.grid_from_csv_bytes(drive([(50, 2, MOT)])), "PUB") == []                         # < 3 s: no event
# 3. normal fuelled low-load generation at the 1500 rpm floor is NOT an event (rpm gate + fuel > 0)
assert DE.detect(DE.grid_from_csv_bytes(drive([(50, 40, {"rpm": 1500.0, "boost": -0.75, "load": 6.0, "fuel": 1.2, "thr": 12.0})])), "FUEL") == []
assert DE.detect(DE.grid_from_csv_bytes(drive([(50, 40, {"rpm": 1500.0, "boost": -0.75, "load": 6.0})])), "PUB") == []
# 4. missing channels -> not evaluable (None), never an empty pass
assert DE.detect(DE.grid_from_csv_bytes(drive([(50, 30, MOT)], with_fuel=False)), "FUEL") is None
assert DE.detect(DE.grid_from_csv_bytes(drive([(50, 30, MOT)], with_boost=False)), "PUB") is None

# 5. monitor flags
mk = lambda f, d, t: dict(file=f, date=d, time_start="10:00:00.0", T_pack_mean_avg=t)
warm = mk("w1.csv", "2026-07-01", 30.0)
store = {"w1.csv": drive([(50, 30, dict(MOT, soc=80.0))])}
dm0 = pd.DataFrame([warm])
with tempfile.TemporaryDirectory() as td:
    sp = os.path.join(td, "mon.json")
    out = DM.update(dm0, lambda f: store.get(f), sp)
    assert out["bootstrap"] is True and out["last_update"]["flags"] == [] and out["summary"]["n_sustained_events"] == 1
    assert ">=25C" not in out["summary"]["validation_gap_bands_without_sustained_event"] and "<5C" in out["summary"]["validation_gap_bands_without_sustained_event"]
    # idempotent: same drives again -> no new drives, no flags, identical file content
    before = open(sp, encoding="utf-8").read()
    out = DM.update(dm0, lambda f: store.get(f), sp)
    assert out["last_update"]["n_new_drives"] == 1 and out["bootstrap"] is True and open(sp, encoding="utf-8").read() == before   # unchanged state returned, file untouched
    # a cold drive (3 C) with a low-SoC sustained event: first_sustained_in_band + below_baseline_soc
    store["c1.csv"] = drive([(50, 40, dict(MOT, soc=55.0))])
    dm1 = pd.DataFrame([warm, mk("c1.csv", "2026-12-15", 3.0)])
    out = DM.update(dm1, lambda f: store.get(f), sp)
    kinds = sorted(x["flag"] for x in out["last_update"]["flags"])
    assert kinds == ["below_baseline_soc", "first_sustained_in_band"], kinds
    fb = [x for x in out["last_update"]["flags"] if x["flag"] == "first_sustained_in_band"][0]
    assert fb["band"] == "<5C" and out["last_update"]["n_flags"] == 2
    # a second cold event in the same band raises nothing new about the band
    store["c2.csv"] = drive([(50, 40, dict(MOT, soc=58.0))])
    out = DM.update(pd.DataFrame([warm, mk("c1.csv", "2026-12-15", 3.0), mk("c2.csv", "2026-12-16", 2.0)]), lambda f: store.get(f), sp)
    assert not [x for x in out["last_update"]["flags"] if x["flag"] == "first_sustained_in_band"]
    assert sorted(x["flag"] for x in out["flag_history"]) == ["below_baseline_soc", "first_sustained_in_band"]          # earlier flags survive later ingestions
    # a rerun without new drives must not erase the last run's flags
    keep = open(sp, encoding="utf-8").read()
    DM.update(pd.DataFrame([warm, mk("c1.csv", "2026-12-15", 3.0), mk("c2.csv", "2026-12-16", 2.0)]), lambda f: store.get(f), sp)
    assert open(sp, encoding="utf-8").read() == keep
    # fuel-confirmed event the census misses (load 12 %, above the 8 % gate): detector gap
    store["g1.csv"] = drive([(50, 40, dict(MOT, load=12.0, soc=79.0))])
    out = DM.update(pd.DataFrame([warm, mk("c1.csv", "2026-12-15", 3.0), mk("c2.csv", "2026-12-16", 2.0), mk("g1.csv", "2026-12-17", 28.0)]), lambda f: store.get(f), sp)
    assert [x["flag"] for x in out["last_update"]["flags"]] == ["fuel_event_not_in_census"], out["last_update"]["flags"]
    # census event with a logged fuel rate (5 L/h): not fuel confirmed
    store["u1.csv"] = drive([(50, 40, dict(MOT, fuel=5.0, thr=20.0, soc=79.0))])
    out = DM.update(pd.DataFrame([warm, mk("c1.csv", "2026-12-15", 3.0), mk("c2.csv", "2026-12-16", 2.0), mk("g1.csv", "2026-12-17", 28.0), mk("u1.csv", "2026-12-18", 28.0)]), lambda f: store.get(f), sp)
    assert [x["flag"] for x in out["last_update"]["flags"]] == ["census_event_not_fuel_confirmed"], out["last_update"]["flags"]
    # a drive without the census channels: channel_gap (not evaluable), never a silent pass
    store["n1.csv"] = drive([(50, 40, MOT)], with_boost=False)
    out = DM.update(pd.DataFrame([warm, mk("n1.csv", "2026-12-19", 5.0)]), lambda f: store.get(f), os.path.join(td, "mon2.json"))
    out = DM.update(pd.DataFrame([warm, mk("n1.csv", "2026-12-19", 5.0), mk("n2.csv", "2026-12-20", 5.0)]), lambda f: store.setdefault("n2.csv", drive([(50, 40, MOT)], with_boost=False)), os.path.join(td, "mon2.json"))
    assert "channel_gap" in [x["flag"] for x in out["last_update"]["flags"]]
# 6. audit M394: backfill ordering, unknown temperature, error isolation, missing raw file, fuel unknown, band stays at first recording
with tempfile.TemporaryDirectory() as td:
    sp = os.path.join(td, "mon3.json")
    st = {"late.csv": drive([(50, 30, dict(MOT, soc=80.0))]), "old.csv": drive([(50, 30, dict(MOT, soc=80.0))]), "ok.csv": drive([(50, 30, dict(MOT, soc=80.0))])}
    DM.update(pd.DataFrame([mk("late.csv", "2026-12-20", 3.0)]), lambda f: st.get(f), sp)                      # bootstrap: a cold event in December
    # a backfilled OLDER cold drive has no earlier sustained event in its band, although a later one is already recorded
    out = DM.update(pd.DataFrame([mk("late.csv", "2026-12-20", 3.0), mk("old.csv", "2026-06-01", 4.0)]), lambda f: st.get(f), sp)
    assert [x["flag"] for x in out["last_update"]["flags"]] == ["first_sustained_in_band"] and out["last_update"]["flags"][0]["file"] == "old.csv"
    # unknown pack temperature: its own flag, never a band flag
    st["nan.csv"] = drive([(50, 30, dict(MOT, soc=80.0))])
    out = DM.update(pd.DataFrame([mk("late.csv", "2026-12-20", 3.0), mk("old.csv", "2026-06-01", 4.0), mk("nan.csv", "2026-12-21", float("nan"))]), lambda f: st.get(f), sp)
    assert [x["flag"] for x in out["last_update"]["flags"]] == ["sustained_event_unknown_temperature"]
    # one unreadable file does not stop the batch: read_error flag, not recorded, the good drive after it is recorded; a missing raw file is an info flag
    st["bad.csv"] = bytes([0, 255, 254]) + b" not a csv"
    base = [mk("late.csv", "2026-12-20", 3.0), mk("old.csv", "2026-06-01", 4.0), mk("nan.csv", "2026-12-21", float("nan"))]
    out = DM.update(pd.DataFrame(base + [mk("bad.csv", "2026-12-22", 10.0), mk("ok.csv", "2026-12-23", 12.0), mk("gone.csv", "2026-12-24", 12.0)]), lambda f: st.get(f), sp)
    kinds = sorted(x["flag"] for x in out["last_update"]["flags"])
    assert "read_error" in kinds and "raw_file_missing" in kinds and "bad.csv" not in out["drives"] and "ok.csv" in out["drives"] and "gone.csv" not in out["drives"], kinds
    n_hist = sum(1 for h in out["flag_history"] if h["flag"] == "read_error")
    out = DM.update(pd.DataFrame(base + [mk("bad.csv", "2026-12-22", 10.0), mk("ok.csv", "2026-12-23", 12.0), mk("gone.csv", "2026-12-24", 12.0)]), lambda f: st.get(f), sp)
    assert sum(1 for h in out["flag_history"] if h["flag"] == "read_error") == n_hist == 1                    # a persistent read_error is recorded once
    # a recorded drive keeps the band of its first recording
    out = DM.update(pd.DataFrame([mk("late.csv", "2026-12-20", 30.0)] + base[1:] + [mk("ok.csv", "2026-12-23", 12.0)]), lambda f: st.get(f), sp)
    assert out["drives"]["late.csv"]["band"] == "<5C"
    # census event whose fuel channel is NaN inside the event on a fuel-capable drive: info flag, not a false positive
    raw = pd.read_csv(__import__("io").BytesIO(drive([(50, 30, dict(MOT, soc=80.0))])))
    raw.loc[40:90, C["fuel"]] = np.nan                                                                     # longer than the 3 s forward fill of the grid
    st["fnan.csv"] = raw.to_csv(index=False).encode("utf-8")
    out = DM.update(pd.DataFrame(base + [mk("bad.csv", "2026-12-22", 10.0), mk("ok.csv", "2026-12-23", 12.0), mk("fnan.csv", "2026-12-25", 12.0)]), lambda f: st.get(f), sp)
    fk = [x["flag"] for x in out["last_update"]["flags"] if x["file"] == "fnan.csv"]
    assert "census_event_fuel_unknown" in fk and "census_event_not_fuel_confirmed" not in fk, fk
# 7. re-check M394: main() never raises (unreadable state file -> monitor_error, exit 0, state untouched); read_error history dedup is per file, not per message
import contextlib, io as _io
with tempfile.TemporaryDirectory() as td:
    bad = os.path.join(td, "broken.json")
    open(bad, "w", encoding="utf-8").write("{ not json")
    buf = _io.StringIO()
    old_argv = sys.argv
    sys.argv = ["dissipation_monitor.py", "update", "--state", bad]
    try:
        with contextlib.redirect_stdout(buf):
            rc = DM.main()
    finally:
        sys.argv = old_argv
    assert rc == 0 and "monitor_error" in buf.getvalue() and open(bad, encoding="utf-8").read() == "{ not json"
    sp = os.path.join(td, "m.json")
    st = {"ok.csv": drive([(50, 30, dict(MOT, soc=80.0))])}
    DM.update(pd.DataFrame([mk("ok.csv", "2026-07-01", 30.0)]), lambda f: st.get(f), sp)
    bad_dm = pd.DataFrame([mk("ok.csv", "2026-07-01", 30.0), mk("x.csv", "2026-07-02", 20.0)])
    for payload in (bytes([0, 255]) + b" a", bytes([0, 254, 1]) + b" b different message text"):
        st["x.csv"] = payload
        out = DM.update(bad_dm, lambda f: st.get(f), sp)
    assert sum(1 for h in out["flag_history"] if h["flag"] == "read_error") == 1
print("OK dissipation monitor: PUB / FUEL detectors, sustained vs transient, flags, idempotence, not-evaluable")
