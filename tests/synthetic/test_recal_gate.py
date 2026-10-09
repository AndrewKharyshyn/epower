"""Known-answer tests for tools/recal_gate.py (run: python tests/synthetic/test_recal_gate.py)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
import numpy as np, pandas as pd
import recal_gate as rg

assert len(rg.RECAL_COLS) == 12 and "implied_offset_A_drive" not in rg.RECAL_COLS

# _judge: inside CI, small shift -> no flags; shift > 0.25 half-width -> soft; outside CI -> hard; drift on new-only -> hard
ci = (-1.0, 1.0)
j = rg._judge("x", 0.0, 0.1, 0.2, ci)
assert not j["soft_flag"] and not j["hard_new_outside_old_ci"] and not j["hard_drift_new_only_outside_old_ci"]
j = rg._judge("x", 0.0, 0.5, None, ci)
assert j["soft_flag"] and not j["hard_new_outside_old_ci"]
j = rg._judge("x", 0.0, 1.5, None, ci)
assert j["hard_new_outside_old_ci"]
j = rg._judge("x", 0.0, 0.1, 2.0, ci)
assert j["hard_drift_new_only_outside_old_ci"]

# ratio-of-sums bootstrap: constant per-row ratio -> degenerate CI equal to the ratio
d = pd.DataFrame({"date": ["a", "a", "b", "c"], "energy_residual_kwh": [0.01] * 4, "duration_s": [3600.0] * 4,
                  "V_pack_median": [300.0] * 4, "integr_time_h": [1.0] * 4, "f_domain_2p": [False] * 4})
num, den = rg._offset_parts(d, False)
ci, est = rg._boot_ratio(d["date"], num, den, np.random.default_rng(42))
assert abs(est - 10.0 / 300.0) < 1e-12 and abs(ci[0] - est) < 1e-12 and abs(ci[1] - est) < 1e-12
# M391: fit counts describe the rows the estimator fits on, not all rows (pass 2 drops f_domain_2p; a row without a residual is never eligible)
e = pd.DataFrame({"date": ["a", "a", "b", "c", "c"], "energy_residual_kwh": [0.01, 0.01, np.nan, 0.01, 0.01], "duration_s": [3600.0] * 5,
                  "V_pack_median": [300.0] * 5, "f_domain_2p": [False, True, False, False, False]})
assert rg._fit_counts(e, False) == {"n_drives": 4, "n_days": 2} and rg._fit_counts(e, True) == {"n_drives": 3, "n_days": 2}
assert rg._offset_eligible(e, False).sum() == 4 and (rg._offset_parts(e, True)[1] != 0).sum() == 3      # same rows feed the estimator
print("recal_gate tests ok")

# _block_null: observed batch beyond ALL distinct blocks gives p = 1/(n_blocks+1) (no spurious resolution), capped soft (<99 blocks)
rng = np.random.default_rng(1)
days = [f"2026-01-{i:02d}" for i in range(1, 31)]
so = pd.DataFrame({"date": np.repeat(days, 3), "x": rng.normal(size=90)})
fit = lambda s: np.array([s["x"].mean(), s["x"].std()])
bo = fit(so)
res = rg._block_null(so, fit, 5, 10, bo, bo + np.array([100.0, 100.0]), [0, 1], np.random.default_rng(42))
assert res["n_valid_blocks"] == 26 and abs(res["p"] - 1 / 27) < 1e-12 and abs(res["p_min"] - 1 / 27) < 1e-12
print("block_null tests ok")
