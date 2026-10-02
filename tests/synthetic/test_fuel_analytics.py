"""M337 known-answer tests for tools/fuel_analytics.py (spec analyses/M337_spec.md rev 2): integration on the rate's own timestamps, FUEL-12 bias recovery,
reset detection input, band edges, weighted vs unweighted quantiles, support labels. Synthetic data only."""
import os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("XT_RAW_DIR", os.path.join(ROOT, "raw"))
import numpy as np, pandas as pd
import fuel_analytics as fa

fails = 0
def ok(label, c, extra=""):
    global fails
    print(("PASS " if c else "FAIL ") + label + ((" - " + str(extra)) if (not c and extra) else ""))
    fails += 0 if c else 1

def trip_csv(path, n=600, rate=3.6, bias=1.0, rate_every=1, reset_at=None):
    t0 = pd.Timestamp("2026-08-10 10:00:00")
    times = [t0 + pd.Timedelta(seconds=i) for i in range(n)]
    litres_per_s = rate / 3600.0
    cnt = np.cumsum(np.full(n, litres_per_s)) * bias
    r = np.full(n, rate, dtype=float)
    r[[i for i in range(n) if i % rate_every]] = np.nan          # sparse rate series: only every `rate_every`-th row carries a value
    if reset_at is not None:
        cnt[reset_at:] = cnt[reset_at:] - cnt[reset_at] + 0.001
    pd.DataFrame({"time": [t.strftime("%Y-%m-%d %H:%M:%S") for t in times], fa.CNT: np.round(cnt, 4), fa.RATE: r}).to_csv(path, index=False)

with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "a.csv"); trip_csv(p)
    T = fa.read_trip(p)
    c = T["counter"]; i0, i1 = c.first_valid_index(), c.last_valid_index()
    Vc = float(c.loc[i1] - c.loc[i0])
    Vi, gap = fa.integrate(T["t"], T["rate"], T["t"].loc[i0], T["t"].loc[i1], 5.0)
    ok("known answer: constant 3.6 L/h over 599 s -> 0.599 L (integral)", abs(Vi - 0.599) < 1e-6, Vi)
    ok("known answer: consistent counter -> |V_int - V_cnt| < 1e-3 L", abs(Vi - Vc) < 1e-3, (Vi, Vc))
    ok("no gap flagged on a 1 s clock", gap is False)
    # sparse rate (every 4th row has a value): integrating on the rate's OWN timestamps recovers the volume (an all-row clock with NaN=0 would undercount ~75%)
    p2 = os.path.join(d, "b.csv"); trip_csv(p2, rate_every=4)
    T2 = fa.read_trip(p2); c2 = T2["counter"]
    Vi2, gap2 = fa.integrate(T2["t"], T2["rate"], T2["t"].loc[c2.first_valid_index()], T2["t"].loc[c2.last_valid_index()], 5.0)
    ok("sparse rate series: own-timestamp integral within 2% of the counter", abs(Vi2 - 0.599) / 0.599 < 0.02, Vi2)
    ok("gap flag false when raw dt (4 s) <= cap (5 s)", gap2 is False)
    p3 = os.path.join(d, "c.csv"); trip_csv(p3, rate_every=8)
    T3 = fa.read_trip(p3)
    _, gap3 = fa.integrate(T3["t"], T3["rate"], T3["t"].loc[0], T3["t"].loc[len(T3["t"]) - 1], 5.0)
    ok("gap flag true when raw dt (8 s) > cap (5 s)", gap3 is True)
    # reset: counter drops
    p4 = os.path.join(d, "d.csv"); trip_csv(p4, reset_at=300)
    T4 = fa.read_trip(p4)
    ok("reset input: counter decrease exceeds the 0.01 L threshold", float(T4["counter"].diff().min()) < -0.01, float(T4["counter"].diff().min()))
    ok("usable flags: counter and rate usable on a normal trip", T["counterUsable"] and T["rateUsable"])

# FUEL-12 bias recovery: counter reads 1.0% above the rate integral -> aggregate (V_int - V_cnt)/V_cnt = -0.99%
rng = np.random.default_rng(1)
df = pd.DataFrame({"day": [f"2026-08-{1 + i % 12:02d}" for i in range(60)], "V_cnt": rng.uniform(0.5, 3.0, 60)})
df["V_int"] = df.V_cnt / 1.01
df["dd"] = df.V_int - df.V_cnt
r = fa.ratio_ci(df, "dd", "V_cnt")
ok("known answer: 1% biased counter -> aggregate -0.99% (tolerance 1e-4)", abs(r["est"] - (-1 + 1 / 1.01)) < 1e-4, r)
ok("CI brackets the estimate and reports n (trips, days)", r["ci95"][0] <= r["est"] <= r["ci95"][1] and r["nTrips"] == 60 and r["nDays"] == 12)
z = df.assign(V_int=df.V_cnt)
ok("known answer: no bias -> aggregate 0", abs(fa.ratio_ci(z.assign(dd=0.0), "dd", "V_cnt")["est"]) < 1e-12)

# band edges: [0.5,2) [2,5) [5,10) [10,20) [20,inf)
km = pd.Series([0.5, 1.99, 2.0, 4.99, 5.0, 9.99, 10.0, 19.99, 20.0, 80.0])
b = pd.cut(km, fa.KM_EDGES, right=False, labels=fa.BAND_LABELS).astype(str).tolist()
ok("band edges inclusive-lower exclusive-upper", b == ["0.5-2", "0.5-2", "2-5", "2-5", "5-10", "5-10", "10-20", "10-20", "20+", "20+"], b)

# weighted vs unweighted quantiles: two trips, rates 5 (1 km) and 10 (9 km): trip-weighted median 7.5, distance-weighted median 10
q = pd.DataFrame({"rate100": [5.0, 10.0], "km": [1.0, 9.0]})
ok("trip-weighted median (type 7) of two trips = 7.5", abs(fa.qstats(q)["q50"] - 7.5) < 1e-12, fa.qstats(q))
ok("distance-weighted median = 10 (90% of km at 10 L/100 km)", abs(fa.qstats(q, True)["q50"] - 10.0) < 1e-12, fa.qstats(q, True))
ok("distance-weighted q10 = 5 and q25 = 10", abs(fa.qstats(q, True)["q10"] - 5.0) < 1e-12 and abs(fa.qstats(q, True)["q25"] - 10.0) < 1e-12)

# support labels and temp bands
ok("support: >=7 days ci, 5-6 low-cluster, <5 points only", [fa.support(x) for x in (7, 12, 6, 5, 4, 1)] == ["ci", "ci", "low-cluster CI", "low-cluster CI", "points only", "points only"])
ok("temp bands: <40, 40-60, >=60, unknown", [fa.temp_band(x) for x in (39.9, 40.0, 59.9, 60.0, float("nan"), None)] == ["<40C", "40-60C", "40-60C", ">=60C", "unknown", "unknown"])

print("FUEL ANALYTICS TESTS: " + ("all passed" if not fails else f"{fails} FAILED"))
sys.exit(1 if fails else 0)
