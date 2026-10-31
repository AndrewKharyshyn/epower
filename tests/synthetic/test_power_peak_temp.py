"""M550 (analyses/M550_spec.md Rev 3): known-answer tests for tools/power_peak_temp.py on synthetic frames (the master's own helpers D._series / D._asof)."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import power_peak_temp as P

T0 = pd.Timestamp("2026-01-01 08:00:00")

def drive(i_samples, v_samples, t1_samples):
    """each argument: list of (seconds, value); returns (df, t) as D._prep_bytes would for these native PID samples."""
    rows = [(s, "I", v) for s, v in i_samples] + [(s, "V", v) for s, v in v_samples] + [(s, "T1", v) for s, v in t1_samples]
    rows.sort(key=lambda r: r[0])
    t = pd.Series([T0 + pd.Timedelta(seconds=r[0]) for r in rows])
    df = pd.DataFrame({c: [r[2] if r[1] == c else np.nan for r in rows] for c in ("I", "V", "T1")})
    return df, t

# KA1 (audit acceptance): current peak at 15 C, power peak at 35 C, at different moments
I = [(s, 0.0) for s in range(0, 31)]; V = [(s, 350.0) for s in range(0, 31)]
I[10] = (10, 100.0); V[10] = (10, 300.0)        # Id = -100 A, P = -30 kW (peak current)
I[20] = (20, 90.0); V[20] = (20, 400.0)         # Id = -90 A, P = -36 kW (peak power)
T1 = [(s + 0.2, 15.0 if s < 15 else 35.0) for s in range(0, 31)]
r = P.extract_frames(*drive(I, V, T1))
assert r["ok"] and r["peakKwRebuilt"] == -36.0 and r["peakIRebuilt"] == -100.0
assert r["T1AtPeakKw"] == 35.0 and r["T1AtPeakI"] == 15.0, (r["T1AtPeakKw"], r["T1AtPeakI"])
assert P._cls(r["ageKwS"]) == "cotimed" and abs(r["ageKwS"] - 0.2) < 1e-6 and abs(r["gapS"] - 10.0) < 1e-6 and r["channelI"] == "reg"

# KA4: two exactly equal power minima -> the earlier sample, tie reported
I2 = [(s, 0.0) for s in range(0, 31)]; V2 = [(s, 350.0) for s in range(0, 31)]
for s, tv in ((8, 15.0), (18, 35.0)):
    I2[s] = (s, 80.0); V2[s] = (s, 400.0)
T2 = [(s, 15.0 if s < 13 else 35.0) for s in range(0, 31)]
r = P.extract_frames(*drive(I2, V2, T2))
assert r["nTiesAtMinP"] == 2 and r["T1AtPeakKw"] == 15.0 and r["t1TiedRange"] == [15.0, 35.0]

# KA5: tier edges, no interpolation (T1 only at one moment, 2.5 s / 3.5 s / 12 s from the peak sample at t = 20)
for off, tier in ((2.5, "nearby"), (3.5, "late"), (12.0, "none"), (1.0, "cotimed"), (-0.5, "cotimed")):
    r = P.extract_frames(*drive(I, V, [(20 + off, 22.0), (0.0, 1.0)]))
    assert P._cls(r["ageKwS"]) == tier, (off, r["ageKwS"])
    assert (r["T1AtPeakKw"] is None) == (tier in ("late", "none")) and abs(r["ageKwS"] - off) < 1e-6 or tier == "none"
r = P.extract_frames(*drive(I, V, []))
assert P._cls(r.get("ageKwS")) == "none" and r["T1AtPeakKw"] is None

# KA7: a voltage sample 1.4 s from the peak current sample is paired (vAgeKwS stored = 1.4); at 1.6 s the current sample is dropped
Iv = [(float(s), 0.0) for s in range(0, 31)]; Iv[20] = (20.0, 90.0)
r = P.extract_frames(*drive(Iv, [(21.4, 400.0), (5.0, 350.0)], [(20.0, 30.0)]))
assert r["ok"] and r["peakKwRebuilt"] == -36.0 and abs(r["vAgeKwS"] - 1.4) < 1e-6, (r.get("peakKwRebuilt"), r.get("vAgeKwS"))
r = P.extract_frames(*drive(Iv, [(21.6, 400.0), (5.0, 350.0)], [(20.0, 30.0)]))
assert r["ok"] and r["peakKwRebuilt"] != -36.0

# keyed-map join assertion on the stored block
import json
a = json.load(open("summary_arrays.json", encoding="utf-8"))
B = a["powerPeakTemperature"]
ak = [p[5] for p in a["cRatePointsAK"]]
assert len(set(ak)) == len(ak) and set(B["kwViewX"]) == set(ak)
assert B["knownAnswer"]["misses"] == {"peakKw": 0, "peakI": 0, "t1PeakI": 0}
assert all(v["tier"] in ("cotimed", "nearby", "late") and v["x"] is not None for v in B["kwViewX"].values() if v["x"] is not None)
# language rule AUD29-F05: the old kW title fires, the new one does not
import language_gate as G
assert "M550-F05-kw-view" in G.scan_text("Drive peak charge power (not co-timed with peak current), kW")
assert "M550-F05-kw-view" not in G.scan_text("Drive peak charge power (reconstructed I\u00D7V sample), kW")
print("test_power_peak_temp OK")
