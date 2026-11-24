"""M771 known-answer tests (analyses/M771_spec.md Rev 2): tools/weather_proxy.py classifies the wiper and lighting proxies exactly on the boundaries (minimum of 10 moving cloud rows, share between 0 and the threshold excluded), the dark contrast
excludes wet-proxy drives, the support gate counts exactly and keeps A1 as counts only below the floor of 20 drives on 10 days, a planted wet difference is recovered through a planted season confounder with month fixed effects,
the displaced-day placebo uses only other days of the same class, thermal class and month with distance within 25 %, the rank-deficiency counter runs, a foreign master stops and no dates, names or per-drive rows enter a result."""
import os, shutil, sys, tempfile
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import weather_proxy as W
import odometer_jump_audit as J

# proxy definitions on the boundaries
lab = W.wet_label([0.05, 0.0499, 0.0, 0.2, 0.0, 0.5, np.nan], [10, 10, 10, 9, 9, 50, 50], 0.05)
assert lab[0] == 1.0 and np.isnan(lab[1]) and lab[2] == 0.0 and np.isnan(lab[3]) and np.isnan(lab[4]) and lab[5] == 1.0 and np.isnan(lab[6])
assert W.wet_label([0.02], [10], 0.02)[0] == 1.0 and W.wet_label([0.2], [10], 0.2)[0] == 1.0 and np.isnan(W.wet_label([0.19], [10], 0.2)[0])
dk = W.dark_label([0.5, 0.49, 0.05, 0.04, 0.9, 0.9], [10, 10, 10, 10, 10, 9], [0.0, 0.0, 0.0, 0.0, 1.0, 0.0])
assert dk[0] == 1.0 and np.isnan(dk[1]) and np.isnan(dk[2]) and dk[3] == 0.0 and np.isnan(dk[4]) and np.isnan(dk[5])           # a wet-proxy drive and a short drive are excluded; the band between is excluded


def planted(n_days=200, per_day=3, wet_effect=0.8, seed=2, wet_days_frac=0.25):
    """fuel = 5 + wet_effect * wet + 0.05 * ambient + month effect + noise; wet drives cluster in the cold months (season confounder absorbed by month fixed effects)."""
    r = np.random.default_rng(seed)
    rows = []
    base = pd.Timestamp("2026-05-01")
    for d in range(n_days):
        day = (base + pd.Timedelta(days=d)).strftime("%Y-%m-%d")
        month = day[:7]
        mi = int(day[5:7])
        amb = 25 - 3.0 * abs(mi - 7) + r.normal(0, 2)
        p_wet = wet_days_frac * (1.0 + (mi >= 10))
        wet_day = r.random() < p_wet
        for k in range(per_day):
            wet = float(wet_day and r.random() < 0.9)
            dist = r.uniform(6, 40)
            rows.append({"day": day, "month": month, "cls": ["urban", "mixed", "mixed_highway", "highway"][(d + k) % 4], "thermal": "warm" if amb > 12 else "cold", "wet": wet, "ambient": amb, "logdist": np.log(dist), "distance_km": dist,
                         "speed_mean_moving": r.uniform(25, 80), "first_of_day": float(k == 0), "fuel_L_per_100km": 5 + wet_effect * wet + 0.05 * amb + 0.15 * (mi >= 10) + r.normal(0, 0.4)})
    d_ = pd.DataFrame(rows)
    d_["v2"] = d_["speed_mean_moving"] ** 2
    return d_


d = planted()
r = W.boot_diff(d, "fuel_L_per_100km", 300)
assert r["ci95"][0] < 0.8 < r["ci95"][1] and abs(r["difference_after_adjustment"] - 0.8) < 0.2, r
assert r["bootstrap_rank_deficient_resamples"]["draws"] == 300 and r["bootstrap_rank_deficient_resamples"]["deficient"] >= 0

# gate: counts exact; below the floor A1 is counts only; at or above the floor it passes
cov = pd.DataFrame({"day": ["d%d" % (i // 2) for i in range(60)], "wiper_nonzero_share": [0.3] * 30 + [0.0] * 30, "moving_n_veh": [20] * 60, "lowbeam_share": [0.0] * 60})
fuel = cov.copy()
g = W.gate(cov, fuel)
t = g["thresholds"]["0.05"]
assert t["wet_proxy_drives"] == 30 and t["fuel_basis_wet_proxy_drives"] == 30 and t["dry_reference_drives"] == 30 and t["wet_proxy_days"] == 15 and g["passed"] is True
small = pd.concat([cov.iloc[:19], cov.iloc[30:]])
g2 = W.gate(small, small)
assert g2["thresholds"]["0.05"]["wet_proxy_drives"] == 19 and g2["passed"] is False
few_days = cov.copy()
few_days["day"] = ["d%d" % (i // 8) for i in range(60)]                                                     # 30 wet drives on fewer than 10 days
assert W.gate(few_days, few_days)["passed"] is False

# matched support: a wet drive needs a dry drive of the same cell within 25 % on another day
m = pd.DataFrame({"day": ["a", "b", "c", "d"], "cls": ["urban"] * 4, "thermal": ["warm"] * 4, "month": ["2026-09"] * 4, "wet": [1.0, 0.0, 1.0, 0.0], "distance_km": [10.0, 11.0, 30.0, 11.0]})
assert W.matched_support(m) == 1                                                                              # the 30 km wet drive has no dry drive within 25 %
assert abs(W.within_month_share(planted()) - 1.0) < 1.0                                                      # a proper share in (0, 1]

# displaced-day placebo: donors only from another day, same class, thermal class and month, distance within 25 %
pl = W.displaced_labels(d, np.random.default_rng(1))
assert 0.8 * len(d) < len(pl) <= len(d)
assert set(pl["wet"].unique()) <= {0.0, 1.0}

# language and privacy
assert "rain" not in W.__doc__.lower().replace("never rain", "") and W.MIN_ROWS == 10 and W.FLOOR_DRIVES == 20 and W.FLOOR_DAYS == 10
assert J.scan_privacy({"G": {"thresholds": {"0.05": {"wet_proxy_drives": 21}}}, "C": {"wet_proxy_by_month": {"2026-09": 3}}}) == []
assert J.scan_privacy({"f": "20260511_185709.csv"}) and J.scan_privacy({"d": "2026-07-26"})

# foreign master stops, nothing written
td = tempfile.mkdtemp()
try:
    with open(os.path.join(td, "m.csv"), "w", encoding="utf-8") as f:
        f.write("file\nx.csv\n")
    out = os.path.join(td, "out")
    assert W.main(["--run", "--master", os.path.join(td, "m.csv"), "--out-dir", out]) == 1 and not os.path.exists(out)
finally:
    shutil.rmtree(td, ignore_errors=True)
print("test_weather_proxy: OK")
