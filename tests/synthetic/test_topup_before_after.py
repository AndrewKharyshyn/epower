"""M773 known-answer tests (analyses/M773_spec.md Rev 2): tools/topup_before_after.py recovers a planted before/after step through a planted drift, ambient and speed confounder, excludes the step day and the puncture day from the windows,
applies the floors (5 days and 20 drives per side, clusters at least twice the parameters) with counts only below them, skips the placebo centres whose window holds a protected date (the October single-corner steps), drops a constant thermal
class, runs the km-weighted fit, writes design_mde from the outcome SD and days, applies the lower-end reading rule and the wrong-sign wording, counts rank-deficient resamples, stops on a foreign master and keeps dates, names and per-drive rows out of a result."""
import os, shutil, sys, tempfile
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import topup_before_after as B
import tyre_rolling as T
import odometer_jump_audit as J


def planted(step=-0.6, drift=0.01, seed=4, n_days=120, per_day=3, start="2026-06-01"):
    r = np.random.default_rng(seed)
    rows = []
    base = pd.Timestamp(start)
    for d in range(n_days):
        day = (base + pd.Timedelta(days=d)).strftime("%Y-%m-%d")
        amb = 18 + 6 * np.sin(d / 25.0) + r.normal(0, 1.5)
        for k in range(per_day):
            sp = r.uniform(25, 55)
            ekm = r.uniform(1.2, 6.0)
            after = 1.0 if day > "2026-07-26" else 0.0
            rows.append({"day": day, "cls": ["urban", "mixed", "mixed_highway", "highway"][(d + k) % 4], "thermal": "warm", "ambient": amb, "ev_speed": sp, "inv_ev_speed": 1.0 / sp, "log_ev_km": np.log(ekm), "soak3": float(r.random() < 0.3),
                         "ev_dist_km": ekm, "ev_dist_pct": r.uniform(20, 80), "ev_kwh_per100km": 12 + 0.08 * amb + 20.0 / sp + drift * d + step * after + r.normal(0, 0.5), "reg": 0.0})
    return pd.DataFrame(rows)


d = planted()
w = B.window(d, "2026-07-26", 28)
assert (w["day"] != "2026-07-26").all() and (w["rel"].abs() <= 28).all() and (w["rel"] != 0).all() and set(w["reg"].unique()) == {0.0, 1.0}
assert (w.loc[w["reg"] == 1, "rel"] > 0).all() and (w.loc[w["reg"] == 0, "rel"] < 0).all()
# the puncture day is excluded
dp = d.copy()
dp.loc[dp["day"] == "2026-07-14", "ev_kwh_per100km"] = 999.0
assert (B.window(dp, "2026-07-26", 28)["day"] != "2026-07-14").all() and B.window(dp, "2026-07-26", 28)["ev_kwh_per100km"].max() < 900
assert (B.window(dp, "2026-07-26", 28, exclude_days=())["day"] == "2026-07-14").any()

# a planted step is recovered inside its interval despite a drift, ambient and speed confounding
f = B.fit(w, "ev_kwh_per100km", B.COVS_FULL, 300)
assert not f.get("counts_only") and f["ci95"][0] < -0.6 + 0.25 and f["ci95"][1] > -0.6 - 0.9 and f["mde"] > 0
assert f["bootstrap_rank_deficient_resamples"]["draws"] == 300 and f["thermal_levels_in_window"] == 1                  # a constant thermal class adds no parameter and is counted
assert f["parameters"] == 2 + 3 + len(B.COVS_FULL)                                                                  # const, reg, three class dummies, covariates
# the km-weighted fit runs and agrees in sign
w2 = w.copy()
w2["w_km"] = w2["ev_dist_km"]
fw = B.fit(w2, "ev_kwh_per100km", B.COVS_FULL, 200, weight_col="w_km")
assert not fw.get("counts_only") and fw["difference_after_minus_before"] < 0

