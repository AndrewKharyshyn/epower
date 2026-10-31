"""M546 G0 / KA2 / KA4 (analyses/M546_spec.md Rev 2): _esm_classify with strict_off=False equals the former classification, FROZEN VERBATIM below; with strict_off=True a second at exactly 400 rpm is 'off' (401 stays 'low', NaN stays unclassified, the limits
1400 / 2300 / 3200 stay '>='); the conservation identity on unrounded transition-matrix row sums of synthetic multi-drive frames (Rule off = stored off + n(exactly 400, last classified sample excluded), Rule low = stored low - n, other rows equal,
matrices differ only in the rows / columns of off and low); the default _engine_state_machine call is untouched by the flag; the recorded real-corpus G0 file (when present)."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import compute_summary_arrays as C

EDGES = [400, 1400, 2300, 3200]


# ---- FROZEN VERBATIM: the former _esm_classify (stored boundary rpm >= 400) ----
def old_classify(rpm):
    st = np.zeros(len(rpm), int)
    st[rpm >= EDGES[0]] = 1
    st[rpm >= EDGES[1]] = 2
    st[rpm >= EDGES[2]] = 3
    st[rpm >= EDGES[3]] = 4
    st[~np.isfinite(rpm)] = -1
    return st
# ---- end frozen ----


assert C._ESM_EDGES == EDGES and C._ESM_STATES == ["off", "low", "loadPoint", "mid", "high"]
r = np.random.default_rng(7)
for _ in range(200):
    x = r.choice([0.0, 399.0, 399.9, 400.0, 400.1, 401.0, 1399.0, 1400.0, 2299.0, 2300.0, 3199.0, 3200.0, 5000.0, np.nan], size=int(r.integers(1, 300)))
    assert (C._esm_classify(x) == old_classify(x)).all() and (C._esm_classify(x, strict_off=False) == old_classify(x)).all()
    s = C._esm_classify(x, strict_off=True)
    o = old_classify(x)
    d = np.where(s != o)[0]
    assert all(x[i] == 400.0 and o[i] == 1 and s[i] == 0 for i in d) and (x[d] == 400.0).all()
    assert ((x == 400.0).sum() == len(d))
# KA4
k = np.array([399.0, 400.0, 401.0, np.nan, 1400.0, 2300.0, 3200.0])
assert C._esm_classify(k).tolist() == [0, 1, 1, -1, 2, 3, 4] and C._esm_classify(k, strict_off=True).tolist() == [0, 0, 1, -1, 2, 3, 4]

# ---- conservation on synthetic multi-drive frames ----
RPM = "Оберти двигуна (rpm)"
PAT = {"a": [0] * 30 + [400.0] * 10 + [500.0] * 30 + [400.0] * 5 + [0] * 30 + [1500] * 20 + [399.0] * 10,
       "b": [0] * 25 + [400.0] * 7 + [2400.0] * 30 + [400.0] * 3 + [3300.0] * 15 + [400.0] * 4 + [800.0] * 20 + [0] * 15}


def frame(p):
    t = pd.date_range("2026-01-01 10:00:00", periods=len(p), freq="1s").strftime("%H:%M:%S.%f").str[:-3]
    return pd.DataFrame({"time": t, RPM: np.array(p, float)})


dm = pd.DataFrame({"file": list(PAT), "date": ["2026-01-01", "2026-01-02"]})
fl = lambda f: frame(PAT[f]).copy()
old = C._engine_state_machine(dm, None, frame_loader=fl)
new = C._engine_state_machine(dm, None, frame_loader=fl, strict_off=True)
assert C._engine_state_machine(dm, None, frame_loader=fl, strict_off=False) == old
n400_last_excl = sum(int((np.array(p[:-1]) == 400.0).sum()) for p in PAT.values())
n400_all = sum(int((np.array(p) == 400.0).sum()) for p in PAT.values())
To, Tn = np.array(old["transitionMatrix"]["counts"], float), np.array(new["transitionMatrix"]["counts"], float)
ro, rn = To.sum(1), Tn.sum(1)
assert rn[0] == ro[0] + n400_last_excl and rn[1] == ro[1] - n400_last_excl and (rn[2:] == ro[2:]).all()
mask = np.ones((5, 5), bool); mask[:2, :] = False; mask[:, :2] = False
assert (To[mask] == Tn[mask]).all() and not (To == Tn).all()
assert old["nDrivesCovered"] == new["nDrivesCovered"] == 2 and old["nDays"] == new["nDays"]
# the entry rate of EVERY state divides by the engine-on hours, which fall by n(exactly 400)/3600: the rate is not 'unchanged'
assert new["stateEdgesRpm"]["offBoundary"].startswith("rpm <= 400") and "offBoundary" not in old["stateEdgesRpm"]
assert "off rpm<=400" in new["methodology"] and "off rpm<400" in old["methodology"] and "low >400-1400" in new["methodology"]
assert "matches rpmDistribution.pooledPct[0]" in old["methodology"] and "matches rpmDistribution.pooledPct[0]" not in new["methodology"] and "not of engine time" in new["methodology"]
# the dwell-survival block keeps the stored boundary (it calls the classifier with its default)
import inspect
assert "_esm_classify(g['rpm'].values)" in inspect.getsource(C._engine_dwell_survival) and "strict_off=strict_off" in inspect.getsource(C._engine_state_machine)
# recorded real-corpus G0
p = "analyses/M546_g0.json"
if os.path.exists(p):
    g = json.load(open(p, encoding="utf-8"))
    assert g["gates"]["passed"] is True and g["masterMd5"].startswith("5556a0c6")
print("OK test_engine_state_machine_g0: frozen classifier, strict boundary, KA2 conservation on unrounded row sums, dwell survival on the stored boundary, recorded G0")
