"""M430 known-answer test (spec analyses/M430_spec.md Rev 2 + 2.1; criteria declared there before any result), tools/soak_fitq.py:
(iv) hand-computed 12-pair example: MAE, skill, zero-denominator rule, cell eligibility;
(i)  planted single exponential (tau = 12 h) on the REAL per-day gap sets of the pack pair table, day-shared offset, integer-degree temperatures and the real selection (ie > 3, re > 0.5):
     in >= 85 % of R = 100 replications (B = 300) S1 'improvement over persistence established' AND S3 does not fire (pooled cell);
(ii) planted two timescales (eta = -0.6 x below 1 h, -0.6 - 0.05 (x - 1) above): S3 fires in >= 60 % of replications;
(iii) planted no decay: S1 'improvement over persistence not established' in >= 85 % of replications.
Declared design: total residual sd 0.35 on the log scale, intra-day correlation 0.25 (day offset sd 0.175, pair noise sd 0.303). The planted designs use the pack's initial-excess range (ie 4..25 C), so the
power statement applies to the pack design only. A failed criterion is a stated limitation, never a pass."""
import json, math, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import soak_fitq as F


def sen(x, y):
    dx = x[:, None] - x[None, :]
    dy = y[:, None] - y[None, :]
    iu = np.triu_indices(len(x), k=1)
    dxu, dyu = dx[iu], dy[iu]
    v = dxu != 0
    return float(np.median(dyu[v] / dxu[v]))


# ---------------------------------------------------------------- (iv) hand-computed example
days = np.repeat(["d%02d" % i for i in range(6)], 2)                 # 6 days x 2 pairs = 12 pairs
y = np.full(12, math.log(0.8))                                        # observed retained fraction 0.8 everywhere
P = {m: np.zeros(12) for m in ("M", "B0", "B1med", "B1mean", "B2med", "B2mean", "B3")}
P["M"] = np.array([math.log(0.9)] * 6 + [math.log(0.7)] * 6)         # |0.8 - 0.9| = |0.8 - 0.7| = 0.1 -> MAE_M = 0.1
cell = F.Cell(np.zeros(12), y, days, P, np.ones(12, bool))
st = cell.stats(np.arange(12))
assert abs(st["MAE_M"] - 0.1) < 1e-12 and abs(st["MAE_B0"] - 0.2) < 1e-12              # persistence predicts 1.0: |0.8 - 1| = 0.2
assert abs(st["skillMAE_B0"] - 0.5) < 1e-12                                            # 1 - 0.1 / 0.2
mse_m = 0.5 * ((math.log(0.8) - math.log(0.9)) ** 2 + (math.log(0.8) - math.log(0.7)) ** 2)
assert abs(st["skillMSElog_B0"] - (1 - mse_m / math.log(0.8) ** 2)) < 1e-12
assert not cell.eligible() and cell.n == 12                                            # < 20 pairs and < 10 days: no statement
assert F.analyse_cell(cell, b=20)["b2EqualsB0AllFolds"] is True                       # B2 == B0 everywhere here (all zeros): flagged
P2 = dict(P); P2["B2med"] = np.full(12, -0.1)
assert F.analyse_cell(F.Cell(np.zeros(12), y, days, P2, np.ones(12, bool)), b=20)["b2EqualsB0AllFolds"] is False
# zero denominator: persistence is perfect when the observed retained fraction is exactly 1
y1 = np.zeros(12)
c1 = F.Cell(np.zeros(12), y1, days, P, np.ones(12, bool))
assert math.isnan(c1.stats(np.arange(12))["skillMAE_B0"])
r = F.analyse_cell(c1, b=50)
assert r["point"]["skillMAE_B0"] is None and not r["eligibleForStatements"]


# ---------------------------------------------------------------- planted designs on the real per-day gap sets
pairs = json.load(open(os.path.join("analyses", "M429_pairs.json"), encoding="utf-8"))
pack = pairs["fits"][pairs["order"].index("pack")]
GAP, DAY = np.array(pack["gapH"]), np.array(pack["arrivalDay"])
UDAYS = sorted(set(DAY.tolist()))
SD_DAY, SD_EPS = 0.175, math.sqrt(0.35 ** 2 - 0.175 ** 2)


def planted(rng, eta):
    off = {d: rng.normal(0, SD_DAY) for d in UDAYS}
    ie = rng.integers(4, 26, len(GAP)).astype(float)
    re = np.round(ie * np.exp(eta(GAP) + np.array([off[d] for d in DAY]) + rng.normal(0, SD_EPS, len(GAP))))
    keep = (ie > 3) & (re > 0.5)
    return GAP[keep], np.log(re[keep] / ie[keep]), DAY[keep]


def pooled_statements(x, y, d, b):
    P, _ = F.cv_predictions(x, y, d, sen, F.fold_of_days(d.tolist(), F.K_FOLDS))
    res = F.analyse_cell(F.Cell(x, y, d, P, np.ones(len(x), bool)), b=b, seed=42)
    return {k: (v.get("statement") if isinstance(v, dict) else None) for k, v in (res.get("statements") or {}).items()}


R, B = 100, 300
designs = {"i_exp": lambda g: -g / 12.0,
           "ii_two": lambda g: np.where(g < 1.0, -0.6 * g, -0.6 - 0.05 * (g - 1.0)),
           "iii_none": lambda g: np.zeros_like(g)}
count = {k: 0 for k in designs}
rng = np.random.default_rng(430)
for rep in range(R):
    for name, eta in designs.items():
        x, y, d = planted(rng, eta)
        s = pooled_statements(x, y, d, B)
        if name == "i_exp":
            count[name] += (s.get("S1") == "improvement over persistence established") and (s.get("S3") != "worse than the empirical gap bins")
        elif name == "ii_two":
            count[name] += s.get("S3") == "worse than the empirical gap bins"
        else:
            count[name] += s.get("S1") == "improvement over persistence not established"
# post-hoc additions on one planted data set (Director ruling 2026-10-14): long-gap share of the squared error, block-bootstrap sensitivity, exclusion counts
x, y, d = planted(np.random.default_rng(5), designs["i_exp"])
fq = F.fit_quality(x, y, d, sen, r2_insample=-1.0, n_removed=10, n_before_filter=len(x) + 10, b=60)
assert 0.0 <= fq["postHoc"]["logSqErrShareGapGe12h"] <= 1.0 and 0.0 < fq["postHoc"]["shareOfScoredPairsGapGe12h"] < 1.0 and "post-hoc" in fq["postHoc"]["label"]
bb = fq["cells"]["pooled"]["blockBootstrap"]
assert bb["blockDays"] == 5 and set(bb["statements"]) == {"S1", "S2", "S3"} and "post-hoc" in bb["label"]
assert fq["selection"]["nRemovedByResidualFilter"] == 10 and fq["inSample"]["rSquared"] == -1.0
rate = {k: v / R for k, v in count.items()}
print("planted rates", rate)
assert rate["i_exp"] >= 0.85, ("criterion (i) failed", rate)
assert rate["ii_two"] >= 0.60, ("criterion (ii) failed", rate)
assert rate["iii_none"] >= 0.85, ("criterion (iii) failed", rate)
print("OK test_m430_fitq (i %.2f, ii %.2f, iii %.2f)" % (rate["i_exp"], rate["ii_two"], rate["iii_none"]))
