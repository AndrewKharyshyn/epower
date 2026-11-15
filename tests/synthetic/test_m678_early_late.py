"""M678 (N-04, spec analyses/M677_spec.md Rev 1.1/1.2): known-answer test of tools/early_late_contrast.py on planted data.
Cases: planted early-late shift recovered with the interval covering it; a pure covariate shift gives a matched difference near zero while the unmatched one is large; a cell without overlap is not used;
day clustering widens the interval relative to independent drives when a day effect is planted; Path A and Path B agree on a planted linear design; edges never see an outcome (V5); determinism; the show rule;
stage wiring. Run: python tests/synthetic/test_m678_early_late.py"""
import inspect, json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import numpy as np
import pandas as pd
import early_late_contrast as C

rng = np.random.default_rng(3)

def frame(n, day0, ndays, shift=0.0, tshift=0.0, dayeff=0.0, beta_t=0.0):
    days = rng.integers(0, ndays, n)
    de = rng.normal(0, 1, ndays) * dayeff
    T = rng.normal(15 + tshift, 4, n); I = rng.normal(100, 20, n); S = rng.normal(60, 4, n)
    y = 10 + beta_t * T + shift + de[days] + rng.normal(0, 0.5, n)
    dd = pd.to_datetime(day0) + pd.to_timedelta(days, unit="D")
    return pd.DataFrame({"file": ["f%d" % i for i in range(n)], "date": dd, "day": dd.strftime("%Y-%m-%d"), "T": T, "I": I, "S": S, "dist": rng.uniform(1, 40, n),
                         "reg": rng.choice(["fast", "slow"], n), "Y2": y})

# ---- case 1: planted shift 2.0 recovered; interval covers it ----
e = frame(300, "2026-05-15", 40); l = frame(300, "2026-09-11", 40, shift=2.0)
pa = C.path_a(e, l, "Y2", nboot=800)
masks = pa.pop("_cellsMask")
assert pa["status"] == "computed" and pa["ci95"][0] <= 2.0 <= pa["ci95"][1] and abs(pa["estimate"] - 2.0) < 0.3, pa
assert abs(pa["unadjustedLateMinusEarly"] - 2.0) < 0.3

# ---- case 2: covariate shift only (late drives hotter, outcome depends on T only): matched estimate far smaller than the unmatched one ----
e2 = frame(400, "2026-05-15", 50, beta_t=1.0); l2 = frame(400, "2026-09-11", 50, tshift=3.0, beta_t=1.0)
p2 = C.path_a(e2, l2, "Y2", nboot=500); p2.pop("_cellsMask")
assert abs(p2["unadjustedLateMinusEarly"]) > 2.0 and abs(p2["estimate"]) < 0.4 * abs(p2["unadjustedLateMinusEarly"]), p2          # coarse cells leave within-cell residual confounding; the matched estimate is much smaller than the unmatched one

# ---- case 3: no overlap -> not shown ----
e3 = frame(120, "2026-05-15", 30); l3 = frame(120, "2026-09-11", 30, tshift=40.0)
p3 = C.path_a(e3, l3, "Y2", nboot=100)
assert p3["status"] == "not shown"

# ---- case 4: day clustering widens the interval relative to independent drives ----
e4 = frame(240, "2026-05-15", 12, dayeff=2.0); l4 = frame(240, "2026-09-11", 12, dayeff=2.0)
p4 = C.path_a(e4, l4, "Y2", nboot=800); p4.pop("_cellsMask")
e5 = e4.copy(); l5 = l4.copy(); e5["day"] = ["u%d" % i for i in range(len(e5))]; l5["day"] = ["v%d" % i for i in range(len(l5))]
p5 = C.path_a(e5, l5, "Y2", nboot=800); p5.pop("_cellsMask")
assert (p4["ci95"][1] - p4["ci95"][0]) > 1.5 * (p5["ci95"][1] - p5["ci95"][0])

# ---- case 5: Path A and Path B agree on a planted linear design ----
pb = C.path_b(e, l, "Y2", masks)
assert pb["status"] == "computed" and abs(pb["estimate"] - 2.0) < 0.4 and pb["ci95"][0] <= 2.0 <= pb["ci95"][1]
assert pb["ci98_33"][0] < pb["ci95"][0] and pb["ci98_33"][1] > pb["ci95"][1]

# ---- case 6: V5 the edge function never receives an outcome; edges are right-closed with the lowest bin closed ----
sig = inspect.signature(C.make_edges)
assert list(sig.parameters) == ["T", "I", "S", "level"]
ed = C.make_edges(np.arange(100.0), np.arange(100.0), np.arange(100.0), C.LEVELS[1])
x = pd.DataFrame({"T": [0.0, 33.0, 34.0], "I": [0.0, 33.0, 34.0], "S": [0.0, 33.0, 34.0], "reg": ["fast", "fast", "fast"], "dist": [1, 1, 1]})
k = C.assign(x, ed, C.LEVELS[1])
assert k[0] == k[1] != k[2]                  # right-closed: an edge value (33) stays in the lower bin; the lowest bin is closed

# ---- case 6b: the regime coding is the same in frames with different regimes present (early all slow, late mixed) ----
xe = pd.DataFrame({"T": [10.0], "I": [100.0], "S": [60.0], "reg": ["slow"], "dist": [1]}); xl = pd.DataFrame({"T": [10.0, 10.0], "I": [100.0, 100.0], "S": [60.0, 60.0], "reg": ["fast", "slow"], "dist": [1, 1]})
ke_, kl_ = C.assign(xe, ed, C.LEVELS[1]), C.assign(xl, ed, C.LEVELS[1])
assert ke_[0] == kl_[1] and kl_[0] != kl_[1]

# ---- case 7: determinism ----
a = C.path_a(e, l, "Y2", nboot=200); a.pop("_cellsMask"); b = C.path_a(e, l, "Y2", nboot=200); b.pop("_cellsMask")
assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

# ---- case 8: covariate-only ladder: a coarser level is chosen when the finer one matches less than 50 % ----
(lv, _, _, _, _, share), reached = C.choose_level(e3, l3)
assert lv["name"] == "3x3x3x2" and not reached and share < 0.5
(lv1, _, _, _, _, sh1), r1 = C.choose_level(e, l)
assert r1 and sh1 >= 0.5

# ---- stage wiring and language rule ----
ids = [s["id"] for s in json.load(open("tools/ingest_stages.json", encoding="utf-8"))["stages"]]
assert ids.index("change_points") < ids.index("early_late_contrast") < ids.index("stamp_basis")
import language_gate as G
rule = {x.rid: x for x in G.RULES}["M677-early-late-wording"]
assert rule.hits("the early vs late ageing between windows") and rule.hits("the matched difference is a capacity fade") and rule.hits("the matched contrast shows a resistance increase") and not rule.hits("difference between early and late drives in matched state bins")
rule3 = {x.rid: x for x in G.RULES}["M678-cap-ah-est-wording"]
assert rule3.hits("cap_ah_est (apparent Ah per 100 % SOC)") and not rule3.hits("cap_ah_est is a voltage proxy scaled by an assumed energy")
print("PASS test_m678_early_late")
