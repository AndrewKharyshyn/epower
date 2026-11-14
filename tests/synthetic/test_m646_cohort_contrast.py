"""M646 known-answer test (spec analyses/M646_spec.md Rev 1): synthetic cohorts with known ratios give the exact raw and route-standardised differences, the bootstrap is deterministic with the seed,
an unsupported route cell makes the adjusted difference 'not estimable', and a cohort with few effective days is exploratory (no verdict wording)."""
import os, sys
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import m646_cohort_contrast as M

def frame(n_days=14, cold_nonurban_days=14):
    rows = []
    for g, (ru, rn) in (("warm", (10.0, 20.0)), ("cold", (12.0, 26.0))):
        for d in range(n_days):
            for s, r in (("urban", ru), ("non-urban", rn)):
                if g == "cold" and s == "non-urban" and d >= cold_nonurban_days:
                    continue
                for k in range(2):
                    km = 5.0 + k
                    rows.append({"file": f"{g}{d}{s}{k}", "date": f"2026-01-{d+1:02d}" if g == "warm" else f"2026-02-{d+1:02d}", "cohort": g, "strat2": s, "strat4": s, "distance_km": km, "N": r * km, "D": km})
    return pd.DataFrame(rows)

w = pd.Series({"urban": 0.4, "non-urban": 0.6})
M.METRICS["T"] = {"label": "t", "unit": "u", "num": None, "den": None, "defn": "t", "need": []}
f = frame()
e = M.contrast(f, "cold", "T", w)
assert abs(e["adjusted"]["estimate"] - (0.4 * 2 + 0.6 * 6)) < 1e-9, e["adjusted"]
# raw: equal km in every cell -> equal cohort mix 50/50 -> (12+26)/2 - (10+20)/2 = 4
assert abs(e["raw"]["estimate"] - 4.0) < 1e-9, e["raw"]
assert e["raw"]["ci95"][0] <= 4.0 <= e["raw"]["ci95"][1] and e["adjusted"]["ci95"][0] <= e["adjusted"]["estimate"] <= e["adjusted"]["ci95"][1]
assert not e["exploratory"] and e["raw"]["reading"] == "interval excludes zero"
e2 = M.contrast(f, "cold", "T", w)
assert e == e2, "bootstrap must be deterministic with the seed"
# unsupported route cell (cold non-urban on 3 days only): adjusted not estimable, raw still shown
f3 = frame(cold_nonurban_days=3)
e3 = M.contrast(f3, "cold", "T", w)
assert e3["adjusted"]["estimable"] is False and "non-urban" in e3["adjusted"]["reason"] and e3["raw"]["estimable"] is True
# few effective days: one dominant day makes the contrast exploratory, no verdict wording
f4 = frame()
f4.loc[(f4.cohort == "cold") & (f4.date == "2026-02-01"), "distance_km"] *= 500
f4["N"] = np.where(f4.cohort == "cold", f4["N"] / f4["D"] * f4["distance_km"], f4["N"]); f4["D"] = f4["distance_km"]
e4 = M.contrast(f4, "cold", "T", w)
assert e4["exploratory"] and "reading" not in e4["raw"], e4["effectiveDays"]
# below the floor: nothing drawn
f5 = f[(f.cohort == "warm") | (f.date <= "2026-02-04")]
assert M.contrast(f5, "cold", "T", w)["raw"]["estimable"] is False
print("PASS test_m646_cohort_contrast")
# language rule (R8): forbidden readings are caught, the required wording is not
import language_gate as LG
rule = [r for r in LG.RULES if r.rid == "M646-cohort-contrast-wording"][0]
for bad in ("a winter penalty of 2 kWh", "higher consumption due to cold", "temperature-adjusted difference", "the Cold vs Warm difference is significant", "no difference between Cold and Warm", "cold raises the energy intensity"):
    assert rule.hits(bad), bad
for good in ("Difference between thermal classes, not a temperature effect.", "Route-mix standardised (urban/non-urban only).", "interval includes zero (not distinguished at this support)"):
    assert not rule.hits(good), good
print("PASS language rule")
