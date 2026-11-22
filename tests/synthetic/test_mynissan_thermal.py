"""M734 known-answer tests (analyses/M734_spec.md Rev 2): planted offset, movement and drift rules, F3 closed form vs numerical integration,
F0 = F2 on identical forcing, split-conformal index, audit list, absent store skipped, frozen-file write refused."""
import json, os, subprocess, sys, tempfile
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import mynissan_thermal as th

# optional stage: no store -> skipped with exit 0
tmp = tempfile.mkdtemp()
assert th.main(["--store", os.path.join(tmp, "nostore"), "--out-dir", tmp]) == 0

# trapezoid: a linear ramp 10 -> 20 over 100 s sampled every 20 s has mean 15; a hole above 35 s is not bridged
ramp = [(t, 10 + 0.1 * t) for t in range(0, 101, 20)]
m, cov, span, n = th.trap(ramp)
assert abs(m - 15.0) < 1e-9 and cov == 100 and n == 6
m2, cov2, _, _ = th.trap([(0, 10.0), (20, 10.0), (100, 10.0), (120, 10.0)])
assert cov2 == 40 and abs(m2 - 10.0) < 1e-9

# movement start: needs 3 consecutive samples above the threshold with gaps <= 35 s
sp = [(0, 0.0), (30, 3.0), (60, 4.0), (90, 0.0), (120, 8.0), (150, 9.0), (180, 10.0)]
assert th.movement_start(sp, 0.0) == 120          # the first run (30, 60) has only two samples
assert th.movement_start([(0, 6.0), (30, 7.0), (60, 8.0)], 5.0) == 0 and th.movement_start([(0, 6.0), (30, 7.0), (60, 4.0)], 5.0) is None
assert th.movement_start([(0, 6.0), (100, 7.0), (130, 8.0)], 0.0) is None

# planted +1 C offset: an early warm bias of +4 C decaying over 150 s is removed by the 180 s cutoff, the remainder is the planted +1 C
amb = [(t, 12.0 + 1.0 + (4.0 * np.exp(-t / 60.0) if t < 150 else 0.0)) for t in range(0, 900, 30)]
s = th.screened_mean(amb, 0.0, 900.0, 180.0)
assert abs(s["mean"] - 13.0) < 1e-9 and not s["drift"] and s["n"] >= 5
assert th.screened_mean(amb, 0.0, 200.0, 180.0) is None                       # fewer than 5 samples after the cutoff
assert th.screened_mean(amb, None, 900.0, 180.0) is None                      # no sustained movement
drifting = [(t, 10.0 + (3.0 if t > 840 else 0.0)) for t in range(0, 900, 30)]
assert th.screened_mean(drifting, 0.0, 900.0, 180.0)["drift"] is True         # last minute spans 3 C > 1 C and > one quantum
assert th.screened_mean([(t, 10.0 + (1.0 if t > 840 else 0.0)) for t in range(0, 900, 30)], 0.0, 900.0, 180.0)["drift"] is False   # exactly one quantum: not flagged

# F3 closed form against numerical integration of dT/dt = -k (T - A(t))
T0, A0, A1, g, tau = 30.0, 10.0, 16.0, 5.0, 3.0
b, k, T, dt = (A1 - A0) / g, 1.0 / tau, T0, 1e-5
for i in range(int(g / dt)):
    t = i * dt
    T += dt * (-k * (T - (A0 + b * t)))
assert abs(th.f3_pred(T0, A0, A1, g, tau) - T) < 1e-3
# F0 = F2 on identical forcing (constant ambient, A0 = A1): the linear model collapses to the constant-forcing model
assert abs(th.f3_pred(T0, 12.0, 12.0 + 1e-9, g, tau) - th.f_const_pred(T0, 12.0, g, tau)) < 1e-6
# planted cooling: tau recovered by the L1 fit
rng = np.random.default_rng(3)
g_ = rng.uniform(0.5, 12, 200); A_ = rng.uniform(5, 20, 200); T0_ = A_ + rng.uniform(5, 15, 200)
y = th.f_const_pred(T0_, A_, g_, 7.0)
assert abs(th.fit_tau(lambda tt: th.f_const_pred(T0_[:, None], A_[:, None], g_[:, None], tt[None, :]), y) - 7.0) < 0.05

# split-conformal: index ceil((n+1)(1-a)) of the sorted absolute residuals
r = np.arange(1, 20) / 10.0                        # n = 19
assert abs(th.conformal_q(r, 0.1) - 1.8) < 1e-9    # ceil(20 * 0.9) = 18 -> the 18th value
assert th.conformal_q(r[:5], 0.1) == float("inf")  # ceil(6 * 0.9) = 6 > n = 5: no finite quantile

# closed audit list: a case with an ambient rise, a late first probe, a probe spread or gap activity is explained; the rest is unexplained
a = th.audit_case({"dA": 0.0, "first_probe_lag_s": 5.0, "spread": 0.5, "gap_speed_max": 0.0})
assert a["unexplained"] is True
assert th.audit_case({"dA": 2.5, "first_probe_lag_s": 5.0, "spread": 0.5, "gap_speed_max": 0.0})["unexplained"] is False
assert th.audit_case({"dA": 0.0, "first_probe_lag_s": 5.0, "spread": 3.0, "gap_speed_max": 0.0})["A3_probe_spread_gt_2C"] is True
assert th.audit_case({"dA": 0.0, "first_probe_lag_s": 5.0, "spread": 0.5, "gap_speed_max": 12.0})["unexplained"] is False
assert th.audit_case({"dA": None, "first_probe_lag_s": 5.0, "spread": 0.5, "gap_speed_max": 0.0})["unexplained"] is False

# the tool never writes a frozen winter file: the guard hook blocks an Edit on it
guard = os.path.join(ROOT, "tools", "guard_paths.py")
payload = json.dumps({"tool_input": {"file_path": "analyses/M717_winter_predictions.json"}})
rc = subprocess.run([sys.executable, guard], input=payload, text=True, capture_output=True).returncode
assert rc == 2
print("test_mynissan_thermal: OK")
