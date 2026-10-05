"""M379b known-answer tests for tools/cadence_emulate.py (analyses/M379_spec.md Rev 2 P5 and Rev 3): thinning properties, keep-all identity through the CSV round trip,
GPS / time columns untouched, and a ramp and a step current signal with a known integral run through the real pipeline (analyze_bytes) at native and emulated cadence."""
import io, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import cadence_emulate as E

# ---- thinning properties ----
ts = np.arange(0.0, 600.0, 0.5)
rng = np.random.default_rng(1)
k = E.thin_column(ts, np.full(2000, 2.0), rng=rng)
assert k[0] == 0 and np.all(np.diff(k) > 0), "first sample kept, indices strictly increasing"
assert abs(np.diff(ts[k]).mean() - 2.0) < 0.05, "dithered thinning preserves the mean interval"
assert abs(np.median(np.diff(ts[E.thin_column(ts, np.full(2000, 2.0), rng=None)])) - 2.0) < 1e-9, "nearest variant on an aligned grid"
k3 = E.thin_column(ts, np.full(2000, 1.25), rng=np.random.default_rng(2))
assert abs(np.diff(ts[k3]).mean() - 1.25) < 0.05, "target between grid multiples: the mean is preserved"
assert np.array_equal(E.thin_column(ts, np.full(5, 9.0), keep_all=True), np.arange(len(ts)))
a1 = E.thin_column(ts, np.full(2000, 1.25), rng=np.random.default_rng(7)); a2 = E.thin_column(ts, np.full(2000, 1.25), rng=np.random.default_rng(7))
assert np.array_equal(a1, a2), "seeded: reproducible"

# ---- keep-all round trip and untouched columns on a small synthetic frame ----
rows = []
for i in range(400):
    rows.append({"time": "08:%02d:%06.3f" % (i // 60, i % 60 + 0.25), "[BMS] HV Battery Current (A)": (-1.5 * i if i % 2 == 0 else np.nan), "[BMS] HV Battery voltage (V)": (350.0 if i % 2 == 1 else np.nan),
                 "Latitude": 50.0 + i * 1e-5, "Longtitude": 30.0})
df = pd.DataFrame(rows)
b = df.to_csv(index=False, lineterminator="\n").encode("utf-8")
pools = {"[BMS] HV Battery Current (A)": np.full(500, 3.0), "[BMS] HV Battery voltage (V)": np.full(500, 3.0)}
out, rep = E.emulate(b, pools, np.random.default_rng(3), factor=1.0, keep_all=True)
assert out == b or pd.read_csv(io.BytesIO(out)).equals(pd.read_csv(io.BytesIO(b))), "keep-all round trip is the identity"
out2, rep2 = E.emulate(b, pools, np.random.default_rng(3), factor=1.0)
d2 = pd.read_csv(io.BytesIO(out2))
assert list(d2["Latitude"]) == list(df["Latitude"]) and list(d2["time"]) == list(df["time"]), "GPS and time untouched"
assert d2["[BMS] HV Battery Current (A)"].notna().sum() < df["[BMS] HV Battery Current (A)"].notna().sum(), "current column thinned"

# ---- ramp and step with a known integral through the pipeline ----
carrier = "raw/2026-09-02 07-53-16.csv"
if os.path.exists(carrier):
    import compute_drive_summary_v6 as C
    base = pd.read_csv(carrier, low_memory=False)
    icol, vcol = "[BMS] HV Battery Current (A)", "[BMS] HV Battery voltage (V)"
    t = pd.to_timedelta(base.iloc[:, 0]).dt.total_seconds().values
    mi, mv = base[icol].notna().values, base[vcol].notna().values
    t0, span = t[mi][0], t[mi][-1] - t[mi][0]
    slow = {c: np.full(2000, 1.4) for c in (icol, vcol)}

    def run(fn, thin):
        d = base.copy()
        d.loc[mi, icol] = -fn(t[mi] - t0)          # raw current is charge-positive: negative = discharge
        d.loc[mv, vcol] = 350.0
        bb = d.to_csv(index=False, lineterminator="\n").encode("utf-8")
        if thin:
            bb, _ = E.emulate(bb, slow, np.random.default_rng(5), factor=1.0)
        return C.analyze_bytes(bb, "synthetic.csv")["gross_discharge_kwh"]
    ramp, step = (lambda x: 0.5 * x), (lambda x: np.where(x > span / 2, 100.0, 0.0))
    exact_ramp = 350.0 * 0.5 * span ** 2 / 2.0 / 3.6e6
    exact_step = 350.0 * 100.0 * (span / 2.0) / 3.6e6
    assert abs(run(ramp, False) / exact_ramp - 1.0) < 1e-3, "pipeline integrates a ramp exactly at the native cadence"
    assert abs(run(step, False) / exact_step - 1.0) < 5e-3, "pipeline integrates a step at the native cadence"
    assert abs(run(ramp, True) / exact_ramp - 1.0) < 5e-3, "thinning does not bias a linear signal"
    assert abs(run(step, True) / exact_step - 1.0) < 1.5e-2, "thinning moves a step integral by about one interval over the span"
print("test_cadence_emulate: OK")
