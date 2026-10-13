"""M425: _engine_start_scan and the three functions that use it (_buffer_impulse_events, _ramp_latency_events, _engine_start_triggers) return exactly what the pre-M425 functions returned
(tests/synthetic/reference/compute_summary_arrays_pre_m425.py, verbatim): on synthetic frames with sustained-off restarts, too-short offs, ramps with plateaus, impulses, gaps, unsorted and duplicated time
stamps (the non-searchsorted fallback), and on every 14th real drive. The full-corpus comparison (554 frames, all three functions, no mismatch) is recorded in analyses/M425_equivalence.json."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import compute_summary_arrays as C

ns = dict(C.__dict__)
exec(compile(open(os.path.join(ROOT, "tests", "synthetic", "reference", "compute_summary_arrays_pre_m425.py"), encoding="utf-8").read(), "pre_m425", "exec"), ns)
OLD = {k: ns[k] for k in ("_buffer_impulse_events", "_ramp_latency_events", "_engine_start_triggers")}
canon = lambda o: json.dumps(o, sort_keys=True, default=str)


def synth(seed, unsorted=False, dup=False):
    rng = np.random.default_rng(seed)
    t, rpm, cur, vol = [], [], [], []
    clock = pd.Timestamp("2026-06-01 08:00:00")
    for cycle in range(int(rng.integers(3, 8))):
        off = int(rng.choice([1, 2, 5, 20, 60]))                       # 1-2 s offs are too short to count as sustained
        for _ in range(off):
            clock += pd.Timedelta(seconds=float(rng.choice([1.0, 1.0, 1.0, 2.5])))
            t.append(clock); rpm.append(float(rng.choice([0, 0, 50, 100]))); cur.append(float(rng.normal(-5, 0.5))); vol.append(float(rng.normal(360, 2)))
        level = float(rng.choice([900, 1200]))
        for seg in range(int(rng.integers(2, 6))):
            for _ in range(int(rng.integers(2, 40))):
                clock += pd.Timedelta(seconds=1)
                t.append(clock); rpm.append(level + float(rng.normal(0, 20))); cur.append(float(rng.normal(-5 - (8 if seg == 0 else 0), 2))); vol.append(float(rng.normal(355, 3)))
            level = float(rng.choice([1500, 2100, 2700, 900]))
        if rng.random() < 0.3:
            clock += pd.Timedelta(seconds=30)                              # a logging gap
    fr = pd.DataFrame({"time": pd.DatetimeIndex(t), C._BUFIMP_RPM_COL: rpm, C._BUFIMP_I_COL: cur, C._BUFIMP_V_COL: vol, C._RAMPLAT_SPD_COL: rng.uniform(0, 100, len(t))})
    if unsorted:
        idx = np.arange(len(fr)); k = int(rng.integers(5, len(fr) - 5)); idx[k], idx[k + 3] = idx[k + 3], idx[k]
        fr = fr.iloc[idx].reset_index(drop=True)
    if dup:
        fr.loc[fr.index[len(fr) // 2], "time"] = fr.loc[fr.index[len(fr) // 2 - 1], "time"]
    return fr


frames = [synth(s) for s in range(30)] + [synth(100 + s, unsorted=True) for s in range(6)] + [synth(200 + s, dup=True) for s in range(4)]
n_events = 0
for i, fr in enumerate(frames):
    for name, old in OLD.items():
        a, b = old(fr), getattr(C, name)(fr)
        assert canon(a) == canon(b), (name, i)
        if name == "_ramp_latency_events":
            n_events += len(a)
assert n_events > 20, "the synthetic frames must contain detectable events (%d)" % n_events
# edge frames
for name, old in OLD.items():
    for fr in (None, frames[0].iloc[:1], frames[0].drop(columns=[C._BUFIMP_I_COL])):
        assert canon(old(fr)) == canon(getattr(C, name)(fr)), name
# the scan itself: the sustained-off rule
rp = pd.DataFrame({"time": pd.date_range("2026-06-01", periods=12, freq="s"), "rpm": [0, 0, 0, 0, 900, 900, 0, 900, 0, 0, 0, 1000.0]})
assert [(i, str(t)[-8:]) for i, t in C._engine_start_scan(rp)] == [(4, "00:00:04"), (11, "00:00:11")], C._engine_start_scan(rp)   # the start at row 7 follows a 1-row off: no event

# real frames: every 14th drive
import drive_raw_cache as drc
dm = pd.read_csv("drive_master.csv", low_memory=False)
fl = drc.make_frame_loader()
n = 0
for f in dm["file"].iloc[::14]:
    fr = fl(f)
    if fr is None:
        continue
    n += 1
    for name, old in OLD.items():
        assert canon(old(fr)) == canon(getattr(C, name)(fr)), (name, f)
rec = json.load(open("analyses/M425_equivalence.json", encoding="utf-8"))
assert rec["mismatches"] == {} and rec["framesCompared"] >= 550
print("OK test_start_event_scan (%d synthetic frames, %d events, %d real frames)" % (len(frames), n_events, n))
