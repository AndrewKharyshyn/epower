"""M403 (analyses/M403_spec.md v4): known-answer harness for the apparent-SoC-scale estimators. Synthetic drives with a known capacity, 0.5-point SoC quantisation, a known constant
current offset, round-robin cadence jitter, plus the cases the spec requires: reverse-regression bracket, matched-support lag scenarios, odd/even-week equivalence test that CAN fail,
NaN-flag drives (test d), SoC = 0 artefacts, singular bootstrap draws, per-drive cache by raw sha256."""
import os, sys, tempfile
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import capacity_basis as CB

CI, CV, CS = "[BMS] HV Battery Current (A)", "[BMS] HV Battery voltage (V)", "[BMS] HV State of charge (%)"
CB.N_BOOT = 300


def drive(seed, qcap=5.0, offset=0.3, n=1500, volt=350.0, soc_delay=0.0, zero_soc_rows=(), shape="sine"):
    """Charge-positive true current (sinusoid + noise); true SoC = S0 + 100*Q/qcap; logged current = true + offset; SoC read quantised to 0.5; ~1.28 s cadence."""
    rng = np.random.default_rng(seed)
    t = np.cumsum(rng.uniform(1.1, 1.46, n))
    t -= t[0]
    ph, per, amp = rng.uniform(0, 6.28), rng.uniform(300, 500), rng.uniform(25, 40)
    if shape == "saw":                                   # asymmetric current: ramps from -amp to +amp, so window ends carry different currents (lag-sensitive)
        Itrue = amp * (2 * (((t + ph * per / 6.28) / per) % 1.0) - 1) + rng.normal(0, 2.0, n)
    else:
        Itrue = amp * np.sin(2 * np.pi * t / per + ph) + rng.normal(0, 2.0, n)
    Q = np.r_[0.0, np.cumsum(0.5 * (Itrue[1:] + Itrue[:-1]) * np.diff(t))] / 3600.0
    S0 = rng.uniform(55, 70)
    soc_true = S0 + 100.0 * np.interp(t - soc_delay, t, Q) / qcap
    soc = np.round(soc_true * 2) / 2
    soc[list(zero_soc_rows)] = 0.0
    secs = 36000 + t
    tm = ["%02d:%02d:%06.3f" % (int(s_ // 3600), int((s_ // 60) % 60), s_ % 60) for s_ in secs]
    return pd.DataFrame({"time": tm, CI: -(Itrue + offset) * -1, CV: volt, CS: soc}).to_csv(index=False).encode("utf-8")   # BMS current is charge-positive: logged = true + offset


def build(n_drives=36, days=18, qcap_by_week=None, **kw):
    rows, store = [], {}
    d0 = pd.Timestamp("2026-06-01")
    for i in range(n_drives):
        day = d0 + pd.Timedelta(days=i % days)
        f = "d%02d.csv" % i
        wk = int(day.isocalendar()[1]) % 2
        q = qcap_by_week[wk] if qcap_by_week else kw.get("qcap", 5.0)
        store[f] = drive(1000 + i, **{**kw, "qcap": q})
        rows.append({"file": f, "date": str(day.date()), "ens_outlier_v2": "False"})
    return pd.DataFrame(rows), store


master, store = build()
calls = []
real_extract = CB.extract_drive
CB.extract_drive = lambda b: (calls.append(1), real_extract(b))[1]
with tempfile.TemporaryDirectory() as td:
    sha = lambda f: __import__("hashlib").sha256(store[f]).hexdigest()
    recs = CB.load_records(master, lambda f: store.get(f), sha, td)
    assert len(calls) == len(master) and all(r is not None for r in recs.values())
    CB.load_records(master, lambda f: store.get(f), sha, td)                       # unchanged bytes -> cache hit, nothing re-extracted
    assert len(calls) == len(master)
    store["d00.csv"] = drive(99999)                                                  # changed bytes -> only that drive
    CB.load_records(master, lambda f: store.get(f), sha, td)
    assert len(calls) == len(master) + 1
    store["d00.csv"] = drive(1000)
CB.extract_drive = real_extract
blk = CB.estimate(master, recs)

a = blk["ahPer100"]
# B recovers the true 5.0 Ah per 100 points; its CI covers it and excludes the 2.1 kWh-equivalent (6.0 Ah at 350 V)
assert abs(a["point"] - 5.0) < 0.15 and a["bootstrapCI95"][0] <= 5.0 <= a["bootstrapCI95"][1] and a["bootstrapCI95"][1] < 5.9, a
# the drift term recovers the injected constant current offset (0.3 A)
assert abs(blk["currentOffsetFitA"]["value"] - 0.3) < 0.1, blk["currentOffsetFitA"]
# energy: terminal kWh per 100 ~ 5.0 Ah x 350 V = 1.75 kWh (not 2.1)
assert abs(blk["kWhPer100"]["point"] - 1.75) < 0.07, blk["kWhPer100"]
# reverse regression and segment-level A bracket / attenuate as documented; windows agree with B within a few percent
assert blk["eventsB"]["reverseAh100"] >= a["point"] - 0.05
assert abs(blk["eventsB"]["segmentAAh100"] - 5.0) < 0.9
for k in ("5", "10", "15"):
    w = blk["windows"][k]
    assert w and w["n"] > 20 and abs(w["Q_Ah"]["est"] - 5.0) < 0.25, (k, w)
assert abs(blk["wholeDrive"]["Q_Ah"]["est"] - 5.0) < 0.5
# method range is a min-max over the fixed list, reported separately from the CI (never merged)
ent = {k: v for k, v in a["methodRangeEntries"].items() if v is not None}
assert a["methodRange"] == [min(ent.values()), max(ent.values())] and "never merged" in a["reporting"]
# matched-support lag scenarios use identical windows; on an asymmetric (sawtooth) current they move the estimate - a scenario sensitivity, not a CI
ml, sl = build(n_drives=36, days=18, shape="saw")
rl = {f: real_extract(sl[f]) for f in ml["file"]}
lg = CB.estimate(ml, rl)["lag"]
assert lg["matchedWindows"] > 20 and lg["-2"] and lg["2"] and lg["-2"]["n"] == lg["0"]["n"] == lg["2"]["n"], lg
# the charge model's drift term absorbs most of a lag in this synthetic: the lag shows up in the fitted bias (monotone in the lag) while the scale stays at the truth
assert abs(lg["0"]["Q_Ah"]["est"] - 5.0) < 0.1 and lg["-2"]["bias_A"]["est"] < lg["0"]["bias_A"]["est"] < lg["2"]["bias_A"]["est"], lg
assert lg["2"]["bias_A"]["est"] - lg["-2"]["bias_A"]["est"] > 0.3, lg
# a drive whose SoC lags the current by 3 s gives a different apparent scale than the synchronous one (the estimators are lag-sensitive)
md, sd = build(n_drives=18, days=9, shape="saw", soc_delay=3.0)
rd = {f: real_extract(sd[f]) for f in md["file"]}
b2 = CB.estimate(md, rd)["windows"]["10"]["bias_A"]["est"]
b0 = CB.estimate(ml.iloc[:18], {f: rl[f] for f in ml["file"].iloc[:18]})["windows"]["10"]["bias_A"]["est"]
assert abs(b2 - b0) > 0.2, (b2, b0)

# test (a): homogeneous odd/even weeks are equivalent; a real difference (5.0 vs 6.5 Ah) is NOT (the test can fail)
ta = blk["testA_oddEvenWeeks"]
assert ta["evaluable"] and ta["powered"] and ta["equivalent"] and abs(ta["difference"]) < 0.25, ta
mh, sh = build(n_drives=36, days=18, qcap_by_week={0: 5.0, 1: 6.5})
rh = {f: real_extract(sh[f]) for f in mh["file"]}
th = CB.estimate(mh, rh)["testA_oddEvenWeeks"]
assert th["evaluable"] and not th["equivalent"] and abs(th["difference"]) > 0.5 and "escalate" in th["outcome"], th

# test (d): NaN-flag drives are outside the primary population; they are added and the delta is reported (k = 0 is 'no effect', not a pass)
assert blk["testD_nanFlagDrives"]["nNanFlagDrives"] == 0 and blk["testD_nanFlagDrives"]["outcome"] == "no effect, k = 0"
mn = master.copy()
mn.loc[:3, "ens_outlier_v2"] = np.nan
bn = CB.estimate(mn, recs)
assert bn["population"]["nDrives"] == len(master) - 4 and bn["testD_nanFlagDrives"]["nWithUsableSeries"] == 4 and bn["testD_nanFlagDrives"]["delta"] is not None
mt = master.copy()
mt.loc[:3, "ens_outlier_v2"] = "True"
assert CB.estimate(mt, recs)["population"]["nDrives"] == len(master) - 4

# SoC = 0 artefacts never define events or support
z = real_extract(drive(7, zero_soc_rows=(100, 101, 700)))
ev_levels = np.concatenate([sg["ev"]["lev"] for sg in z["variants"]["primary"] if "ev" in sg])
assert z is not None and ev_levels.min() > 30, ev_levels.min()
# the audit-package (literal) window definition carries the documented endpoint-selection bias: it reads below the truth while the anchored windows do not, and it is in the method range
lit = a["methodRangeEntries"]["W10_literal"]
assert 4.6 < lit < 4.97 and lit < blk["windows"]["10"]["Q_Ah"]["est"] - 0.05 and blk["windowsLiteral10"]["matchedWindows"] > 20, (lit, blk["windows"]["10"]["Q_Ah"]["est"])
assert a["methodRange"][0] <= lit
# integration-policy variants exist and the 3 s gap cap / ZOH do not change a gap-free synthetic drive materially
assert abs(a["methodRangeEntries"]["B_gap3s"] - a["point"]) < 0.15 and abs(a["methodRangeEntries"]["B_zoh"] - a["point"]) < 0.2

# grouped_fit: singular bootstrap draws are skipped and counted; a design that is singular on the full data returns None
di = np.array([0] * 20 + [1] * 20)
X = np.column_stack([np.r_[np.arange(20.0), np.zeros(20)], np.ones(40)]) * np.array([[1, 0]]) + np.column_stack([np.zeros(40), np.r_[np.ones(20), np.zeros(20)]])
y = np.r_[2.0 * np.arange(20.0), np.zeros(20)]
Wd = CB.boot_weights(2, 200)
r = CB.grouped_fit(di, np.column_stack([np.r_[np.arange(20.0), np.zeros(20)]]), y, 2, Wd, lambda b: b[0])
assert r["est"] > 1.99 and r["nDrawsUsed"] < 200 and r["nDrawsUsed"] > 0, r                      # draws that pick only the zero day are singular
assert CB.grouped_fit(di, np.zeros((40, 1)), y, 2, Wd, lambda b: b[0]) is None
# estimates are deterministic (seed 42, fixed draws)
assert CB.estimate(master, recs) == blk
# splice: only capacityBasis, its stamp and CAP_AH_RATED change; a second run with the same block and corpus hash changes nothing (the stamp keeps its generatedAt)
A0 = {"x": 1, "constantProvenance": {"CAP_KWH": {"value": 2.1}}, "_artifactStamps": {"fuelContract": {"corpusHash": "old", "generatedAt": "t0", "carriedForward": True}}}
cfg = {"auditMetadata": {"constantProvenance": {"CAP_AH_RATED": {"value": 5.0, "class": "documentary"}}}}
A1, ch1, bad1 = CB.splice(A0, {"k": 1}, cfg, "md5a")
assert not bad1 and set(ch1) == {"/capacityBasis", "/constantProvenance/CAP_AH_RATED", "/_artifactStamps/capacityBasis"}, (ch1, bad1)
assert A1["_artifactStamps"]["capacityBasis"]["corpusHash"] == "md5a" and "carriedForward" not in A1["_artifactStamps"]["capacityBasis"] and A0["x"] == A1["x"]
A2, ch2, bad2 = CB.splice(A1, {"k": 1}, cfg, "md5a")
assert ch2 == [] and A2 == A1
A3, ch3, _ = CB.splice(A1, {"k": 2}, cfg, "md5a")
assert "/capacityBasis/k" in ch3 or "/capacityBasis" in ch3
print("OK test_capacity_basis: B %.3f Ah/100 CI %s, kWh/100 %.3f, range %s" % (a["point"], a["bootstrapCI95"], blk["kWhPer100"]["point"], a["methodRange"]))