# floors: fewer than 5 days or 20 drives per side, or too few clusters for the parameters: counts only
few = w[(w["rel"] >= -3) & (w["rel"] <= 3)]
assert B.fit(few, "ev_kwh_per100km", B.COVS_FULL, 100).get("counts_only") is True
one_side = w[w["reg"] == 1]
assert B.fit(one_side, "ev_kwh_per100km", B.COVS_FULL, 100).get("counts_only") is True
narrow = w[(w["rel"] >= -8) & (w["rel"] <= 8)]
fn = B.fit(narrow, "ev_kwh_per100km", B.COVS_FULL, 100)
assert fn.get("counts_only") is True or (fn["days_before"] + fn["days_after"]) >= B.CLUSTER_FLOOR_FACTOR * fn["parameters"]       # the cluster floor holds whenever an estimate is written

# design_mde from the outcome SD and the days per side, written independently of any fit
dm = B.design_mde(w, "ev_kwh_per100km")
assert dm["expected_mde"] > 0 and dm["days_before"] > 0 and dm["days_after"] > 0 and abs(dm["outcome_sd"] - w["ev_kwh_per100km"].std(ddof=1)) < 1e-12

# reading rule (lower end) and wrong-sign wording
assert B.reading(0.04, 0.05) == "informative" and B.reading(0.06, 0.05) == "not informative at this support"
assert B.sign_note(0.5, [0.2, 0.8]) == "inconsistent with the expected sign, confounding suspected" and B.sign_note(-0.5, [-0.8, -0.2]).startswith("interval excludes zero with the expected sign") and B.sign_note(-0.1, [-0.5, 0.2]) == "interval includes zero"

# protected-date guard: the October single-corner steps (+76 and +82 days) make the +56 and +84 day centres at 28 days unusable
prot = T.protected_dates(["2026-07-26", "2026-10-10", "2026-10-16"])
c56 = (pd.Timestamp("2026-07-26") + pd.Timedelta(days=56)).strftime("%Y-%m-%d")
c84 = (pd.Timestamp("2026-07-26") + pd.Timedelta(days=84)).strftime("%Y-%m-%d")
c42 = (pd.Timestamp("2026-07-26") + pd.Timedelta(days=42)).strftime("%Y-%m-%d")
cm84 = (pd.Timestamp("2026-07-26") - pd.Timedelta(days=84)).strftime("%Y-%m-%d")
assert not T.window_ok(c56, 28, prot) and not T.window_ok(c84, 28, prot) and T.window_ok(c42, 28, prot) and T.window_ok(cm84, 14, prot)

# dose by week: aggregates only, weeks with fewer than 3 drives suppressed
dd = d.copy()
dd["p_cold"] = np.where(dd["day"] > "2026-07-26", 280.0, 245.0)
dose = B.dose_by_week(dd, "2026-07-26")
assert dose["week_+1"]["median_kpa"] == 280.0 and dose["week_-1"]["median_kpa"] == 245.0 and all(k.startswith("week_") for k in dose)

# privacy and language
assert J.scan_privacy({"A1_primary_28d_unweighted": {"days_before": 20, "difference_after_minus_before": -0.2}, "placebo_windows_guarded": {"windows": {"half28_offset+56": {"skipped": "x"}}}, "pressure_dose_per_week": {"week_+1": {"drives": 8}}}) == []
assert J.scan_privacy({"f": "20260511_185709.csv"}) and J.scan_privacy({"d": "2026-07-26"})
assert B.EXPECT_LOWER_PCT == 0.35 and B.OFFSETS == (-84, -56, -42, 42, 56, 84) and B.CLUSTER_FLOOR_FACTOR == 2 and "not a pressure effect" in B.__doc__

# foreign master stops, nothing written
td = tempfile.mkdtemp()
try:
    with open(os.path.join(td, "m.csv"), "w", encoding="utf-8") as fh:
        fh.write("file\nx.csv\n")
    out = os.path.join(td, "out")
    assert B.main(["--run", "--master", os.path.join(td, "m.csv"), "--out-dir", out]) == 1 and not os.path.exists(out)
finally:
    shutil.rmtree(td, ignore_errors=True)
print("test_topup_before_after: OK")
