"""M745 known-answer tests (analyses/M745_spec.md Rev 2): partition, the 3-factor Shapley accounting, gate G0, bootstrap mechanics and coverage on planted data.
No repository payload is read."""
import os, sys
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import m745_decomposition as M


def row(date, km, kwh, regime="shoulder", excluded=False):
    return {"date": date, "regime": regime, "km": km, "kwh": kwh, "km_seasonal": km, "ambient": 10.0, "drive_type": "urban", "excluded": excluded}


def state(rows, pub=None):
    return {"rows": rows, "published": pub or {"value": None, "n": None, "pairedKm": None}, "parsedBooleans": {}}


def V(rows):
    el = [r for r in rows.values() if M.eligible(r)]
    return 100.0 * sum(r["kwh"] for r in el) / sum(r["km"] for r in el)


# 1 additions only: the whole step is f3
s0 = state({"a": row("2026-01-01", 10, 3), "b": row("2026-01-02", 10, 3)})
s1 = state({"a": row("2026-01-01", 10, 3), "b": row("2026-01-02", 10, 3), "c": row("2026-01-03", 30, 3), "d": row("2026-01-04", 10, 1)})
d = M.run_decomposition(s0, s1, nb=300)
assert d["counts"]["A"] == 2 and d["counts"]["R"] == 0 and d["counts"]["reasonA"]["new_file"] == 2
assert abs(d["total"] - (V(s1["rows"]) - V(s0["rows"]))) < 1e-12
assert abs(d["contributions"]["f3_added"]["value"] - d["total"]) < 1e-12 and d["contributions"]["f1_values_rederived"]["value"] == 0.0 and d["contributions"]["f2_removed"]["value"] == 0.0
assert abs(d["identity"]["reconstructed"] - d["V_S1"]) < 1e-12, "V(S1) = (1-w) V_C + w V_A"

# 2 re-derived values only: the whole step is f1 (same files, kWh re-derived)
s0 = state({"a": row("2026-01-01", 10, 3), "b": row("2026-01-02", 10, 5)})
s1 = state({"a": row("2026-01-01", 10, 2), "b": row("2026-01-02", 10, 4)})
d = M.run_decomposition(s0, s1, nb=300)
assert abs(d["contributions"]["f1_values_rederived"]["value"] - (V(s1["rows"]) - V(s0["rows"]))) < 1e-12 and d["contributions"]["f3_added"]["value"] == 0.0
assert d["f1ColumnSplit"] is not None and abs(d["f1ColumnSplit"]["kmColumn"]) < 1e-12 and abs(d["f1ColumnSplit"]["kwhColumn"] - d["f1ColumnSplit"]["totalCommon"]) < 1e-12

# 3 removal only (a drive turns non-shoulder: membership change)
s0 = state({"a": row("2026-01-01", 10, 3), "b": row("2026-01-02", 10, 5)})
s1 = state({"a": row("2026-01-01", 10, 3), "b": row("2026-01-02", 10, 5, regime="cold")})
d = M.run_decomposition(s0, s1, nb=300)
assert d["counts"]["R"] == 1 and d["counts"]["reasonR"]["membership_change"] == 1
assert abs(d["contributions"]["f2_removed"]["value"] - (V(s1["rows"]) - V(s0["rows"]))) < 1e-12

# 4 mix with a hand-computed two-player Shapley (f1 unchanged; one removal r, one addition a)
s0 = state({"c": row("2026-01-01", 10, 3), "r": row("2026-01-02", 10, 5)})
s1 = state({"c": row("2026-01-01", 10, 3), "a": row("2026-01-03", 10, 1)})
d = M.run_decomposition(s0, s1, nb=300)
v = lambda keep: 100 * sum(x[1] for x in keep) / sum(x[0] for x in keep)
c, r, a = (10, 3), (10, 5), (10, 1)
v00 = v([c, r]); v10 = v([c]); v01 = v([c, r, a]); v11 = v([c, a])
sh_f2 = 0.5 * ((v10 - v00) + (v11 - v01)); sh_f3 = 0.5 * ((v01 - v00) + (v11 - v10))
assert abs(d["contributions"]["f2_removed"]["value"] - sh_f2) < 1e-12 and abs(d["contributions"]["f3_added"]["value"] - sh_f3) < 1e-12
assert abs(sh_f2 + sh_f3 - (v11 - v00)) < 1e-12
for order in d["sequential"].values():
    assert abs(sum(order.values()) - d["total"]) < 1e-9
dd = d["detailByReason"]
assert abs(sum(x["value"] for x in dd.values()) - d["total"]) < 1e-9

