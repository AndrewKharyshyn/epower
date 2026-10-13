"""M425: compute_summary_arrays._fixed_interval_self_transition (vectorised) equals the former pandas form (ser.where(ser >= 0).resample(...).apply(mode).dropna() + consecutive comparison) on synthetic
sequences (ties, invalid states, gaps, sub-second timestamps, midnight anchoring, all datetime units) and on the real corpus, where it also reproduces the published engineDwellSurvival.fixedIntervalSelfTransition."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import compute_summary_arrays as C


def reference(seq_all, window_s):
    """The pre-M425 implementation, verbatim."""
    same = total = 0
    for day, idx, st in seq_all:
        ser = pd.Series(st, index=idx)
        ser = ser.where(ser >= 0)
        resampled = ser.resample('%ds' % window_s).apply(lambda x: x.mode().iloc[0] if len(x.dropna()) else np.nan)
        vals = resampled.dropna().values
        for k in range(1, len(vals)):
            total += 1
            if vals[k] == vals[k - 1]:
                same += 1
    return {'windowS': window_s, 'nTransitionsObserved': total, 'selfTransitionRate': round(same / total, 4) if total else None}


rng = np.random.default_rng(425)
seqs = []
for i in range(40):
    n = int(rng.integers(30, 900))
    base = pd.Timestamp("1900-01-01 %02d:%02d:%02d" % (rng.integers(0, 24), rng.integers(0, 60), rng.integers(0, 60)))
    t = np.cumsum(rng.choice([1.0, 1.0, 1.0, 1.5, 0.4, 7.0], size=n))                     # 1 Hz with jitter and gaps
    idx = base + pd.to_timedelta(t, unit="s")
    st = rng.choice([-1, 0, 0, 1, 1, 2, 3], size=n).astype(np.int64)
    if i % 5 == 0:
        st[:] = rng.choice([0, 1], size=n)                                                  # two-state: many ties
    if i % 7 == 0:
        st[: n // 2] = -1                                                                   # long invalid stretch
    seqs.append(("d", pd.DatetimeIndex(idx).as_unit(["ns", "us", "ms", "s"][i % 4]) if i % 4 == 3 else pd.DatetimeIndex(idx).as_unit(["ns", "us", "ms"][i % 3]), st))
seqs.append(("d", pd.date_range("2026-06-01 23:59:00", periods=300, freq="s"), np.arange(300) % 3))   # crosses midnight
seqs.append(("d", pd.date_range("2026-06-01 10:00:00", periods=50, freq="s"), np.full(50, -1)))          # all invalid
for w in (1, 10, 30, 60, 120, 7):
    assert C._fixed_interval_self_transition(seqs, w) == reference(seqs, w), w
    for s in seqs[:6]:
        assert C._fixed_interval_self_transition([s], w) == reference([s], w), (w, s[1][0])

# real corpus: all drives, five windows; equals the reference and the published block
import drive_raw_cache as drc
dm = pd.read_csv("drive_master.csv", low_memory=False)
fl = drc.make_frame_loader()
real = []
for _, r in dm.iterrows():
    g = C._esm_grid(r['file'], None, fl)
    if g is None or 'rpm' not in g.columns:
        continue
    g = g.dropna(subset=['rpm'])
    if len(g) < 20:
        continue
    st = C._esm_classify(g['rpm'].values)
    if (st >= 0).sum() < 20:
        continue
    real.append((str(r.get('date', ''))[:10], g.index, st))
A = json.load(open("summary_arrays.json", encoding="utf-8"))
pub = {x['windowS']: x for x in A["engineDwellSurvival"]["fixedIntervalSelfTransition"]}
if len(real) >= 0.9 * len(dm):                  # the frame cache (raw_cache/) is not in the repository: CI runs without it and skips the real-corpus part (recorded in analyses/M425_equivalence.json)
    for w in (1, 10, 30, 60, 120):
        got = C._fixed_interval_self_transition(real, w)
        assert got == pub[w], (w, got, pub[w])
    for w in (30, 120):
        assert C._fixed_interval_self_transition(real, w) == reference(real, w), w
else:
    print("note: frame cache not available (%d of %d drives): real-corpus comparison skipped" % (len(real), len(dm)))
rec = json.load(open("analyses/M425_equivalence.json", encoding="utf-8"))
assert rec["fixedIntervalSelfTransition"]["equalToPublishedBlock"] is True and rec["fixedIntervalSelfTransition"]["sequences"] >= 550
print("OK test_fixed_interval_self_transition (%d synthetic + %d real sequences)" % (len(seqs), len(real)))
