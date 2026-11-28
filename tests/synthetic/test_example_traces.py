"""M795 known-answer tests (analyses/M795_spec.md Rev 2) for tools/example_traces.py: debounce, engine-off run, first-start window, sign seconds (regeneration is not counted), peak eligibility, median choice, published block."""
import json, os, sys
import numpy as np
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import example_traces as X

# 1. debounce: a 2 s blip inside a run is absorbed, a 3 s change stays, the first run is never changed
s = np.array([1, 1, 1, 0, 0, 1, 1, 1, 1, 0, 0, 0, 0], dtype=bool)
d = X.debounce(s, 3)
assert d.tolist() == [True, True, True, True, True, True, True, True, True, False, False, False, False], d.tolist()
assert X.debounce([], 3).size == 0

# 2. longest engine-off run: planted run of 10 s at 36 km/h (= 0.1 km), a 2 s engine blip above 400 inside it is debounced away, k scales the distance, the count of raw rpm > 400 seconds is reported
rpm = np.r_[np.full(5, 900.0), np.full(4, 0.0), [900.0, 900.0], np.full(5, 0.0), np.full(5, 900.0), np.full(3, 0.0), np.full(5, 900.0)]
speed = np.full(len(rpm), 36.0)
r = X.longest_off_run(rpm, speed, 1.0)
assert r["a"] == 5 and r["b"] == 16 and r["n"] == 11 and abs(r["km"] - 11 * 36.0 / 3600) < 1e-12 and r["rawAbove400"] == 2, r
r2 = X.longest_off_run(rpm, speed, 2.0); assert abs(r2["km"] - 2 * r["km"]) < 1e-12
assert X.longest_off_run(np.full(10, 900.0), np.full(10, 50.0), 1.0) is None
assert X.longest_off_run(np.full(10, 0.0), np.full(10, 1.0), 1.0) is None       # shorter than the minimum distance

# 3. first engine start: needs 30 known seconds of rpm <= 400 before the first rotation; a window that does not fit returns None
rp = np.r_[np.full(40, 0.0), np.full(400, 1500.0)]
assert X.first_start_window(rp, 30, 300) == 10
assert X.first_start_window(np.r_[np.full(10, 0.0), np.full(400, 1500.0)], 30, 300) is None   # engine on before 30 s of off
assert X.first_start_window(np.r_[np.full(40, 0.0), np.full(100, 1500.0)], 30, 300) is None    # window too short
assert X.first_start_window(np.r_[np.full(35, 0.0), [np.nan], np.full(3, 0.0), np.full(400, 1500.0)], 30, 300) is None  # a missing second inside the 30 s before the start: not a clean start

# 4. sign seconds: discharge counts, charge counts only with target torque >= 0 (regeneration is not generation), rpm <= 400 counts nothing
rpm = np.full(6, 1500.0); rpm[5] = 100.0
p = np.array([5.0, 5.0, -5.0, -5.0, -5.0, 5.0]); tq = np.array([10.0, 10.0, 10.0, -20.0, np.nan, 10.0])
assert X.sign_seconds(rpm, p, tq) == (2, 1), X.sign_seconds(rpm, p, tq)

# 5. peak eligibility: speed >= 80 at the peak, pedal > 10 in the 5 s before, no gap within 3 s, window inside the grid
n = 200; a = 100
pk = np.zeros(n); pk[a] = 50.0; sp = np.full(n, 100.0); pd_ = np.zeros(n); pd_[a - 2] = 30.0
assert X.peak_eligible(pk, sp, pd_, a)
assert not X.peak_eligible(pk, np.full(n, 70.0), pd_, a)                       # below the highway threshold
assert not X.peak_eligible(pk, sp, np.zeros(n), a)                              # no pedal in the 5 s before
pd2 = pd_.copy(); pd2[a - 6] = 30.0; pd2[a - 2] = 0.0; assert not X.peak_eligible(pk, sp, pd2, a)   # pedal 6 s before is outside the look-back
sp2 = sp.copy(); sp2[a + 2] = np.nan; assert not X.peak_eligible(pk, sp2, pd_, a)   # gap within 3 s
assert not X.peak_eligible(pk, sp, pd_, 10)                                     # window outside the grid

# 6. median choice: closest to the median, ties by the smaller key
i, med = X.closest_to_median([1.0, 5.0, 9.0, 5.0], ["d", "c", "a", "b"]); assert med == 5.0 and i == 3   # tie 5.0: keys c and b -> b
i, med = X.closest_to_median([1.0, 2.0, 10.0], ["a", "b", "c"]); assert med == 2.0 and i == 1
assert X.coverage(np.array([1.0, np.nan]), np.array([1.0, 1.0])) == 0.5

# 7. the published block: provenance and selection counts, T8 known answers, month label only, gaps as null
A = json.load(open("summary_arrays.json", encoding="utf-8")); B = A["exampleTraces"]; T = B["traces"]
rm = A["evTraction"]["runMax"]
assert B["provenance"]["drives"]["T8"]["file"] == rm["file"]
assert abs(T["T8"]["run"]["km"] - rm["km"]) <= 0.01 and abs(T["T8"]["run"]["durationS"] - rm["durationS"]) <= 1 and T["T8"]["run"]["debouncedEngineOnSeconds"] == 0
for k in ("T7", "T9"):
    s = B["selection"][k]; assert s["eligible"] <= s["candidates"] and s["eligible"] >= 1
for k, tr in T.items():
    assert len(tr["month"].split()) == 2 and tr["month"].split()[0] in X.MONTHS and "date" not in tr and "file" not in tr
    n = len(tr["t"]); assert all(len(tr[c]) == n for c in tr if c in ('speed', 'rpm', 'powerKw', 'coolantC', 'torqueNm', 'pedal'))
assert T["T7"]["dischargeSeconds"] >= 20 and T["T7"]["chargeSeconds"] >= 20 and B["selection"]["T7"]["chosenEngineOnS"] == T["T7"]["engineRotationSeconds"]
assert T["T9"]["peakSpeedKmh"] >= 80 and T["T9"]["powerKw"][30] == T["T9"]["peakKw"]
assert len(json.dumps(B)) < 60000
print("ok test_example_traces")
