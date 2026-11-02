"""Known-answer tests for tools/m573_cell_spread_step.py (M573 spec Rev 1, KA1-KA5)."""
import json
import os
import sys
import unittest

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import m573_cell_spread_step as m


def synth(slope=0.0, step=0.0, step_at=0.7, n_days=80, per_day=5, noise=2.0, seed=0, rho=0.0):
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(n_days):
        months = 5.0 * k / (n_days - 1)
        day_eff = rng.normal(0, 1.0)
        for _ in range(per_day):
            T, I = rng.normal(25, 5), rng.normal(100, 20)
            y = 20 + slope * months + (step if months >= 5.0 * step_at else 0.0) + 0.1 * (T - 25) + 0.02 * (I - 100) + day_eff + rng.normal(0, noise)
            rows.append({"y": y, "months": months, "step": float(months >= 5.0 * step_at), "T": T, "I": I, "day": f"d{k:03d}", "wk": f"w{k // 7:02d}"})
    return pd.DataFrame(rows)


class TestM573(unittest.TestCase):
    def test_ka1_trend_without_step(self):
        d = synth(slope=0.5, step=0.0)
        r = m.fit_cluster(d, ["months", "step", "T", "I"], coef="months")
        s = m.fit_cluster(d, ["months", "step", "T", "I"], coef="step")
        self.assertTrue(r["ci95"][0] < 0.5 < r["ci95"][1])
        self.assertTrue(s["ci95"][0] < 0.0 < s["ci95"][1])

    def test_ka2_step_without_trend(self):
        d = synth(slope=0.0, step=3.0)
        r = m.fit_cluster(d, ["months", "step", "T", "I"], coef="months")
        s = m.fit_cluster(d, ["months", "step", "T", "I"], coef="step")
        lin = m.fit_cluster(d, ["months", "T", "I"], coef="months")
        self.assertTrue(r["ci95"][0] < 0.0 < r["ci95"][1])
        self.assertTrue(s["ci95"][0] < 3.0 < s["ci95"][1] and s["ci95"][0] > 0)
        self.assertLess(r["aic"], lin["aic"])          # the step model must beat the linear model on a pure step
        self.assertTrue(lin["ci95"][0] > 0.0)          # and the linear model alone reads it as a trend

    def test_ka3_week_block_bootstrap_coverage(self):
        hits, reps = 0, 150
        for s in range(reps):
            d = synth(slope=0.3, step=0.0, seed=100 + s, n_days=60, per_day=3)
            b = m.week_block_bootstrap(d, ["months", "T", "I"], n=300, seed=m.SEED)
            hits += b["ci95"][0] <= 0.3 <= b["ci95"][1]
        cov = hits / reps
        self.assertTrue(0.85 <= cov <= 0.995, cov)      # nominal 95 %, few blocks and 300 draws: wide acceptance band

    def test_ka4_reproduces_released_estimator(self):
        import degradation_trends as dt
        dm = pd.read_csv(os.path.join(ROOT, "drive_master.csv"))
        d = m.build_frame(dm)
        mine = m.fit_cluster(d, ["months", "T", "I"])
        rel = dt._cluster_ols(d, covars=("T", "I"))
        self.assertAlmostEqual(mine["est"], rel["slope"], places=3)
        self.assertAlmostEqual(mine["se"], rel["se"], places=3)
        self.assertEqual(mine["n"], rel["nObs"])
        self.assertEqual(mine["G"], rel["nDays"])
        with open(os.path.join(ROOT, "summary_arrays.json"), encoding="utf-8") as f:
            pay = json.load(f)["degradationTrends"]["cellSpread"]["clusterRobustOLS"]
        # the payload was built at the last ingestion; equality holds while the master is unchanged since
        self.assertAlmostEqual(mine["est"], pay["slope"], places=3)
        self.assertAlmostEqual(mine["ci95"][0], pay["ci95"][0], places=3)

    def test_ka5_master_md5_unchanged_by_import(self):
        p = os.path.join(ROOT, "drive_master.csv")
        a = m.md5(p)
        _ = m.build_frame(pd.read_csv(p))
        self.assertEqual(a, m.md5(p))


if __name__ == "__main__":
    unittest.main()
