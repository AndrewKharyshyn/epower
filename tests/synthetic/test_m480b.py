"""M480b known-answer tests (analyses/M480b_spec.md Rev 3). Expected values are derived by hand or by brute-force enumeration, not read off the tool.
Run: python tests/synthetic/test_m480b.py"""
import itertools, os, sys, tempfile
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import compute_drive_summary_v6 as D            # noqa: E402
import pair_cache as PC                          # noqa: E402
import m480b_pair_outcomes as O                  # noqa: E402
import dependence_sensitivity as DS              # noqa: E402

CI, CMAX, CMIN, CSOC = "[BMS] HV Battery Current (A)", "[BMS] Max Cell Voltage (V)", "[BMS] Min Cell Voltage (V)", "[BMS] HV State of charge (%)"


def ok(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + name + ((" -- " + str(detail)) if not cond else ""))
    if not cond:
        ok.bad += 1


ok.bad = 0
close = lambda a, b, tol: a is not None and abs(a - b) <= tol


def make_csv(events):
    events = sorted(events, key=lambda e: e[0])
    cols = ["time", CI, CMAX, CMIN, CSOC]
    rows = []
    for t, c, v in events:
        r = {k: "" for k in cols}
        r["time"] = "%02d:%02d:%09.6f" % (int(t // 3600), int((t % 3600) // 60), t % 60)
        r[c] = repr(float(v))
        rows.append(r)
    return pd.DataFrame(rows, columns=cols).to_csv(index=False).encode("utf-8")


# (1) closed form = brute-force enumeration of all m-subsets --------------------------------------------------------------------------------------------------
rng = np.random.default_rng(5)
for N, m in ((7, 4), (9, 5), (22, 20), (12, 10)):
    x = np.round(rng.gamma(3, 2, N), 1)                      # rounded values create ties
    subs = [np.quantile(np.array(c), 0.95) for c in itertools.combinations(x, m)]
    meds = [np.median(np.array(c)) for c in itertools.combinations(x, m)]
    ok("(1) N=%d m=%d: closed-form q0.95 statistic equals the mean over every subset" % (N, m), close(O.fixed_n_stat(x, m), float(np.mean(subs)), 1e-9), (O.fixed_n_stat(x, m), np.mean(subs)))
    ok("(1) N=%d m=%d: closed-form median statistic equals the mean over every subset" % (N, m), close(O.fixed_n_stat(x, m, kind="median"), float(np.mean(meds)), 1e-9))
x = rng.gamma(4, 2, 60)
ok("(1) invariant to row order", close(O.fixed_n_stat(x, 20), O.fixed_n_stat(rng.permutation(x), 20), 1e-9))
ok("(1) N < m gives no value (support floor)", np.isnan(O.fixed_n_stat(x[:15], 20)))
ok("(1) N = m gives the plain numpy-linear p95 of the sample", close(O.fixed_n_stat(x[:20], 20), float(np.quantile(x[:20], 0.95)), 1e-9))

# (2) the fixed-n statistic does not depend on N; the variable-n p95 does -----------------------------------------------------------------------------------
fx40 = np.mean([O.fixed_n_stat(rng.gamma(4, 2, 40), 20) for _ in range(300)])
fx400 = np.mean([O.fixed_n_stat(rng.gamma(4, 2, 400), 20) for _ in range(300)])
v40 = np.mean([np.quantile(rng.gamma(4, 2, 40), 0.95) for _ in range(300)])
v400 = np.mean([np.quantile(rng.gamma(4, 2, 400), 0.95) for _ in range(300)])
ok("(2) same distribution, N=40 vs N=400: fixed-n statistic agrees within 1.5 % while the variable-n p95 differs more", abs(fx40 - fx400) / fx400 < 0.015 and abs(v40 - v400) / v400 > abs(fx40 - fx400) / fx400,
   (fx40, fx400, v40, v400))

# (3) restrictions select exactly the hand-built pairs ----------------------------------------------------------------------------------------------------------
a = {"I": np.array([50.0, 50.01, 80.0, 80.01, -80.0, 4.99, 5.0, np.nan, -65.0, 65.0]),
     "soc": np.array([60.0, 49.99, 50.0, 70.0, 70.01, 60.0, 60.0, 60.0, np.nan, 60.0]),
     "off_ms": np.array([0.0, 25.0, 25.01, 50.0, 50.01, 100.0, 100.01, -50.0, -50.01, 10.0]), "spread_mv": np.arange(10.0), "t": np.arange(10.0)}
m0 = list(O.pair_mask(a, "O0"))
ok("(3) O0: |I| > 50 (50 excluded, NaN excluded)", m0 == [False, True, True, True, True, False, False, False, True, True], m0)
m1 = list(O.pair_mask(a, "O1"))
ok("(3) O1: 50 < |I| <= 80 and 50 <= SoC <= 70 (edges, NaN SoC excluded)", m1 == [False, False, True, False, False, False, False, False, False, True], m1)
m2 = list(O.pair_mask(a, "O2", 50.0))
ok("(3) O2 at 50 ms: loaded and |offset| <= 50 (50.00 kept, 50.01 dropped)", m2 == [False, True, True, True, False, False, False, False, False, True], m2)
ok("(3) O2 at 25 and 100 ms", list(O.pair_mask(a, "O2", 25.0)) == [False, True, False, False, False, False, False, False, False, True] and list(O.pair_mask(a, "O2", 100.0)) == [False, True, True, True, True, False, False, False, True, True])
m3 = list(O.pair_mask(a, "O3"))
ok("(3) O3: |I| < 5 (4.99 in, 5 out, NaN out)", m3 == [False, False, False, False, False, True, False, False, False, False], m3)

# (4) cache extraction: offset sign, production agreement, key invalidation --------------------------------------------------------------------------------------
tt = np.arange(0.0, 120.0, 1.0)
vc = lambda t: 3.7 + 0.1 * np.sin(2 * np.pi * t / 40.0)
ev = [(t, CMAX, vc(t) + 0.01) for t in tt] + [(t + 0.25, CMIN, vc(t + 0.25) - 0.01) for t in tt] + [(t + 0.1, CI, -80.0 if t < 100 else 0.0) for t in tt] + [(t, CSOC, 60.0) for t in np.arange(0, 120, 5.0)]
b = make_csv(ev)
arr = PC.pairs_from_bytes(b)
prod = D._v5_analyze_bytes(b, "x")
ld = np.abs(arr["I"]) > 50
ok("(4) offset sign: min-cell report minus max-cell report = +250 ms", close(float(np.median(arr["off_ms"])), 250.0, 0.5), np.median(arr["off_ms"]))
ok("(4) loaded count equals the production n_loaded_spread_samples and the loaded p95 equals the production value within 0.05 mV",
   int(ld.sum()) == prod["n_loaded_spread_samples"] and abs(float(np.quantile(arr["spread_mv"][ld], 0.95)) - prod["cell_spread_loaded_p95_mv"]) <= 0.05 + 1e-9, (int(ld.sum()), prod["n_loaded_spread_samples"]))
ok("(4) matched SoC and current ages are carried (SoC 60 %, current 100 ms from the pair)", close(float(np.nanmedian(arr["soc"])), 60.0, 1e-9) and close(float(np.nanmedian(arr["cur_age_ms"])), 150.0, 51.0))
with tempfile.TemporaryDirectory() as d:
    sha = {"a.csv": "a" * 64}
    ld_ = lambda f: b
    _, _, s1 = PC.load_or_build("a.csv", ld_, lambda f: sha[f], "ext1" * 8, d)
    _, _, s2 = PC.load_or_build("a.csv", lambda f: (_ for _ in ()).throw(AssertionError("raw read on hit")), lambda f: sha[f], "ext1" * 8, d)
    _, _, s3 = PC.load_or_build("a.csv", ld_, lambda f: sha[f], "ext2" * 8, d)
    sha["a.csv"] = "b" * 64
    _, _, s4 = PC.load_or_build("a.csv", ld_, lambda f: sha[f], "ext1" * 8, d)
ok("(4) cache: first build, then hit without reading the raw file; a changed extractor hash or raw hash invalidates the entry", (s1, s2, s3, s4) == ("built", "hit", "built", "built"), (s1, s2, s3, s4))

# (5) Delta intervals ---------------------------------------------------------------------------------------------------------------------------------------------
rg = np.random.default_rng(11)
nd, per = 120, 5
day = np.repeat(np.arange(nd), per)
months = day / nd * 12.0
X = np.column_stack([np.ones(len(day)), months, rg.normal(25, 5, len(day)), rg.normal(150, 20, len(day))])
base = 0.05 * X[:, 2] + 0.01 * X[:, 3] + np.repeat(rg.normal(0, 0.3, nd), per)
y_ref = base + 0.5 * months + rg.normal(0, 0.3, len(day))
y_r = base + 0.2 * months + rg.normal(0, 0.3, len(day))
grp = np.array(["d%03d" % i for i in day])
da, db = O.delta_analytic(X, y_r, y_ref, grp), O.delta_bootstrap(X, y_r, y_ref, grp, 1, 800, 42)
ok("(5) known Delta -0.3: analytic and bootstrap intervals contain it and exclude zero", da["ci95"][0] < -0.3 < da["ci95"][1] < 0 and db["ci95"][0] < -0.3 < db["ci95"][1] < 0, (da, db["ci95"]))
d0 = O.delta_analytic(X, y_ref, y_ref, grp)
ok("(5) identical outcomes: Delta = 0 with zero width", abs(d0["delta"]) < 1e-12 and d0["se"] < 1e-9)

# (6) power gate: nominal level at theta 0, near 1 for a large slope ------------------------------------------------------------------------------------------------
dfp = pd.DataFrame({"day": grp})
pg = O.power_gate(dfp, X, y_ref, y_ref + rg.normal(0, 0.05, len(day)), {"zero": 0.0, "big": 3.0}, draws=300)
ok("(6) detection probability is small at theta = 0 and about 1 at a large theta", pg["zero"]["detection_probability"] < 0.12 and pg["big"]["detection_probability"] > 0.99, pg)
ok("(6) minimum effect with 80 % power = (t_.975 + t_.80) * SE with df = G - 1", close(O.mde80(0.1, 117), (1.9806 + 0.8447) * 0.1, 5e-3), O.mde80(0.1, 117))

# (7) decision rule: each outcome, precedence, the worked example -----------------------------------------------------------------------------------------------------
mk = lambda inf=True, point=0.5, b_ref=0.5, dlo=-0.1, dhi=0.1, lo=0.2: {"informative": inf, "point": point, "b_ref": b_ref, "delta_lo": dlo, "delta_hi": dhi, "cr1_lo": lo}
ok("(7) supported_provisional", O.verdict({"O1": mk(), "O2": mk()})[0] == "supported_provisional")
ok("(7) not_supported: both informative, each below half with Delta upper bound below zero", O.verdict({"O1": mk(point=0.1, dlo=-0.9, dhi=-0.1), "O2": mk(point=0.1, dlo=-0.9, dhi=-0.1)})[0] == "not_supported")
ok("(7) not_supported: a negative point estimate with Delta upper bound below zero (single informative outcome)", O.verdict({"O1": mk(inf=False), "O2": mk(point=-0.2, dlo=-1.0, dhi=-0.1)})[0] == "not_supported")
ok("(7) worked example: ONE informative outcome below half, Delta upper below zero, positive point -> consistent_imprecise", O.verdict({"O1": mk(inf=False), "O2": mk(point=0.1, dlo=-0.9, dhi=-0.1)})[0] == "consistent_imprecise")
ok("(7) consistent_imprecise: informative, lower bound of CR1 not above zero", O.verdict({"O1": mk(lo=-0.1), "O2": mk(inf=False)})[0] == "consistent_imprecise")
ok("(7) underpowered_inconclusive: no informative primary outcome", O.verdict({"O1": mk(inf=False), "O2": mk(inf=False)})[0] == "underpowered_inconclusive")
ok("(7) the supported verdict names its informative outcome", O.verdict({"O1": mk(inf=False), "O2": mk()})[1] == ["O2"])

# (8) end to end on a synthetic corpus: slope in every pair set vs slope only in pairs outside the restricted sets -----------------------------------------------------------
def corpus(seed, where):
    r = np.random.default_rng(seed)
    n_days, per_day = 130, 4
    rows, data = [], {}
    for dd in range(n_days):
        for k in range(per_day):
            f = "f%03d_%d.csv" % (dd, k)
            mo = dd / n_days * 12.0
            n = 300
            I = r.uniform(-140, 140, n)
            soc = r.uniform(40, 80, n)
            off = r.uniform(-100, 100, n)
            cur = np.abs(I)
            spread = 20 + r.normal(0, 1.0, n)
            sl = 0.5 * mo
            if where == "all":
                spread += sl
            elif where == "outside":                                   # slope only where the restricted sets do not look: |I| > 80 and |offset| > 50
                spread += sl * ((cur > 80) & (np.abs(off) > 50))
            data[f] = {"t": np.sort(r.uniform(0, 2000, n)), "spread_mv": spread, "off_ms": off, "I": I, "cur_age_ms": np.full(n, 50.0), "soc": soc}
            rows.append({"file": f, "date": pd.Timestamp("2026-05-01") + pd.Timedelta(days=dd), "day": "d%03d" % dd, "months": mo, "T": 25 + r.normal(0, 3), "I": 150 + r.normal(0, 15),
                         "regime": "fast" if dd < 40 else "slow"})
    return pd.DataFrame(rows), data


fr, data = corpus(3, "all")
res = O.analyse_outcomes(fr, data, 200, 100)
ok("(8) slope in every pair set: O0m, O1m, O2m recover 0.5 and the verdict is supported_provisional naming both outcomes",
   close(res["O0m"]["slope"], 0.5, 0.08) and close(res["outcomes"]["O1"]["slope"], 0.5, 0.15) and close(res["outcomes"]["O2"]["slope"], 0.5, 0.15) and res["verdict"] == "supported_provisional"
   and res["informative_outcomes"] == ["O1", "O2"], (res["O0m"]["slope"], res["outcomes"]["O1"]["slope"], res["outcomes"]["O2"]["slope"], res["verdict"], res["informative_outcomes"]))
ok("(8) the results carry Delta (analytic and bootstrap), power gate at three slopes, MDE, regime mix, moving blocks, sensitivities, slow regime and cutoffs",
   all(k in res["outcomes"]["O2"] for k in ("delta", "power_gate", "mde80", "regime_mix", "moving_block")) and set(res["outcomes"]["O2"]["power_gate"]) == {"theta_0", "theta_half_ref", "theta_ref"}
   and "O1_m10" in res["sensitivities"] and "O2_off25" in res["sensitivities"] and "O2_slow_regime" in res["companions"] and len(res["companions"]["O1_cutoffs"]) == 5)
fr2, data2 = corpus(4, "outside")
res2 = O.analyse_outcomes(fr2, data2, 200, 100)
ok("(8) slope only outside the restricted sets: O1m and O2m have no slope while O0m keeps one; the verdict is not_supported",
   res2["O0m"]["slope"] > 0.1 and abs(res2["outcomes"]["O1"]["slope"]) < 0.1 and abs(res2["outcomes"]["O2"]["slope"]) < 0.1 and res2["verdict"] == "not_supported",
   (res2["O0m"]["slope"], res2["outcomes"]["O1"]["slope"], res2["outcomes"]["O2"]["slope"], res2["verdict"], res2["primary_inputs"]))

if ok.bad:
    sys.exit(1)
print("OK test_m480b")
