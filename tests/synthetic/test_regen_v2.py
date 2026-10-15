"""M441 known-answer tests of the interval extractor v2 (spec analyses/M441_spec.md Rev 2.1, section 6 + 9 + 10; criteria declared there before any result): tools/regen_v2.py.
(1) hand-calculated KE and charge incl. a zero crossing; (3) zero-charge interval stays in the denominator; (4) missing/stale RPM, current, probes, SOC -> declared exclusion or NaN attribute, never a fabricated value;
(5) a timestamp gap is not turned into an interval; (6) SOC / speed-bin boundaries and the overflow bin; (7) a deceleration over several samples = atomic intervals whose sums equal the whole;
(8) ratio of sums; (10a) exact cadence invariance (1.0 / 1.4 / 2.6 s, tolerance 1e-9); (10b) realistic cadence invariance (0.5 pp) and the legacy contrast (>= 2.5 pp);
(12) ambient temperature plays no role; plateau handling (B1/R2) and per-channel decimation (R1)."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import compute_summary_arrays as C
import regen_v2 as R

SP, RPM, I_, V_ = "[VCM] Vehicle Speed (km/h)", "Оберти двигуна (rpm)", "[BMS] HV Battery Current (A)", "[BMS] HV Battery voltage (V)"
SOC = "[BMS] HV State of charge (%)"
TC = ["[BMS] HV Battery Temperature Sensor %d (℃)" % k for k in (1, 2, 3, 4)]
T0 = pd.Timestamp("2026-03-01 10:00:00")
MASS = C.MASS_URBAN_MIXED_KG


def frame(sec, speed, rpm=0.0, cur=0.0, volt=360.0, soc=60.0, temps=(30.0,) * 4):
    sec = np.asarray(sec, float); n = len(sec)
    full = lambda x: np.full(n, x, float) if np.isscalar(x) else np.asarray(x, float)
    d = {"time": T0 + pd.to_timedelta(sec, unit="s"), SP: full(speed), RPM: full(rpm), I_: full(cur), V_: full(volt), SOC: full(soc)}
    for c, t in zip(TC, temps):
        d[c] = np.full(n, np.nan if t is None else t)
    return pd.DataFrame(d)


def run(df, **kw):
    return R.extract_drive(df, C=C, i_off=None, **kw)


def totals(res, mass=MASS, with_trimmed=False):
    iv = res["intervals"]
    if iv is None:
        return 0.0, 0.0, 0
    m = np.ones(len(iv["t0"]), bool) if with_trimmed else ~iv["trimmed"]
    ke = R.KE_FACTOR * mass * iv["dv2"][m]
    return float(ke.sum()), float(iv["charge"][m].sum()), int(m.sum())


ke_of = lambda v0, v1: R.KE_FACTOR * MASS * (v0 ** 2 - v1 ** 2)

# ---- (1) hand calculation: 1 Hz, engine off, 50 -> 40 -> 30 -> 20 km/h, current 20 A constant, then a ramp +20 -> -20 A over one interval (zero crossing at its midpoint)
sec = np.arange(0, 6)
r = run(frame(sec, [50, 50, 40, 30, 20, 20], cur=[20, 20, 20, 20, 20, 20]))
ke, ch, n = totals(r)
assert n == 3 and abs(ke - (ke_of(50, 40) + ke_of(40, 30) + ke_of(30, 20))) < 1e-15
assert abs(ch - 3 * 20 * 360 / 1000 / 3600) < 1e-15, ch                       # 3 s of 7.2 kW; the leading and the trailing plateau interval are trimmed
tr = totals(r, with_trimmed=True)
assert tr[2] == 5 and abs(tr[1] - 5 * 20 * 360 / 1000 / 3600) < 1e-15            # the trimmed plateaus carry charge but are reported apart, not in the estimator
r = run(frame([0, 1, 2], [30, 20, 10], cur=[-20, 20, -20]))                    # two intervals, each a ramp through zero: charge = half the interval at a mean of 10 A
assert abs(totals(r)[1] - 2 * (0.5 * 10 * 360 / 1000 / 3600)) < 1e-12, totals(r)

# ---- (3) a valid zero-charge deceleration stays in the denominator and lowers the pooled ratio
r = run(frame([0, 1, 2], [30, 20, 10], cur=[-5, -5, -5]))
assert totals(r)[1] == 0.0 and totals(r)[0] > 0
assert r["intervals"]["charge"].sum() == 0

# ---- (4) exclusions, never a fabricated value
d = frame(np.arange(5), [40, 30, 20, 10, 5]); d[RPM] = np.nan                    # no RPM channel at all: unknown is never off
r = run(d); assert r["intervals"] is None and r["counts"]["rpmUnknown"] == 4
d = frame(np.arange(5), [40, 30, 20, 10, 5]); d.loc[2, RPM] = 1500               # a native engine-on sample inside
r = run(d); assert r["counts"]["engineOn"] == 2 and r["intervals"] is not None and totals(r)[2] == 2
d = frame(np.arange(5), [40, 30, 20, 10, 5]); d[I_] = np.nan; d.loc[[0, 4], I_] = 10.0   # current bracketed by samples 4 s apart (<= 5 s): supported by interpolation
r = run(d); assert totals(r)[2] == 4
d = frame(np.arange(5), [40, 30, 20, 10, 5]); d[I_] = np.nan; d.loc[0, I_] = 10.0
r = run(d); assert r["intervals"] is None and r["counts"]["currentOrVoltageUnsupported"] == 4
d = frame(np.arange(0, 40, 8), [40, 30, 20, 10, 5]); r = run(d); assert r["intervals"] is None and r["counts"]["speedGap"] == 4       # 8 s apart: gaps, never bridged
d = frame(np.arange(5), [40, 30, 20, 10, 5], temps=(30, 30, 30, None)); r = run(d)
assert np.isnan(r["intervals"]["tpack"]).all() and (r["intervals"]["nprobe"] == 3).all() and totals(r)[2] == 4                               # a missing probe: attribute NaN, interval kept
d = frame(np.arange(5), [40, 30, 20, 10, 5], soc=np.nan); r = run(d)
assert np.isnan(r["intervals"]["soc"]).all() and totals(r)[2] == 4
d = frame(np.arange(5), [40, 30, 20, 10, 5], soc=[101, 101, 101, 101, 101]); r = run(d)
assert np.isnan(r["intervals"]["soc"]).all()                                                                                                 # outside 0-100 is invalid, dropped before the lookup
d = frame(np.arange(14), np.linspace(90, 5, 14), soc=np.nan); d.loc[0, SOC] = 60.0; r = run(d)
soc_ = r["intervals"]["soc"]; assert (soc_[:11] == 60.0).all() and np.isnan(soc_[11:]).all()                                                  # age <= 10 s is used, 11 s is not

# ---- (5) a gap does not create an interval and does not duplicate energy
d = frame([0, 1, 2, 12, 13, 14], [50, 40, 30, 30, 20, 10], cur=15.0); r = run(d)
assert r["counts"]["speedGap"] == 1 and totals(r)[2] == 4 and totals(r, with_trimmed=True)[2] == 4

# ---- (6) speed-bin boundaries and the overflow row (slices by mid-point speed)
r = run(frame([0, 1, 2], [140, 130, 120], cur=10.0))
b = r["bins"]["dv2"]; assert b[:, 13].sum() > 0 and b[:, 12].sum() > 0 and abs(b.sum() - (140 ** 2 - 120 ** 2)) < 1e-9
r = run(frame([0, 1, 2], [30, 20, 10], cur=10.0))                                                                                            # edges 30/20/10 exactly on interval ends: slices in the right bins
b = r["bins"]["dv2"]; assert b[0, 2] > 0 and b[0, 1] == 0 and b[1, 1] > 0 and b[1, 0] == 0
assert r["bins"]["touch"][0, 2] == 1 and r["bins"]["touch"][0, 1] == 0

# ---- (7) several samples = atomic intervals; the sums equal the whole
sp = [60, 55, 52, 40, 31, 20, 11]
r = run(frame(np.arange(7), sp, cur=12.0))
assert totals(r)[2] == 6 and abs(totals(r)[0] - ke_of(60, 11)) < 1e-12 and abs(totals(r)[1] - 6 * 12 * 360 / 1000 / 3600) < 1e-12

# ---- plateau handling (B1/R2): an inner plateau enters with KE 0 and its charge; leading/trailing plateaus are trimmed and counted
r = run(frame(np.arange(7), [50, 50, 40, 40, 30, 30, 30], cur=10.0))
iv = r["intervals"]
assert list(iv["trimmed"]) == [True, False, False, False, True, True] and abs(totals(r)[1] - 3 * 10 * 0.36 / 3600) < 1e-15 and abs(totals(r)[0] - ke_of(50, 30)) < 1e-12
# a speed increase ends the episode
r = run(frame(np.arange(6), [50, 40, 45, 35, 30, 30], cur=10.0)); assert r["counts"]["notDecelOrFlat"] == 1 and totals(r)[2] == 3

# ---- (8) pooled recovery is a ratio of sums on unequal-KE intervals
r = run(frame([0, 1, 2], [100, 90, 20], cur=[30, 30, -5]))
ke, ch, n = totals(r); iv = r["intervals"]
pooled = ch / ke; mean_of_ratios = np.mean(iv["charge"] / (R.KE_FACTOR * MASS * iv["dv2"]))
assert abs(pooled - mean_of_ratios) > 1e-3 and abs(pooled - iv["charge"].sum() / (R.KE_FACTOR * MASS * iv["dv2"].sum())) < 1e-15

# ---- (10a) exact cadence invariance: linear speed, constant I and V, bin-edge crossings on shared sub-grid nodes (R5)
def linear(dt, dur=91.0):
    t = np.round(np.arange(int(round(dur / dt)) + 1) * dt, 9)
    return frame(t, 100.0 - 1.0 * t, cur=18.0, volt=360.0)

res = [run(linear(dt)) for dt in (1.0, 1.4, 2.6)]
ref = res[0]["bins"]
# the three runs end at different last samples (91 is not a multiple of 1.4 or 2.6 apart from 91 = 65 x 1.4 = 35 x 2.6): all end exactly at 91 s
for x in res[1:]:
    for k in ("dv2", "charge"):
        a, bsum = ref[k].sum(axis=0), x["bins"][k].sum(axis=0)
        assert np.allclose(a, bsum, rtol=1e-9, atol=1e-12), (k, a, bsum)
    assert abs(totals(x)[1] / totals(x)[0] - totals(res[0])[1] / totals(res[0])[0]) < 1e-9 * 100

# ---- (10b) realistic: smooth deceleration, 1 km/h speed quantization, current quantization, jittered dt (seed 42); legacy contrast
def realistic(dt, seed=42, dur=90.0):
    rng = np.random.default_rng(seed)
    t = np.cumsum(np.r_[0.0, dt * (1 + 0.1 * rng.uniform(-1, 1, int(dur / dt) + 5))]); t = t[t <= dur]
    v = np.round(100.0 * np.exp(-t / 45.0))                                         # smooth 100 -> 14 km/h, quantized to 1 km/h
    cur = np.round(15.0 + 5.0 * np.sin(2 * np.pi * t / 20.0), 1)
    volt = np.round(360.0 + 2 * np.sin(t / 7.0), 0)
    return frame(t, v, cur=cur, volt=volt)

rr = {dt: run(realistic(dt)) for dt in (1.0, 1.4, 2.6)}
rec = {dt: 100 * totals(x)[1] / totals(x)[0] for dt, x in rr.items()}
spread = max(rec.values()) - min(rec.values())
assert spread <= 0.5, ("v2 cadence spread (pp)", rec)
# the legacy rule on the same trajectories (M440 replication of the capture block)
import m440_regen_sens as X
leg = {}
for dt in (1.0, 1.4, 2.6):
    st = X.extract_drive(realistic(dt), "urban", "k.csv", "2026-03-01", C=C)
    leg[dt] = 100 * st["cap"].sum() / st["ke"].sum() if len(st) else float("nan")
lspread = max(leg.values()) - min(leg.values())
assert lspread >= 2.5, ("legacy contrast (pp)", leg)

# ---- (12) ambient temperature is not an input: a frame with a wildly varying ambient column gives identical output
d = frame(np.arange(8), [70, 60, 50, 42, 33, 25, 17, 9], cur=11.0)
d["[BMS] HV Battery Intake Air Temperature (℃)"] = np.linspace(-30, 40, 8)
a, b2 = run(d), run(frame(np.arange(8), [70, 60, 50, 42, 33, 25, 17, 9], cur=11.0))
assert np.array_equal(a["intervals"]["charge"], b2["intervals"]["charge"]) and np.array_equal(a["intervals"]["tpack"], b2["intervals"]["tpack"])

# ---- (R1) per-channel decimation keeps every 2nd native sample of every channel; both phases run and the cadence record doubles
d = frame(np.arange(0, 40, 1.0), np.linspace(80, 10, 40), cur=15.0)
f, e0, e1 = run(d), run(d, decimate=0), run(d, decimate=1)
assert abs(e0["cadence"]["speedDtMed"] - 2.0) < 1e-9 and abs(e1["cadence"]["speedDtMed"] - 2.0) < 1e-9 and abs(f["cadence"]["speedDtMed"] - 1.0) < 1e-9
assert abs(totals(e0)[0] - totals(f)[0]) / totals(f)[0] < 0.05

# ---- lag sensitivity: shifting I/V times by +1 s changes the charge (edge intervals can lose their bracket)
a = run(frame(np.arange(8), [70, 60, 50, 42, 33, 25, 17, 9], cur=[0, 0, 10, 20, 30, 20, 10, 0])); b3 = run(frame(np.arange(8), [70, 60, 50, 42, 33, 25, 17, 9], cur=[0, 0, 10, 20, 30, 20, 10, 0]), iv_lag_s=1.0)
assert totals(b3)[2] >= 5 and totals(a)[1] != totals(b3)[1]      # a shift can drop edge intervals whose I/V bracket is lost; the kept ones keep their KE

print("test_regen_v2: ALL PASSED", {"cadence10b_pp": round(spread, 3), "legacy_contrast_pp": round(lspread, 3), "legacy": {k: round(v, 2) for k, v in leg.items()}, "v2": {k: round(v, 2) for k, v in rec.items()}})
