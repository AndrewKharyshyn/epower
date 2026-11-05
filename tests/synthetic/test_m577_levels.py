"""M577 known-answer tests (spec analyses/M577_spec.md Rev 1): CR2 coverage of a planted step, false-positive rate of the label ladder under S=0,
collinearity gate, PID-on-one-day identification, label precedence. Pure synthetic data; no repo data."""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import m577_cell_spread_levels as m   # noqa: E402


def synth(seed, s_eff=3.0, g=80, per=3, collinear=False, rho=0.0):
    rng = np.random.default_rng(seed)
    days = pd.date_range("2026-05-15", periods=g, freq="D")
    rows = []
    u_prev = 0.0
    for i, dt in enumerate(days):
        u_prev = rho * u_prev + rng.normal(0, 1.0)              # day effect (independent days by default: the CR2 cluster assumption; rho > 0 is the documented limit, covered by the week-block model E)
        for _ in range(per):
            rows.append({"date": dt, "day": str(dt.date()), "months": i / 30.4, "step": float(i >= g // 2), "T": 25 + rng.normal(0, 6), "I": 90 + rng.normal(0, 25),
                         "soc": 60 + rng.normal(0, 8), "socr": 20 + rng.normal(0, 4), "lrest": rng.normal(2, .5), "first": float(rng.random() < .3), "slow": float(rng.random() < .5), "e": u_prev + rng.normal(0, 1.5)})
    d = pd.DataFrame(rows)
    if collinear:
        d["slow"] = d["step"]
    d["y"] = 20 + 0.1 * d["months"] + 0.3 * (d["T"] - 25) + 0.02 * (d["I"] - 90) + s_eff * d["step"] + d["e"]
    d["wk"] = d["date"].dt.strftime("%G-%V")
    return d


# 1 coverage of the planted step (CR2 t(G-1)) and the planted-label path
cover, fp, n = 0, 0, 200
for i in range(n):
    r = m.fit_term(synth(1000 + i, 3.0), m.BASE, "step")
    cover += r["ci95"][0] <= 3.0 <= r["ci95"][1]
    r0 = m.fit_term(synth(5000 + i, 0.0), m.BASE, "step")
    fp += m.excl(r0["ci95"])
assert cover / n >= 0.93, ("coverage", cover / n)
assert fp / n <= 0.08, ("false positive rate", fp / n)
print("OK coverage", cover / n, "false-positive", fp / n)

# 1b documented limit: autocorrelated day effects (rho 0.5) undercover for a step regressor, which is why the label also requires the week-block model E
c2 = sum(m.fit_term(synth(9000 + i, 3.0, rho=0.5), m.BASE, "step")["ci95"][0] <= 3.0 <= m.fit_term(synth(9000 + i, 3.0, rho=0.5), m.BASE, "step")["ci95"][1] for i in range(100))
print("INFO coverage with rho=0.5:", c2 / 100)

# 2 label precedence on constructed inputs
A = {"est": 3.0, "ci95": [1.0, 5.0]}
agree = {"b": [0.5, 5.0], "c": [1.0, 4.0], "d": [0.2, 6.0], "e": [0.1, 6.0]}
assert m.label_term(A, agree, 1.5, False) == ("distinguishable from zero", [])
assert m.label_term(A, {**agree, "e": [-0.5, 6.0]}, 1.5, False)[0] == "procedure-dependent"
assert m.label_term(A, {**agree, "c": [-6.0, -1.0]}, 1.5, False)[0] == "procedure-dependent"          # opposite sign
assert m.label_term(A, {**agree, "c": None}, 1.5, False) == ("distinguishable from zero", ["c"])      # not evaluable is named, label on the evaluable set
assert m.label_term({"est": 0.4, "ci95": [-1.0, 1.8]}, agree, 1.5, False)[0].startswith("not distinguishable")
assert m.label_term(A, agree, 7.0, True)[0] == "not separable"                                          # R gate only
assert m.label_term(A, agree, 7.0, False)[0] == "distinguishable from zero"
print("OK label ladder")

# 3 collinearity gate: R == S gives an infinite VIF
d = synth(7, 3.0, collinear=True)
v = m.vif(d, m.BASE, "slow")
assert v > m.VIF_LIMIT
assert m.label_term({"est": 3.0, "ci95": [1.0, 5.0]}, {}, v, True)[0] == "not separable"
print("OK collinearity gate", v)

# 4 PID indicator on one day is not identified; on enough days it is testable
d = synth(9, 0.0, g=60)
d["date"] = pd.to_datetime(d["date"])
last = d["date"].max()
assert m.pid_identification(d, str(last.date()))["label"].startswith("not identified (P on 1 day")
assert m.pid_identification(d, str((last - pd.Timedelta(days=9)).date()))["label"] == "testable"
print("OK pid identification")

# 5 arm floor for the cold subset
d = synth(11, 0.0, g=20, per=1)
assert not m.arm_floor(d[d["step"] == 1].assign(step=1.0).iloc[:3].pipe(lambda x: pd.concat([x, d[d["step"] == 0]])))
assert m.arm_floor(synth(12, 0.0, g=40, per=1))
print("OK arm floor")
