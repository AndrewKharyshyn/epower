#!/usr/bin/env python3
"""test_cohort_rates.py (M291) — the roadmap's named cohort-rate contract test:
"every rate exposes paired n/km", plus the paired-eligibility guard the audit asked
for (a row with a missing numerator must NOT contribute its distance to the
denominator). Pure unit test over seasonal_core; no corpus files required.

Run: python3 test_cohort_rates.py   (exit 0 = pass)
"""
import math
import seasonal_core as sc

fails = []

def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)

def approx(a, b, tol=1e-9):
    return a is not None and b is not None and abs(a - b) <= tol

# ── 1. The audit's canonical example: null numerator must not inflate the denominator ──
# Two drives, each 100 km. One has quantity=10, the other has a MISSING quantity.
# Buggy behaviour: 100*10/(100+100) = 5.  Correct paired behaviour: 100*10/100 = 10.
drives = [{"q": 10.0, "distance_km": 100.0}, {"q": None, "distance_km": 100.0}]
det = sc.cohort_per_100km_detail(drives, "q")
check("null-numerator drive excluded from denominator (value=10, not 5)", approx(det["value"], 10.0))
check("paired_n counts only the paired-eligible drive (1)", det["paired_n"] == 1)
check("paired_km is only the paired distance (100)", approx(det["paired_km"], 100.0))
check("cohort_per_100km wrapper agrees with detail.value", approx(sc.cohort_per_100km(drives, "q"), det["value"]))

# ── 2. A real zero numerator IS paired-eligible (0 events over real distance) ──
drives0 = [{"q": 0.0, "distance_km": 50.0}, {"q": 4.0, "distance_km": 50.0}]
det0 = sc.cohort_per_100km_detail(drives0, "q")
check("real-zero numerator stays paired-eligible (n=2)", det0["paired_n"] == 2)
check("real-zero numerator counted in km (100)", approx(det0["paired_km"], 100.0))
check("rate over real-zero + 4 = 100*4/100 = 4", approx(det0["value"], 4.0))

# ── 3. Non-positive / missing distance never pairs (no divide-by-zero, no free numerator) ──
drives_d = [{"q": 5.0, "distance_km": 0.0}, {"q": 5.0, "distance_km": None},
            {"q": 5.0, "distance_km": 10.0}]
det_d = sc.cohort_per_100km_detail(drives_d, "q")
check("zero/None-distance drives excluded (paired_n=1)", det_d["paired_n"] == 1)
check("rate uses only the positive-distance drive (100*5/10=50)", approx(det_d["value"], 50.0))

# ── 4. NaN numerator behaves like missing ──
drives_nan = [{"q": float("nan"), "distance_km": 20.0}, {"q": 2.0, "distance_km": 20.0}]
det_nan = sc.cohort_per_100km_detail(drives_nan, "q")
check("NaN numerator excluded (paired_n=1, value=10)", det_nan["paired_n"] == 1 and approx(det_nan["value"], 10.0))

# ── 5. Empty / all-ineligible cohort returns well-formed null (never zero-as-real) ──
det_e = sc.cohort_per_100km_detail([], "q")
check("empty cohort -> value None, paired_n 0, paired_km 0", det_e["value"] is None and det_e["paired_n"] == 0 and approx(det_e["paired_km"], 0.0))

# ── 6. events-per-100km shares the same paired basis ──
ev = [{"e": 3.0, "distance_km": 100.0}, {"e": None, "distance_km": 100.0}]
det_ev = sc.cohort_events_per_100km_detail(ev, "e")
check("events rate: null-event drive excluded (value=3, paired_n=1)", approx(det_ev["value"], 3.0) and det_ev["paired_n"] == 1)

# ── 7. hourly rate is paired-eligible too (M291) ──
hr = [{"e": 6.0, "integr_time_h": 2.0}, {"e": None, "integr_time_h": 2.0}]
val_hr = sc.cohort_hourly_rate(hr, "e")
# paired: 6 / 2 = 3.0 ; buggy (unpaired) would be 6 / 4 = 1.5
check("cohort_hourly_rate excludes null-event hours (3.0, not 1.5)", approx(val_hr, 3.0))

# ── 8. contract: the detail dict always carries the three basis keys ──
check("detail dict exposes value+paired_n+paired_km", set(det.keys()) == {"value", "paired_n", "paired_km"})

if __name__ == "__main__":
    print("COHORT-RATE CONTRACT " + ("FAILED: " + "; ".join(fails) if fails else "PASSED"))
    raise SystemExit(1 if fails else 0)
