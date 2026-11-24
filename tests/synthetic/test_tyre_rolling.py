"""M770 known-answer tests (analyses/M770_spec.md Rev 2): tools/tyre_rolling.py converts snapshots to the cold-equivalent level exactly, recovers a planted pressure slope through a planted ambient confounder, sizes the design from the
RESIDUAL regressor SD, applies the lower-magnitude reading rule and the wrong-sign wording, builds before/after windows that exclude the puncture day and recovers a planted step while placebo windows avoid every protected date,
returns counts only below 5 days per side, stops on a foreign master and keeps dates and per-drive rows out of a result. No real data is needed."""
import json, os, shutil, sys, tempfile
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import tyre_rolling as T
import odometer_jump_audit as J

M733 = {"E2_temperature_response": {"front": {"slope_kpa_per_c": 0.7, "minutes_into_drive_coef_kpa_per_min": 0.05}, "rear": {"slope_kpa_per_c": 0.5, "minutes_into_drive_coef_kpa_per_min": 0.06}}}

# cold-equivalent: exact arithmetic on planted snapshots
df = pd.DataFrame({"settled_ambient_c": [25.0], "min_into_drive": [10.0], "fl_kpa": [250.0], "fr_kpa": [250.0], "rl_kpa": [230.0], "rr_kpa": [230.0]})
ce = T.cold_equivalent(df, M733).iloc[0]
exp = np.mean([250 - 0.7 * 10 - 0.05 * 10, 250 - 0.7 * 10 - 0.05 * 10, 230 - 0.5 * 10 - 0.06 * 10, 230 - 0.5 * 10 - 0.06 * 10])
assert abs(ce - exp) < 1e-12
assert list(T.epochs(["2026-07-01", "2026-07-26", "2026-10-10", "2026-10-20"], ["2026-07-26", "2026-10-10", "2026-10-16"])) == [0, 1, 2, 3]


def planted(n_days=150, per_day=4, slope=-0.20, seed=3, step_effect=0.0):
    """fuel = 6 + slope * reg + 0.1 * ambient + noise; the regressor (cold-equivalent pressure per +10 %) also moves with ambient (confounder)."""
    r = np.random.default_rng(seed)
    rows = []
    base = pd.Timestamp("2026-06-01")
    for d in range(n_days):
        day = (base + pd.Timedelta(days=d)).strftime("%Y-%m-%d")
        amb = 15 + 10 * np.sin(d / 30.0) + r.normal(0, 2)
        for k in range(per_day):
            reg = 0.3 * (amb - 15) / 10 + r.normal(0, 0.5)
            after = 1.0 if day >= "2026-07-26" else 0.0
            dist = r.uniform(6, 50)
            rows.append({"day": day, "cls": ["urban", "mixed", "mixed_highway", "highway"][(d + k) % 4], "thermal": "warm" if amb > 15 else "cold", "reg": reg, "ambient": amb, "logdist": np.log(dist), "distance_km": dist,
                         "speed_mean_moving": r.uniform(25, 80), "dsoc100": r.normal(0, 1), "first_of_day": float(k == 0), "min_into_drive": r.uniform(2, 15),
                         "fuel_L_per_100km": 6 + slope * reg + 0.1 * amb + step_effect * after + r.normal(0, 0.4), "p_cold": 250 + 10 * reg, "epoch": 0 if day < "2026-07-26" else 1})
    d_ = pd.DataFrame(rows)
    d_["v2"] = d_["speed_mean_moving"] ** 2
    return d_


d = planted()
est, ci, sd = T.boot(d, "fuel_L_per_100km", T.COVS, 300)
assert ci[0] < -0.20 < ci[1] and abs(est + 0.20) < 0.08, (est, ci)
assert T.slope(d.assign(reg=d["reg"]), "fuel_L_per_100km", [c for c in T.COVS if c != "ambient"]) > est + 0.01              # without the confounder the slope is biased toward plus

# sizing from the RESIDUAL regressor SD (smaller than the raw SD because ambient explains part of it)
sz = T.design_sizing(d, "fuel_L_per_100km", T.COVS)
assert 0 < sz["regressor_sd_residual_per10pct"] < sz["regressor_sd_raw_per10pct"] and sz["expected_mde_per10pct"] > 0 and sz["n_eff"] <= sz["drives"] and "between_epoch_variance_share" in sz

# epoch fixed effects run and agree in sign with the planted slope
assert T.slope(d, "fuel_L_per_100km", T.COVS, extra_cat=("epoch",)) < 0

# reading rule on the LOWER magnitude and the wrong-sign wording
assert T.reading(0.05, 0.1) == "informative" and T.reading(0.0501, 0.1) == "not informative at this support"
assert T.sign_note(0.5, [0.2, 0.8]) == "inconsistent with the expected sign, confounding suspected"
assert T.sign_note(-0.5, [-0.8, -0.2]).startswith("interval excludes zero with the expected sign") and T.sign_note(-0.1, [-0.5, 0.3]) == "interval includes zero"
assert T.sign_note(-0.5, [-0.8, -0.2], expected_negative=False) == "inconsistent with the expected sign, confounding suspected"

# B1: planted step recovered; the puncture day is excluded; counts only below 5 days per side; protected dates guard the placebo windows
ds = planted(step_effect=-0.6, slope=0.0)
ds.loc[ds["day"] == T.PUNCTURE_DAY, "fuel_L_per_100km"] = 99.0                                                        # a poisoned puncture day must not enter
o = T.before_after(ds, "2026-07-26", 14, "fuel_L_per_100km", T.COVS, 300)
assert not o.get("counts_only") and o["ci95"][0] < -0.6 < o["ci95"][1] and o["drives_before"] > 0 and o["drives_after"] > 0
assert o["difference_after_minus_before"] < -0.3
few = ds[(ds["day"] >= "2026-07-24") & (ds["day"] <= "2026-07-28")]
assert T.before_after(few, "2026-07-26", 14, "fuel_L_per_100km", T.COVS, 300).get("counts_only") is True
prot = T.protected_dates(["2026-07-26", "2026-10-10", "2026-10-16"])
assert T.window_ok("2026-09-01", 14, prot) and not T.window_ok("2026-07-20", 14, prot) and not T.window_ok("2026-07-10", 14, prot) and not T.window_ok("2026-10-05", 14, prot)
assert "2026-07-14" in prot and T.STEP_DATE == "2026-07-26"

# owner scale decision recorded verbatim; no dates or per-drive rows in a result
assert T.OWNER_DECISION["independentlyVerified"] is False and T.OWNER_DECISION["quote"].startswith("You may trust the data") and T.OWNER_DECISION["date"] == "24 Nov 2026"
assert J.scan_privacy({"A1": {"drives": 100, "days": 50, "slope_L_per_100km_per10pct": -0.1}, "B1": {"windows": {"14": {"days_before": 6}}, "placebo": {"14": {"+42": {"skipped": "x"}}}}}) == []
assert J.scan_privacy({"f": "20260511_185709.csv"}) and J.scan_privacy({"d": "2026-07-26"})

# foreign master stops, nothing written
td = tempfile.mkdtemp()
try:
    with open(os.path.join(td, "m.csv"), "w", encoding="utf-8") as f:
        f.write("file\nx.csv\n")
    out = os.path.join(td, "out")
    assert T.main(["--run", "--master", os.path.join(td, "m.csv"), "--out-dir", out]) == 1 and not os.path.exists(out)
finally:
    shutil.rmtree(td, ignore_errors=True)
assert T.EXPECT_PCT == (-0.3, -2.3) and T.SEED == 42
print("test_tyre_rolling: OK")
