"""M428 known-answer test (spec analyses/M428_spec.md Rev 2): tools/m428_oot.py on synthetic hazards with a KNOWN truth.
A: no shift -> D1 PASS, D2 within, D3 not material, outcome 'no material out-of-time degradation detected'.
B: planted calibration shift (later hazard x1.7) -> O/E interval above the band -> D2 MATERIAL -> 'refit criterion met'.
C: planted support shift (later pack temperature far below the basis) -> D3 MATERIAL for tpack -> 'refit criterion met'.
D: outcome independent of every predictor -> no skill -> D1 FAIL -> 'refit criterion met'.
E: large day-to-day random effect with few later days -> uninformative O/E interval -> D2 not 'within' -> never the positive sentence.
Also: pure decision functions (three-state D2, per-predictor excess D3) and the jackknife / bootstrap interval of a constant-ratio case."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import m428_oot as O

# ---- pure decision functions
assert O.d_states([0.01, 0.05], [0.9, 1.1], {"tpack": {"excessPp": 3.0}}) == ("PASS", "within", "not material")
assert O.d_states([-0.01, 0.05], [0.9, 1.1], {"tpack": {"excessPp": 3.0}})[0] == "FAIL"
assert O.d_states([0.01, 0.05], [0.6, 1.4], {"tpack": {"excessPp": 3.0}})[1] == "indeterminate"      # wide interval is never 'within'
assert O.d_states([0.01, 0.05], [1.3, 1.6], {"tpack": {"excessPp": 3.0}})[1] == "MATERIAL"
assert O.d_states([0.01, 0.05], [0.5, 0.7], {"tpack": {"excessPp": 3.0}})[1] == "MATERIAL"
assert O.d_states([0.01, 0.05], [0.9, 1.1], {"soc": {"excessPp": 2.0}, "tpack": {"excessPp": 10.5}})[2] == "MATERIAL"
assert O.d_states([0.01, 0.05], [0.9, 1.1], {"soc": {"excessPp": 9.9}})[2] == "not material"

# ---- constant-ratio case: O/E exactly 2 on every day -> point 2, jackknife and bootstrap intervals collapse around 2
rng0 = np.random.default_rng(1)
day = np.repeat(np.arange(8), 200)
p = np.full(len(day), 0.02)
y = np.zeros(len(day))
for d in range(8):
    idx = np.where(day == d)[0]
    y[idx[:8]] = 1.0                                   # 8 events per 200 seconds = 0.04 = 2 x 0.02
pc = O.Pieces(day, y, p, p, p)
assert abs(pc.point()["OE"] - 2.0) < 1e-9
ci, und = pc.boot(200, 42)
assert abs(ci["OE"][0] - 2.0) < 1e-9 and abs(ci["OE"][1] - 2.0) < 1e-9 and und["OE"] == 0
jk = pc.jackknife()
assert abs(jk["OE"]["tInterval"][0] - 2.0) < 1e-6 and jk["OE"]["df"] == 7


# ---- synthetic tables
def make(n_days, seed, per_day=2500, shift=1.0, tshift=0.0, signal=True, day_sd=0.0, start_day=0, n_files=5):
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(n_days):
        d = start_day + k
        n = per_day
        soc = rng.uniform(30, 80, n); speed = rng.uniform(0, 120, n); tpack = rng.uniform(20, 45, n) + tshift
        demand = rng.gamma(2.0, 3.0, n); dur = rng.exponential(30.0, n) + 1
        eta = -3.2 + (0.045 * (soc - 55) - 0.012 * (speed - 60) + 0.03 * (tpack - 32) + 0.06 * demand - 0.4 * np.log1p(dur)) * (1.0 if signal else 0.0)
        eta = eta + np.log(shift) + (rng.normal(0, day_sd) if day_sd else 0.0)
        haz = 1 - np.exp(-np.exp(eta))
        y = (rng.uniform(size=n) < haz).astype(float)
        f = ["syn_%03d_%d.csv" % (d, i % n_files) for i in range(n)]
        rows.append(pd.DataFrame({"soc": soc, "speed": speed, "tpack": tpack, "demand": demand, "durationS": dur, "y": y,
                                  "day": "2026-06-%02d" % (d + 1) if d < 28 else "2026-07-%02d" % (d - 27), "file": f}))
    return pd.concat(rows, ignore_index=True)


def run(basis_days, later_days, **kw):
    seed = kw.pop("seed", 7)
    tb = make(basis_days, seed)
    tl = make(later_days, seed + 1, start_day=basis_days, **kw)
    tbl = pd.concat([tb, tl], ignore_index=True)
    files = list(dict.fromkeys(tbl["file"]))
    basis = list(dict.fromkeys(tb["file"]))
    return O.evaluate_side(tbl, basis, files, b=200, seed=42, sens=False)


A = run(24, 8)
assert A["primary"]["states"]["D1"] == "PASS" and A["primary"]["states"]["D3"] == "not material", A["primary"]["states"]
assert A["primary"]["states"]["D2"] == "within", (A["primary"]["states"], A["primary"]["ci95Percentile"]["OE"])
assert A["decision"]["outcome"].startswith("no material out-of-time degradation detected"), A["decision"]["outcome"]

B = run(24, 8, shift=1.7)
assert B["primary"]["states"]["D2"] == "MATERIAL" and B["decision"]["outcome"].startswith("refit criterion met"), (B["primary"]["states"], B["primary"]["ci95Percentile"]["OE"])
assert B["primary"]["ci95Percentile"]["OE"][0] > 1.25

C = run(24, 8, tshift=-14.0)
assert C["primary"]["states"]["D3"] == "MATERIAL" and C["decision"]["outcome"].startswith("refit criterion met"), (C["primary"]["states"], C["support"]["perPredictor"]["tpack"])
assert C["support"]["perPredictor"]["tpack"]["excessPp"] > 10.0 and C["support"]["perPredictor"]["soc"]["excessPp"] < 3.0

D = run(24, 8, signal=False)
assert D["primary"]["states"]["D1"] == "FAIL" and D["decision"]["outcome"].startswith("refit criterion met"), (D["primary"]["states"], D["primary"]["ci95Percentile"]["skillVsB0"])

E = run(24, 4, day_sd=0.7, seed=11)
assert E["primary"]["states"]["D2"] != "within" or not E["decision"]["outcome"].startswith("no material"), E["primary"]["ci95Percentile"]["OE"]
assert not (E["primary"]["states"]["D2"] == "indeterminate" and E["decision"]["outcome"].startswith("no material")), "an uninformative interval must never give the positive sentence"

# sensitivities branch executes and is internally consistent (bands, halves, S1, in/out of support, S3)
tb = make(24, 7); tl = make(8, 8, start_day=24)
tt = pd.concat([tb, tl], ignore_index=True)
F = O.evaluate_side(tt, list(dict.fromkeys(tb["file"])), list(dict.fromkeys(tt["file"])), b=100, seed=42, sens=True)
S = F["sensitivities"]
assert sum(b_["atRiskSeconds"] for b_ in S["OEbyPackTemperatureBand"]) == F["primary"]["atRiskSeconds"]
assert sum(b_["events"] for b_ in S["OEbyPackTemperatureBand"]) == F["primary"]["events"]
assert S["S2_firstHalf"]["atRiskSeconds"] + S["S2_secondHalf"]["atRiskSeconds"] == F["primary"]["atRiskSeconds"]
assert S["S1_perDrive"]["nDrivesAll"] == F["primary"]["nDrives"] and "S3_dropSharedDays" in S and sum(F["perDriveEvents"].values()) == F["primary"]["events"]
assert F["skippedFilesNotInTable"] == {"basis": 0, "later": 0}
print("OK test_m428_oot")
