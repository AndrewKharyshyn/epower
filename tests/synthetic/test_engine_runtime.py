"""M512 known-answer tests (analyses/M512_spec.md Rev 2): RPM-supported time base, gap cap, late first sample, RPM-less drive, backward dt attribution, bracket and rate bootstrap."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import engine_runtime as ER
import compute_drive_summary_v6 as D

RPM = "\u041e\u0431\u0435\u0440\u0442\u0438 \u0434\u0432\u0438\u0433\u0443\u043d\u0430 (rpm)"
CAP = D.DT_CAP_S

def csv(times, rpm):
    t = pd.to_datetime("2026-08-01 10:00:00") + pd.to_timedelta(times, unit="s")
    return pd.DataFrame({"time": t.strftime("%H:%M:%S.%f").str[:-3], RPM: rpm}).to_csv(index=False).encode()

# 1 Hz, 10 samples: rpm on (>400) for samples 5..9 -> intervals ending at samples 5..9 are on (backward attribution): 5 s on of 9 s supported
times = np.arange(10, dtype=float)
rpm = [0, 0, 0, 0, 0, 800, 800, 800, 800, 800]
sup, on, why = ER.runtime_from_bytes(csv(times, rpm))
assert (sup, on, why) == (9.0, 5.0, None), (sup, on, why)
# gap longer than the cap counts only the cap; dt == cap counts fully
sup, on, _ = ER.runtime_from_bytes(csv(np.array([0, 1, 2, 22, 27, 28], float), [0, 0, 0, 800, 800, 800]))
assert abs(sup - (1 + 1 + CAP + CAP + 1)) < 1e-9 and abs(on - (CAP + CAP + 1)) < 1e-9, (sup, on)
# late first RPM sample: the unsupported lead-in is not counted
sup, on, _ = ER.runtime_from_bytes(csv(np.arange(8, dtype=float), [np.nan, np.nan, np.nan, 800, 800, 800, 0, 0]))
assert (sup, on) == (4.0, 2.0), (sup, on)
# RPM-less drive and a two-sample series carry a reason, not a number
s, o, why = ER.runtime_from_bytes(csv(np.arange(6, dtype=float), [np.nan] * 6))
assert np.isnan(s) and np.isnan(o) and why == "no_rpm_series"
s, o, why = ER.runtime_from_bytes(csv(np.arange(2, dtype=float), [800, 800]))
assert np.isnan(s) and why == "no_rpm_series"
# totals: bracket and the imputed figure by hand
g = pd.DataFrame({"rpm_supported_s": [3600.0, 1800.0, np.nan], "engine_on_s": [1800.0, 900.0, np.nan], "elapsed_s": [4000.0, 1800.0, 1000.0],
                  "engine_on_pct": [50.0, 50.0, np.nan], "distance_km": [10.0, 5.0, 2.0]})
t = ER._totals(g)
assert abs(t["supportedOnHours"] - 0.75) < 1e-12 and abs(t["supportedHours"] - 1.5) < 1e-12
assert abs(t["elapsedHours"] - 6800 / 3600) < 1e-12 and abs(t["unsupportedHours"] - (6800 / 3600 - 1.5)) < 1e-12
assert abs(t["bracketHours"][1] - (0.75 + t["unsupportedHours"])) < 1e-12 and abs(t["scaledImputedHours"] - (2000 + 900) / 3600) < 1e-12
assert t["nDrivesWithoutRpm"] == 1 and abs(t["kmWithRpm"] - 15.0) < 1e-12 and abs(t["supportedOnPer10kKm"] - 0.75 / 15 * 10000) < 1e-9
assert t["scaledImputedHours"] > t["supportedOnHours"] and t["scaledImputedHours"] < t["bracketHours"][1]
# day-clustered ratio bootstrap: deterministic, interval brackets the point ratio
num = np.arange(1, 41, dtype=float); den = np.full(40, 10.0); days = np.repeat(np.arange(10), 4).astype(str)
c1, n1 = ER._dayboot_ratio(num, den, days, nb=500); c2, _ = ER._dayboot_ratio(num, den, days, nb=500)
assert c1 == c2 and n1 == 10 and c1[0] < num.sum() / den.sum() < c1[1]
import compute_summary_arrays as cs
assert ER.CLASS_ORDER == cs.CLASS_ORDER and all(ER._cond_class(x) == cs._cond_class(x) for x in cs.CLASS_ORDER + ["unknown", None])
_m = pd.DataFrame({"ens_invalid": [True, False, np.nan, "True"], "ens_outlier_v2": [False, False, np.nan, False]})
assert ER._canonical_bad(_m).tolist() == cs._canonical_bad(_m).tolist() == [True, False, False, True]
print("test_engine_runtime: OK")
