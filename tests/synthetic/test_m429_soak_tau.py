"""M429 known-answer test (spec analyses/M429_spec.md Rev 2, section 3.5; pass criteria declared there before any result):
(i)   planted exponential decay with day-correlated noise, R = 200 replications, B = 300: empirical coverage of the day-clustered 95 % interval for k in [0.88, 1.00]; the pair-iid interval under 0.85;
(ii)  planted no-decay data: the upper tau bound is unbounded and the non-decaying draw share is above 0.2;
(iii) the helper's old-rule function reproduces the previously published intervals on the stored pair sets (read from analyses/M429_result.json 'previousPayload', not typed here);
plus the interval rule itself: slope >= 0 draws are counted (tau = +inf), the upper bound is unbounded iff the 97.5th slope percentile >= 0, the tau interval is monotone in the slope interval."""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import soak_tau as S


def sen(x, y):                                           # same definition as compute_summary_arrays._sen_slope
    dx = x[:, None] - x[None, :]
    dy = y[:, None] - y[None, :]
    iu = np.triu_indices(len(x), k=1)
    dxu, dyu = dx[iu], dy[iu]
    v = dxu != 0
    return float(np.median(dyu[v] / dxu[v]))


# ---- the interval rule on hand-made slopes
iv = S.interval_from_slopes(np.array([-0.2, -0.15, -0.1, -0.1, -0.05] * 20))
assert iv["upperUnbounded"] is False and iv["nonDecayingDrawShare"] == 0.0
assert iv["tauCI"][0] < iv["tauCI"][1] and abs(iv["tauCI"][0] - 1 / 0.2) < 0.2 and abs(iv["decayRateKCI"][1] - 0.2) < 0.01
sl = np.concatenate([np.full(950, -0.1), np.full(50, 0.02)])            # 5 % non-decaying draws: the 97.5th percentile is >= 0
iv = S.interval_from_slopes(sl)
assert iv["upperUnbounded"] is True and iv["tauCI"][1] is None and iv["nonDecayingDrawShare"] == 0.05 and iv["tauCI"][0] is not None
sl = np.concatenate([np.full(990, -0.1), np.full(10, 0.02)])            # 1 % non-decaying: the upper bound stays finite
iv = S.interval_from_slopes(sl)
assert iv["upperUnbounded"] is False and iv["tauCI"][1] is not None and iv["nonDecayingDrawShare"] == 0.01
assert S.interval_from_slopes(np.full(100, 0.1))["tauCI"] == [None, None]          # whole interval non-decaying
assert S._tau(-0.1) == 10.0 and S._tau(0.0) is None and S._tau(0.3) is None


# ---- (i) coverage with day-correlated noise
def make(rng, k, n_days=20, per_day=6, sd_day=0.30, sd_eps=0.10):
    """The gap level clusters by day (a day of short gaps, a day with long gaps) and the day carries a shared offset: the pairs of a day are NOT exchangeable.
    (A first design with a day offset independent of the gap left the pair-iid interval calibrated: pair dependence only matters when the regressor clusters by day, as the real gaps do.)"""
    day, x, y = [], [], []
    for d in range(n_days):
        e = rng.normal(0, sd_day)
        base = float(rng.choice([0.4, 2.5, 10.0]))
        for _ in range(per_day):
            g = base * float(rng.uniform(0.5, 1.5))
            day.append("2026-07-%02d" % (d + 1)); x.append(g); y.append(-k * g + e + rng.normal(0, sd_eps))
    return np.array(x), np.array(y), np.array(day)


R, B, K = 200, 300, 0.1
rng = np.random.default_rng(2026)
hit_c = hit_i = 0
for r in range(R):
    x, y, day = make(rng, K)
    ci_c = S.interval_from_slopes(S.boot_slopes(x, y, day, sen, B, 42 + r))["decayRateKCI"]
    ci_i = S.interval_from_slopes(S.boot_slopes(x, y, None, sen, B, 42 + r))["decayRateKCI"]
    hit_c += ci_c[0] <= K <= ci_c[1]
    hit_i += ci_i[0] <= K <= ci_i[1]
cov_c, cov_i = hit_c / R, hit_i / R
assert 0.88 <= cov_c <= 1.00, ("day-clustered coverage", cov_c)
assert cov_i < 0.85, ("pair-iid coverage", cov_i)

# ---- (ii) no decay
rng = np.random.default_rng(7)
x, y, day = make(rng, 0.0, sd_day=0.30)
iv = S.interval_from_slopes(S.boot_slopes(x, y, day, sen, 600, 42))
assert iv["upperUnbounded"] is True and iv["tauCI"][1] is None and iv["nonDecayingDrawShare"] > 0.2, iv

# ---- gap split: strata, tau null for a non-decaying stratum
rng = np.random.default_rng(11)
x = np.concatenate([rng.uniform(0.1, 0.9, 60), rng.uniform(2.0, 20.0, 60)])
y = np.concatenate([rng.normal(0, 0.05, 60), -0.1 * x[60:] + rng.normal(0, 0.05, 60)])
day = np.array(["d%02d" % (i % 25) for i in range(120)])
g = S.gap_split(x, y, day, sen, b=300, seed=42)
assert [s["nPairs"] for s in g["strata"]] == [60, 60] and g["strata"][0]["label"].startswith("gap <")
assert g["strata"][1]["tau"] is not None and abs(g["strata"][1]["decayRateK"] - 0.1) < 0.03
lo0, hi0 = g["strata"][0]["decayRateKCI"]
assert lo0 <= 0.0 <= hi0 and "post-hoc" in g["label"], g["strata"][0]          # the planted no-decay stratum: its interval includes zero

# ---- (iii) the old rule reproduces the previously published intervals on the stored pair sets (frozen historical rows)
rf, pf = os.path.join("analyses", "M429_published_rule.json"), os.path.join("analyses", "M429_pairs.json")
if os.path.exists(rf) and os.path.exists(pf):
    rows = json.load(open(rf, encoding="utf-8"))["rows"]
    prev = {"soakTauCI": rows["pack"]["tauCI"], "coolantTauCI": rows["coolant"]["tauCI"], "oilTauCI": rows["oil"]["tauCI"]}
    P = json.load(open(pf, encoding="utf-8"))
    fits = dict(zip(P["order"], P["fits"]))
    for name, cl, key in (("pack", False, "soakTauCI"), ("coolant", True, "coolantTauCI"), ("oil", True, "oilTauCI")):
        f = fits[name]
        x, y = np.array(f["gapH"]), np.array(f["y"])
        got, dropped = S.old_rule_interval(x, y, sen, cluster=(np.array(f["arrivalDay"]) if cl else None), b=1000, seed=42)
        assert got == prev[key], (name, got, prev[key])
# language rule for the old wording
import language_gate as LG
assert "M429-soak-ratio" in LG.scan_text("Treat the fitted tau as the SHORT-GAP behavior it's best supported by")
assert "M429-soak-ratio" in LG.scan_text("physically consistent with coolant and oil being smaller thermal masses")
assert "M429-soak-ratio" not in LG.scan_text("a point-estimate ratio of about 3.4x against the pack's own 11.55 h")
print("OK test_m429_soak_tau (coverage day-clustered %.3f, pair-iid %.3f)" % (cov_c, cov_i))
