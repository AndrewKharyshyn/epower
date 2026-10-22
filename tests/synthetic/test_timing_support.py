"""M479 known-answer tests (analyses/M479_spec.md): per-PID timing, max/min pair offset and loaded support sidecar. Expected values are derived by hand from the
construction of each synthetic drive, not read off the tool. Run: python tests/synthetic/test_timing_support.py"""
import hashlib, io, math, os, sys, tempfile
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import compute_drive_summary_v6 as D          # noqa: E402
import timing_support as TS                    # noqa: E402

CI, CMAX, CMIN, CSOC = "[BMS] HV Battery Current (A)", "[BMS] Max Cell Voltage (V)", "[BMS] Min Cell Voltage (V)", "[BMS] HV State of charge (%)"


def make_csv(events):
    """events: list of (t_seconds, column, value) -> wide CSV bytes in the logger's format (one non-null cell per row, HH:MM:SS.ffffff clock)."""
    events = sorted(events, key=lambda e: e[0])
    cols = ["time", CI, CMAX, CMIN, CSOC]
    rows = []
    for t, c, v in events:
        r = {k: "" for k in cols}
        r["time"] = "%02d:%02d:%09.6f" % (int(t // 3600), int((t % 3600) // 60), t % 60)
        r[c] = repr(float(v))
        rows.append(r)
    return pd.DataFrame(rows, columns=cols).to_csv(index=False).encode("utf-8")


def cur_events(times, val):
    return [(t, CI, val(t) if callable(val) else val) for t in times]


def cells(times, vc, spread_v=0.020, phase=0.0, neg_idx=()):
    ev = []
    for i, t in enumerate(times):
        ev.append((t, CMAX, vc(t) + spread_v / 2))
        mn = vc(t + phase) - spread_v / 2
        if i in neg_idx:
            mn = vc(t) + spread_v / 2 + 0.002       # logged min above logged max
        ev.append((t + phase, CMIN, mn))
    return ev


def ok(name, cond, detail=""):
    print(("OK   " if cond else "FAIL ") + name + ((" -- " + str(detail)) if not cond else ""))
    if not cond:
        ok.bad += 1


ok.bad = 0
close = lambda a, b, tol: a is not None and abs(a - b) <= tol

# (a) identical production density summary, different timing rows ------------------------------------------------------------------------------------------
N = 750
t_u = np.arange(N + 1) * 0.8
cyc = np.array([0.1, 0.8, 0.8, 0.8, 4.0])
t_j = np.concatenate([[0.0], np.cumsum(np.tile(cyc, N // 5))])
steps = np.full(N, 0.8)
steps[[200, 500]] = 30.0
t_o = np.concatenate([[0.0], np.cumsum(steps)])
res = {}
for name, tt in (("uniform", t_u), ("jitter", t_j), ("outage", t_o)):
    b = make_csv(cur_events(tt, -10.0))
    dens = D._i_channel_sampling_density(["x"], lambda f, b=b: b)["x"]
    res[name] = (dens, TS.timing_from_bytes(b))
ok("(a) production density cannot tell the three apart (median 0.8 s, coverage 1.0)",
   all(close(d[0], 0.8, 1e-9) and close(d[1], 1.0, 1e-9) for d, _ in res.values()), [d for d, _ in res.values()])
u, j, o = res["uniform"][1], res["jitter"][1], res["outage"][1]
ok("(a) uniform: no jitter, no long gaps, rate close to 1/0.8 Hz", close(u["i_dt_q50"], 0.8, 1e-9) and close(u["i_dt_iqr_ratio"], 0.0, 1e-9) and u["i_n_gap20"] == 0
   and close(u["i_frac_dt_gt3s"], 0.0, 1e-9) and close(u["i_rate_hz"], 1 / 0.8, 0.02), u)
ok("(a) jitter: q05 0.1 s, q95 4.0 s, one interval in five above 3 s, no long gaps, elapsed-time rate near 1/1.3 Hz",
   close(j["i_dt_q05"], 0.1, 1e-6) and close(j["i_dt_q95"], 4.0, 1e-6) and close(j["i_frac_dt_gt3s"], 0.2, 1e-9) and j["i_n_gap20"] == 0 and close(j["i_rate_hz"], 1 / 1.3, 0.02), j)
ok("(a) outage: two intervals of 30 s counted (60 s total, max gap 30 s), median still 0.8 s, lower elapsed-time rate than uniform",
   o["i_n_gap20"] == 2 and close(o["i_gap20_s"], 60.0, 1e-9) and close(o["i_max_gap_s"], 30.0, 1e-9) and close(o["i_dt_q50"], 0.8, 1e-9) and o["i_rate_hz"] < 0.95 * u["i_rate_hz"], o)
ok("(a) flag_gap20_i only for the outage drive", (u["flag_gap20_i"], j["flag_gap20_i"], o["flag_gap20_i"]) == (False, False, True))
ok("(a) row coverage is a separate variable (1.0 here)", all(close(r[1]["i_row_cov"], 1.0, 1e-9) for r in res.values()))

# (b) the unchanged-cell phase counterexample ---------------------------------------------------------------------------------------------------------------
tt = np.arange(0.0, 300.0, 1.0)
vc = lambda t: 3.7 + 0.15 * math.sin(2 * math.pi * t / 40.0)       # shared smooth component, true simultaneous spread 20 mV
out = {}
for ph in (0.01, 0.25):
    b = make_csv(cells(tt, vc, phase=ph) + cur_events(tt + 0.1, -80.0))
    r = D._v5_analyze_bytes(b, "x")
    out[ph] = (TS.timing_from_bytes(b), r)
a, c = out[0.01][0], out[0.25][0]
ok("(b) sidecar reads the reporting offset: median 10 ms and 250 ms", close(a["off_med_ms"], 10.0, 0.5) and close(c["off_med_ms"], 250.0, 0.5), (a["off_med_ms"], c["off_med_ms"]))
ok("(b) skew flag only for the 0.25 s offset", (a["flag_skew_gt50ms"], c["flag_skew_gt50ms"]) == (False, True))
p1, p2 = out[0.01][1]["cell_spread_loaded_p95_mv"], out[0.25][1]["cell_spread_loaded_p95_mv"]
ok("(b) production loaded p95 differs between the two offsets although the simultaneous spread is 20 mV in both (mechanism on a synthetic, not a size in real data)",
   close(p1, 20.0, 0.5) and p2 - p1 > 3.0, (p1, p2))
ok("(b) n_loaded equals the production n_loaded_spread_samples", a["n_loaded"] == out[0.01][1]["n_loaded_spread_samples"] and c["n_loaded"] == out[0.25][1]["n_loaded_spread_samples"], (a["n_loaded"], out[0.01][1]["n_loaded_spread_samples"]))

# (c) negative pairs are counted, never removed ------------------------------------------------------------------------------------------------------------
tt = np.arange(0.0, 200.0, 1.0)
neg = {10, 20, 30, 40, 50, 60, 70}
b = make_csv(cells(tt, lambda t: 3.7, neg_idx=neg) + cur_events(tt + 0.1, -80.0))
r = TS.timing_from_bytes(b)
ok("(c) 7 negative pairs counted among 200, all loaded, none dropped", r["n_pairs"] == 200 and r["n_neg"] == 7 and r["n_neg_loaded"] == 7 and r["n_loaded"] == 200
   and close(r["frac_neg"], 7 / 200, 1e-12) and r["flag_neg_loaded"] is True, r)

# (d) loaded counts, split, episodes, current age, SoC ---------------------------------------------------------------------------------------------------------
tt = np.arange(0.0, 100.0, 1.0)
cur = lambda t: -80.0 if t < 30 else (0.0 if t < 50 else (60.0 if t < 75 else -100.0))
b = make_csv(cells(tt, lambda t: 3.7) + cur_events(tt + 0.05, lambda t: cur(t - 0.05)) + [(s, CSOC, 60.0) for s in np.arange(0.0, 100.0, 5.0)])
r = TS.timing_from_bytes(b)
ok("(d) 80 loaded pairs: 55 discharge, 25 charge; 2 episodes (30 and 50); largest share 0.625", r["n_loaded"] == 80 and r["n_loaded_dis"] == 55 and r["n_loaded_chg"] == 25
   and r["n_episodes"] == 2 and close(r["episode_max_share"], 0.625, 1e-12), r)
ok("(d) matched current is 50 ms from its pair; |I| median 80 A, p95 100 A; SoC 60 %", close(r["cur_age_p50_ms"], 50.0, 1.0) and close(r["cur_age_p95_ms"], 50.0, 1.0)
   and close(r["i_abs_med"], 80.0, 1e-9) and close(r["i_abs_p95"], 100.0, 1e-9) and close(r["soc_med"], 60.0, 1e-9), r)
ok("(d) flags: support below 20 and 30 false, fewer than 3 episodes true", (r["flag_support_lt20"], r["flag_support_lt30"], r["flag_one_episode"]) == (False, False, True))
ok("(d) n_loaded equals the production n_loaded_spread_samples", r["n_loaded"] == D._v5_analyze_bytes(b, "x")["n_loaded_spread_samples"])

# (e) determinism and incremental reuse -----------------------------------------------------------------------------------------------------------------------
bs = {"a.csv": make_csv(cells(np.arange(0.0, 100.0, 1.0), vc, phase=0.1) + cur_events(np.arange(0.0, 100.0, 1.0) + 0.1, -80.0)), "b.csv": b}
master = pd.DataFrame({"file": list(bs), "date": ["2026-10-01", "2026-10-02"]})
sha = {f: hashlib.sha256(v).hexdigest() for f, v in bs.items()}
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "t.csv")
    s1 = TS.build_sidecar(master, lambda f: bs[f], path=path, sha_lookup=lambda f: sha[f])
    raw1 = open(path, "rb").read()
    s2 = TS.build_sidecar(master, lambda f: (_ for _ in ()).throw(AssertionError("raw file read on reuse")), path=path, sha_lookup=lambda f: sha[f])
    raw2 = open(path, "rb").read()
    s3 = TS.build_sidecar(master, lambda f: bs[f], path=path, sha_lookup=lambda f: sha[f], rebuild=True)
    raw3 = open(path, "rb").read()
ok("(e) incremental rerun reuses stored rows without reading raw files; rebuild is byte-identical", raw1 == raw2 == raw3 and list(s1["file"]) == list(master["file"]) and (s1["raw_sha256"] == pd.Series(sha).values).all())
ok("(e) matched support against a master that carries the production counts",
   TS.matched_support(s1, pd.DataFrame({"file": list(bs), "n_loaded_spread_samples": [D._v5_analyze_bytes(v, "x")["n_loaded_spread_samples"] for v in bs.values()]})) == [])

# (f) regime change inside one drive --------------------------------------------------------------------------------------------------------------------------
t_f = np.concatenate([np.arange(0.0, 120.0, 0.8), 120.0 + np.arange(0.0, 120.0, 1.6)])
rf = TS.timing_from_bytes(make_csv(cur_events(t_f, -10.0)))
ru = TS.timing_from_bytes(make_csv(cur_events(np.arange(0.0, 240.0, 0.8), -10.0)))
ok("(f) window medians on both sides of 1.05 s set regime_cross while the drive median stays fast; a uniform drive does not", rf["i_regime_cross"] is True and rf["i_dt_q50"] < 1.05
   and ru["i_regime_cross"] is False and close(rf["i_win_dt_min"], 0.8, 1e-9) and close(rf["i_win_dt_max"], 1.6, 1e-9), (rf["i_win_dt_min"], rf["i_win_dt_max"], rf["i_dt_q50"]))

if ok.bad:
    sys.exit(1)
print("OK test_timing_support")