# 5 gate G0 on a planted pair
rows = {"a": row("2026-01-01", 10, 3), "b": row("2026-01-02", 10, 5), "x": row("2026-01-03", 10, 99, excluded=True), "y": row("2026-01-03", 10, 99, regime="warm")}
good = state(rows, {"value": 40.0, "n": 2, "pairedKm": 20.0}); bad = state(rows, {"value": 40.5, "n": 2, "pairedKm": 20.0})
assert M.g0(good, 40.0)["pass"] and not M.g0(bad, 40.5)["pass"] and not M.g0(good, 41.0)["pass"], "the kpis.jsonl value is part of the gate (C1)"
assert not M.g0(state(rows, {"value": 40.0, "n": 3, "pairedKm": 20.0}))["pass"]

# 6 bootstrap mechanics on a three-day example (hand computation)
num = np.array([3.0, 5.0, 2.0]); den = np.array([10.0, 20.0, 5.0])
groups = {"C0": {"num": num, "den": den}, "C1": {"num": num, "den": den}}
for w, expect in (([1, 1, 1], 100 * 10 / 35), ([3, 0, 0], 30.0), ([0, 2, 1], 100 * 12 / 45)):
    got = M.cell_value(groups, np.array([w], float), set(), False)
    assert abs(float(got[0]) - expect) < 1e-12, (w, got, expect)
W = M.draws(3, 50, 42)
assert W.shape == (50, 3) and (W.sum(1) == 3).all()
assert np.array_equal(W, M.draws(3, 50, 42)), "deterministic for the seed"
assert np.isnan(M.cell_value(groups, np.array([[0, 0, 0]], float), set(), False)[0]), "zero km draws give NaN (counted, C6)"

# 7 empty cell: no added drives -> exploratory, contribution 0; overall precedence (C5)
s0 = state({"a": row("2026-01-01", 10, 3), "b": row("2026-01-02", 10, 5)})
d = M.run_decomposition(s0, state(dict(s0["rows"])), nb=200)
assert d["total"] == 0.0 and d["contributions"]["f3_added"]["reading"].startswith("exploratory")
assert M.overall({"f1": "not distinguishable from 0", "f2": "x", "f3": "not distinguishable from 0"}, [0.0, 0.0]).startswith("step not distinguishable")
assert M.overall({"f1": "contributes", "f2": "x", "f3": "accounts for the step"}, [-5.0, -1.0]) == "mixed (dominant added drives)"
assert M.overall({"f1": "not distinguishable from 0", "f2": "x", "f3": "not distinguishable from 0"}, [-5.0, -1.0]) == "not attributable"

# 8 Kish effective days and reading rule (C4)
assert abs(M.kish(np.array([1.0, 1.0, 1.0, 1.0])) - 4.0) < 1e-12 and M.kish(np.array([0.0])) == 0.0
assert M.read_factor(-7.0, [-9.0, -5.0], -7.4, [-9, -5], 6.0) == "accounts for the step"
assert M.read_factor(-2.0, [-3.0, -1.0], -7.4, [-9, -5], 6.0) == "contributes"
assert M.read_factor(-7.0, [-9.0, 1.0], -7.4, [-9, 1], 6.0) == "not distinguishable from 0"
assert M.read_factor(-7.0, [-9.0, -5.0], -7.4, [-9, -5], 4.0).startswith("exploratory")

# 9 coverage on a planted null (spec C3 c1): S0 is a random 60 % of the drives of S1, no true step; the interval of the total excludes 0 in 2-8 % of datasets
rng = np.random.default_rng(7); excl = 0; nsim = 300
for _ in range(nsim):
    rows1 = {}
    for day in range(40):
        eff = rng.normal(0, 3)
        for k in range(int(rng.integers(1, 4))):
            km = float(rng.uniform(3, 25))
            rows1["d%d_%d" % (day, k)] = row("2026-%02d-%02d" % (day // 28 + 1, day % 28 + 1), km, km * (20 + eff + rng.normal(0, 4)) / 100.0)
    keys = list(rows1); keep = set(rng.choice(keys, size=int(0.6 * len(keys)), replace=False).tolist())
    s0 = state({k: v for k, v in rows1.items() if k in keep}); s1 = state(rows1)
    d = M.run_decomposition(s0, s1, nb=300)
    lo, hi = d["total_ci95"]
    excl += int(lo > 0 or hi < 0)
rate = excl / nsim
print("planted-null exclusion rate", rate)
assert 0.02 <= rate <= 0.08, rate
print("test_m745_decomposition: OK")
