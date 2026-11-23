"""M751 known-answer tests (analyses/M751_spec.md Rev 2): class-to-set mapping, strict ordered join with reason codes, set memberships (D1 at 1 km), pairing from a
planted trajectory table, planted contamination recovered with the right sign and an interval that excludes zero, a planted null gives a shift interval containing zero,
the support floor suppresses intervals, tau recovered on a planted exponential for the paired decay-rate difference, overall wording rule, control V0 detects a perturbed
published block, reproducible bootstrap, optional-stage skip. No raw files or cloud store needed."""
import os, sys, tempfile
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import heatsoak_gap_sensitivity as H

# optional stage: no gap table -> skipped with exit 0
tmp = tempfile.mkdtemp()
assert H.main(["--gaps", os.path.join(tmp, "none.csv"), "--out-dir", tmp]) == 0

# class to set mapping
assert H.CLASS_SET["stationary_consistent"] == "S" and H.CLASS_SET["driving_observed"] == "D" and H.CLASS_SET["odometer_increase_only"] == "D"
assert H.CLASS_SET["uncertain"] == "U" and H.CLASS_SET["export_break"] == "X" and H.CLASS_SET["no_cloud_data"] == "X" and H.CLASS_SET["no_cloud_row"] == "X"


def sen(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    i, j = np.triu_indices(len(x), 1)
    dx = x[j] - x[i]
    ok = dx != 0
    return float(np.median((y[j] - y[i])[ok] / dx[ok]))


# pairing from a planted trajectory table: pack 30 C at the end of drive 1, 24 C at the start of drive 2 after 2 h; ambient 20 C -> retained 0.4; drive 3 has no trajectory
t0 = pd.Timestamp("2026-06-01 08:00")
d = pd.DataFrame({"file": ["a", "b", "c"], "ts_full": [t0, t0 + pd.Timedelta(hours=3), t0 + pd.Timedelta(hours=6)],
                  "te_full": [t0 + pd.Timedelta(hours=1), t0 + pd.Timedelta(hours=4), t0 + pd.Timedelta(hours=7)]})
traj = {"a": {"pm_end": 30, "pm_start": 25}, "b": {"pm_end": 28, "pm_start": 24}}
pf = H.build_pairs(d, traj, {"b": 20.0, "a": 20.0})
assert len(pf) == 1 and pf.iloc[0]["prev"] == "a" and pf.iloc[0]["next"] == "b" and abs(pf.iloc[0]["gapH"] - 2.0) < 1e-9
assert abs(pf.iloc[0]["retainedFrac"] - 0.4) < 1e-9 and pf.iloc[0]["dayArrival"] == "2026-06-01" and pf.iloc[0]["shedC"] == 6

# strict ordered join with reason codes and reconciliation
pf2 = pd.DataFrame({"prev": ["a", "b", "c", "d"], "next": ["b", "c", "d", "e"], "gapH": [1.0, 2.0, 3.0, 4.0]})
gaps = pd.DataFrame({"prev": ["a", "b", "x"], "next": ["b", "c", "y"], "gap_h": [1.005, 2.5, 9.0], "class": ["stationary_consistent", "driving_observed", "uncertain"],
                     "moved_km": [0.0, 3.0, 0.0], "last_move_to_next_h": [1.0, 0.5, 1.0]})
m, rec = H.join_classes(pf2, gaps)
assert list(m["cls"]) == ["stationary_consistent", "no_cloud_row", "no_cloud_row", "no_cloud_row"]
assert list(m["reason"]) == ["", "gap_mismatch", "no_m729_row", "no_m729_row"] and list(m["set"]) == ["S", "X", "X", "X"]
assert rec == {"pairs": 4, "m729_gaps": 3, "matched": 1, "no_m729_row": 2, "gap_mismatch": 1, "m729_gaps_without_a_pair": 1}
try:
    H.join_classes(pd.DataFrame({"prev": ["a", "a"], "next": ["b", "c"], "gapH": [1.0, 2.0]}), gaps)
    raise SystemExit("a drive appearing twice as previous must stop")
except H.Stop:
    pass
try:
    H.join_classes(pf2, pd.concat([gaps, gaps.iloc[:1]]))
    raise SystemExit("duplicate gap rows must stop")
except H.Stop:
    pass

# memberships: D1 needs at least 1 km of movement
mm = pd.DataFrame({"set": ["S", "D", "D", "U", "X"], "moved_km": [0, 0.2, 3.0, 0, 0]})
mk = H.masks(mm)
assert list(mk["B"]) == [True, False, False, False, False] and list(mk["C"]) == [True, False, False, True, True]
assert list(mk["D1"]) == [False, False, True, False, False] and list(mk["C1"]) == [True, True, False, True, True] and mk["A"].all()

# planted contamination: half of the pairs in the 6-12 h bin are D pairs with a retained fraction 0.40 higher; clean pairs 0.40
rng = np.random.default_rng(3)
n_days, per = 60, 6
rows = []
for dday in range(n_days):
    for k in range(per):
        is_d = k % 2 == 0
        rows.append({"gapH": rng.uniform(6.2, 11.8), "retainedFrac": float(rng.normal(0.80 if is_d else 0.40, 0.10)), "set": "D" if is_d else "S", "moved_km": 3.0 if is_d else 0.0,
                     "dayArrival": "2026-07-%02d" % (dday % 28 + 1) if dday < 28 else "2026-08-%02d" % (dday - 27), "dayDeparture": "x", "initExcessC": 8.0,
                     "residExcessC": 4.0, "shedC": 3.0})
pl = pd.DataFrame(rows)
e = H.e2_bins(pl, H.masks(pl), "dayArrival", nb=400)
b6 = [r for r in e if r["gapLoH"] == 6][0]
assert b6["B"]["supported"] and b6["B"]["shiftPp"] > 15 and b6["B"]["ci95Pp"][0] > 0 and b6["B"]["verdict"] == "material", b6["B"]
assert b6["C"]["shiftPp"] > 15 and b6["C"]["verdict"] == "material" and b6["B"]["relativeShift"] > 0.2 and b6["B"]["mdePp"] > 0
# planted null: D pairs drawn from the same distribution as S pairs -> interval contains zero
pn = pl.copy()
pn["retainedFrac"] = rng.normal(0.40, 0.10, len(pn))
en = H.e2_bins(pn, H.masks(pn), "dayArrival", nb=400)
bn = [r for r in en if r["gapLoH"] == 6][0]
assert bn["B"]["ci95Pp"][0] <= 0 <= bn["B"]["ci95Pp"][1] and bn["B"]["verdict"] == "not distinguishable", bn["B"]
# support floor: 12 pairs in the bin -> no interval, wording says not estimable
ps = pl.iloc[:12].copy()
es = [r for r in H.e2_bins(ps, H.masks(ps), "dayArrival", nb=100) if r["gapLoH"] == 6][0]
assert es["B"]["supported"] is False and "ci95Pp" not in es["B"] and es["B"]["verdict"] == "not estimable at this support"
# thresholds
assert H.verdict_shift(6.0, 2.0, 10.0, True) == "material" and H.verdict_shift(3.0, 1.0, 5.0, True) == "small"
assert H.verdict_shift(8.0, -1.0, 17.0, True) == "not distinguishable" and H.verdict_shift(8.0, 1.0, 9.0, False).startswith("not estimable")
# bootstrap reproducible for a fixed seed
r = pl["retainedFrac"].to_numpy(); cl = pl["dayArrival"].to_numpy(); ins = {"B": (pl["set"] == "S").to_numpy()}
d1, _ = H.paired_median_diffs(r, ins, cl, 50, 42)
d2, _ = H.paired_median_diffs(r, ins, cl, 50, 42)
assert np.array_equal(d1["B"], d2["B"])

# tau on a planted exponential (k = 0.10 per hour) for clean pairs and a slower decay for D pairs; the paired decay-rate difference has the right sign
rng = np.random.default_rng(11)
gh = rng.uniform(0.5, 30, 260)
isd = rng.random(260) < 0.45
k_true = np.where(isd, 0.03, 0.10)
init = np.full(260, 10.0)
resid = init * np.exp(-k_true * gh + rng.normal(0, 0.05, 260))
days = np.array(["2026-06-%02d" % (1 + i % 28) for i in range(260)])
pt = pd.DataFrame({"gapH": gh, "initExcessC": init, "residExcessC": resid, "retainedFrac": resid / init, "dayArrival": days, "dayDeparture": days,
                   "prev": ["p%d" % i for i in range(260)], "next": ["n%d" % i for i in range(260)], "set": np.where(isd, "D", "S"), "moved_km": np.where(isd, 3.0, 0.0)})
tB, fB = H.tau_set(pt[pt["set"] == "S"], sen, nb=200)
assert abs(tB["decayRateK"] - 0.10) < 0.01 and tB["nFit"] == int((pt["set"] == "S").sum()) and abs(tB["tauH"] - 10.0) < 1.0
tA, fA = H.tau_set(pt, sen, nb=200)
assert tA["decayRateK"] < tB["decayRateK"]
dd = H.paired_k_diff(fA, {"B": (fA["set"] == "S").to_numpy()}, sen, 200, 42)
lo, hi = np.percentile(dd["B"], [2.5, 97.5])
# Sen's slope is robust: the 45 % slow-decay pairs move the pooled decay rate by only about 6 %, so the shift is positive with an interval above zero but inside the 0.80-1.25 band: "small"
assert lo > 0 and 0.8 < tA["decayRateK"] / tB["decayRateK"] < 1.25 and H.verdict_k(tA["decayRateK"], tB["decayRateK"], lo, hi) == "small"
assert H.verdict_k(0.06, 0.10, 0.02, 0.06) == "material" and H.verdict_k(0.06, 0.10, -0.01, 0.06) == "not distinguishable"
assert H.verdict_k(0.09, 0.10, -0.01, 0.02) == "not distinguishable" and H.verdict_k(0.10, 0.101, 0.001, 0.003) == "small" and H.verdict_k(None, 0.1, 0, 1) == "not estimable"
# fewer than 8 pairs after the filter: not estimable
assert "not estimable" in H.tau_set(pt.iloc[:5], sen, nb=50)[0]["status"]

# overall wording rule
sup = {"B": {"supported": True, "verdict": "small"}, "C": {"supported": True, "verdict": "small"}}
assert H.overall([sup, sup], {}).startswith("not established")
assert H.overall([sup, sup, sup], {"B": {"verdictK": "small"}, "C": {"verdictK": "small"}}).startswith("no material shift detected at this support (lower bound)")
mat = {"B": {"supported": True, "verdict": "material"}, "C": {"supported": True, "verdict": "material"}}
assert H.overall([mat, sup, sup], {}).startswith("sensitive to unlogged driving (lower bound)")
only_b = {"B": {"supported": True, "verdict": "material"}, "C": {"supported": True, "verdict": "small"}}
assert H.overall([only_b, sup, sup], {}).startswith("mixed")

# control V0: a published block built from the same pairs passes, a perturbed one is detected
pv = pt.copy()
bins = []
for lo_, hi_ in H.BINS:
    sub = pv[H.bin_rows(pv, lo_, hi_)]
    if not len(sub):
        continue
    rf = sub["retainedFrac"].dropna()
    pv.loc[sub.index, "shedC"] = 3.0
    bins.append({"gapLoH": lo_, "gapHiH": None if hi_ > 1e8 else hi_, "n": int(len(sub)), "nAmb": int(len(rf)), "medShedC": 3.0, "medRetainedFrac": round(float(rf.median()), 4)})
tt, _ = H.tau_set(pv, sen, 200)
pub = {"nPairs": len(pv), "nPairsAmbient": int(pv["retainedFrac"].notna().sum()), "gapBins": bins, "tauFitN": tt["nFit"], "soakDecayRateK": tt["decayRateK"], "soakDecayRateKCI": tt["decayRateKCI"]}
assert H.v0_compare(pv, pub, sen, 200) == []
bad = dict(pub, gapBins=[dict(bins[0], medRetainedFrac=0.5)] + bins[1:])
assert any("medRetainedFrac" in x for x in H.v0_compare(pv, bad, sen, 200))
print("test_heatsoak_gap_sensitivity: OK")
