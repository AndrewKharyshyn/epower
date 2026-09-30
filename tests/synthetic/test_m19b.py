"""Known-answer test for compute_drive_summary_v6.m19b_huber_adjust (M312). Run: python tests/synthetic/test_m19b.py"""
import os, sys
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import numpy as np, pandas as pd
import compute_drive_summary_v6 as v6

rng = np.random.default_rng(0)
n = 80
T = rng.uniform(15, 40, n)
I = rng.uniform(50, 180, n)
dm = pd.DataFrame({"file": [f"f{i}" for i in range(n)], "date": pd.date_range("2026-05-01", periods=n, freq="D").astype(str),
                   "T_pack_mean_avg": T, "peak_I_discharge": I,
                   "cell_spread_loaded_p95_mv": 10 + 0.1 * T + 0.05 * I + rng.normal(0, 0.3, n)})
dm["ens_outlier"] = False
dm["ens_outlier_v2"] = False
dm.loc[[3, 4, 5], "ens_outlier"] = True            # flagged by the v5 ensemble only: KEPT under the canonical rule
dm.loc[[10, 11], "ens_outlier_v2"] = True          # hard-rule invalid: EXCLUDED under the canonical rule
dm.loc[[10, 11], "cell_spread_loaded_p95_mv"] = 200.0   # planted gross outliers on the invalid rows
dm["cell_spread_loaded_p95_adj_hub_mv"] = 999.0    # stale values: the column must be FULLY rewritten

out, info = v6.m19b_huber_adjust(dm)
col = out["cell_spread_loaded_p95_adj_hub_mv"]
assert info["exclusion"] == "ens_outlier_v2" and "error" not in info
assert col.loc[[10, 11]].isna().all(), "v2-invalid rows must be NaN"
assert col.loc[[3, 4, 5]].notna().all(), "rows flagged only by ens_outlier are kept under ens_outlier_v2"
assert (col.dropna() != 999.0).all() and col.notna().sum() == n - 2, "column fully rewritten, NaN only outside E_new"
assert abs(info["huber_coef"]["bT"] - 0.1) < 0.02 and abs(info["huber_coef"]["bI"] - 0.05) < 0.01   # known answer
assert info["n_clean"] == n - 2

out2, info2 = v6.m19b_huber_adjust(dm, "ens_outlier")          # the former keep set: drops rows 3,4,5
assert info2["exclusion"] == "ens_outlier" and out2["cell_spread_loaded_p95_adj_hub_mv"].loc[[3, 4, 5]].isna().all()

out3, info3 = v6.m19b_huber_adjust(dm.drop(columns=["ens_outlier_v2"]))   # pre-v6 master: falls back to ens_outlier
assert info3["exclusion"] == "ens_outlier"
assert dm["cell_spread_loaded_p95_adj_hub_mv"].eq(999.0).all(), "input frame must not be mutated"
print("OK m19b: canonical keep set, full rewrite, known-answer coefficients, fallback, no input mutation")
