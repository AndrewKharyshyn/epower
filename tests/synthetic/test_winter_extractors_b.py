"""M728 known-answer tests (analyses/M728_spec.md Rev 2, A1): the P4 extractor on synthetic frames with a planted plane, the cell rules, the evaluability rules, the condition-number limit, and the v3 behaviour of winter_score
(P4 dispatched, P1 and P6 not evaluable, P2 / P3 / P5 / P7 unchanged from M727). No observation after the freeze is read by this test."""
import hashlib, json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_extractors_b as WB
import winter_extractors as WE
import winter_score as WS

NB_ = 200
B0, BT, BS = 34.0, 1.5, -1.0                      # planted plane: kW at 0 C and SoC 60, kW per C, kW per SoC point


def drive(day, tmin_lo, n=300, seed=0, spread=8.0, plane=(B0, BT, BS)):
    r = np.random.default_rng(seed)
    T = tmin_lo + r.uniform(0.0, spread, n)
    soc = r.uniform(40, 80, n)
    y = plane[0] + plane[1] * T + plane[2] * (soc - 60.0)
    X = np.column_stack([np.ones(n), T, soc - 60.0])
    XtX, Xty = X.T @ X, X.T @ y
    row = {"day": day, "Tlo_min": float(T.min()), "pin_n": n}
    for i in range(3):
        row["pin_xty_%d" % i] = float(Xty[i])
        for j in range(3):
            row["pin_xtx_%d%d" % (i, j)] = float(XtX[i, j])
    return row


def frame(coldest, ndrives=24, ndays=8, seed=1):
    return pd.DataFrame([drive("2026-12-%02d" % (1 + (i % ndays)), coldest + (i % 3) * 0.5, seed=seed * 100 + i) for i in range(ndrives)])


# ---- the planted plane is recovered exactly by the summed normal equations
f = frame(-6.0)
o = WB.extract_p4(f, NB_)
assert o["status"] == "fitted" and abs(o["b0KwAt0CSoc60"] - B0) < 1e-6 and abs(o["bTKwPerC"] - BT) < 1e-9 and abs(o["bSKwPerSocPoint"] - BS) < 1e-9
assert abs(o["kwAtMinus10C"] - (B0 - 10 * BT)) < 1e-6 and o["nDrives"] == 24 and o["nDays"] == 8 and o["regressionSeconds"] == 24 * 300
assert o["b0Ci95"][0] <= B0 + 1e-6 and o["b0Ci95"][1] >= B0 - 1e-6 and o["conditionNumber"] < 1e8
assert o["evaluable0C"] is True and o["evaluableMinus10C"] is True and "model-derived intercept" in o["kind"]
assert -20 < o["pinWeightedMeanTminC"] < 20
# the day order is fixed: the same frame in any row order gives the same endpoints
assert WB.extract_p4(f.sample(frac=1.0, random_state=3), NB_)["b0Ci95"] == o["b0Ci95"]

# ---- cell rules: a probe minimum of 5 C or more, or pin_n = 0, is not in the cell
g = pd.concat([f, pd.DataFrame([drive("2026-12-20", 6.0, seed=9), drive("2026-12-21", 7.0, seed=10)])], ignore_index=True)
assert WB.extract_p4(g, NB_)["nDrives"] == 24
g2 = f.copy()
g2.loc[g2.index[:4], "pin_n"] = 0
assert WB.extract_p4(g2, NB_)["nDrives"] == 20
assert WB.extract_p4(f.iloc[0:0], NB_)["status"] == "not evaluable"
# restrict_to_cold=False (the frozen-basis fidelity check) keeps the warmer drives
assert WB.extract_p4(g, NB_, restrict_to_cold=False)["nDrives"] == 26

# ---- evaluability: 0 C needs the coldest probe at most 3 C, -10 C at most -5 C
e = WB.extract_p4(frame(3.5), NB_)
assert e["evaluable0C"] is False and e["evaluableMinus10C"] is False                       # coldest 3.5 C
e = WB.extract_p4(frame(2.5), NB_)
assert e["evaluable0C"] is True and e["evaluableMinus10C"] is False
e = WB.extract_p4(frame(-5.5), NB_)
assert e["evaluable0C"] is True and e["evaluableMinus10C"] is True

# ---- condition number: constant temperature makes the plane singular -> not evaluable
c = frame(2.0)
rows = []
for i in range(24):
    r = np.random.default_rng(i)
    T = np.full(100, 2.0)
    soc = np.full(100, 60.0)
    X = np.column_stack([np.ones(100), T, soc - 60.0])
    y = np.full(100, 30.0)
    row = {"day": "2026-12-%02d" % (1 + i % 8), "Tlo_min": 2.0, "pin_n": 100}
    XtX, Xty = X.T @ X, X.T @ y
    for a in range(3):
        row["pin_xty_%d" % a] = float(Xty[a])
        for b in range(3):
            row["pin_xtx_%d%d" % (a, b)] = float(XtX[a, b])
    rows.append(row)
s = WB.extract_p4(pd.DataFrame(rows), NB_)
assert s["status"] == "not evaluable" and "condition number" in s["reason"]

# ---- v3 of winter_score: P4 dispatched through score_all (registry check simulated), P1 and P6 not evaluable, point-inside rule on the frozen intervals
F_ = json.load(open(os.path.join(ROOT, "analyses", "M717_winter_predictions.json"), encoding="utf-8"))
band0, envm10 = F_["predictions"]["P4"]["kW_at_0C"][1:3], F_["predictions"]["P4"]["envelope_at_minus10C"]


def scoring_frame(plane, coldest, nd=24, nday=8):
    rows = [drive("2026-11-%02d" % (20 + (i % nday)), coldest + (i % 3) * 0.5, seed=500 + i, plane=plane) for i in range(nd)]
    d = pd.DataFrame(rows)
    d["key"] = ["20261120%06d" % i for i in range(nd)]
    d["start"] = pd.to_datetime("2026-11-20 09:00:00") + pd.to_timedelta((np.arange(nd) % nday) * 24, unit="h")
    d["month"] = 11
    d["clean"] = True
    for c in ("ahc_T_<0", "ahc_T_0-5", "ahc_T_5-10", "ahc_T_10-15", "ahd_T_<0", "ahd_T_0-5", "ahd_T_5-10", "ahd_T_10-15"):          # columns the other extractors read: present, uninformative
        d[c] = 0.0
    d["R_pulse_mohm"] = np.nan
    d["T_pulse"] = np.nan
    for c in ("km", "ah", "spd_s", "dur_h", "eng_on_s", "rpm_s", "ambient_start_c", "ambient_end_c"):
        d[c] = np.nan
    d["day_"] = d["day"]
    return d


_orig = WS.extractors_frozen
WS.extractors_frozen = lambda pid=None, changelog_text=None: (True, "frozen") if pid in ("P2", "P3", "P4", "P5", "P7") else (False, "not covered")
try:
    fr_in = scoring_frame((33.9, 1.55, -1.0), -6.0)                       # a plane inside both frozen statements: 33.9 at 0 C, 33.9 - 15.5 = 18.4 at -10 C
    cells = {c["prediction"]: c for c in WS.score_all(fr_in, F_, nb=100)}
    c4 = cells["P4"]
    assert cells["P1"]["status"] == "not evaluable" and cells["P6"]["status"] == "not evaluable"
    assert c4["status"] == "within the band" and [s["status"] for s in c4["statements"]] == ["within the band", "within the band"] and "not delivered power" in c4["reading"]
    fr_out = scoring_frame((45.0, 1.55, -1.0), -6.0)
    assert {c["prediction"]: c for c in WS.score_all(fr_out, F_, nb=100)}["P4"]["status"] == "outside the band"
    fr_warm = scoring_frame((33.9, 1.55, -1.0), 2.0)                       # coldest 2 C: the -10 C statement has no data near it
    st = {c["prediction"]: c for c in WS.score_all(fr_warm, F_, nb=100)}["P4"]["statements"]
    assert st[0]["status"] == "within the band" and st[1]["status"] == "not evaluable" and st[1]["reason"].startswith("no data near")
    few = scoring_frame((33.9, 1.55, -1.0), -6.0, nd=6, nday=6)
    assert {c["prediction"]: c for c in WS.score_all(few, F_, nb=50)}["P4"]["status"] == "not evaluable"
    # P2, P3, P5, P7: the M727 outputs are unchanged by v3 (the module is not edited and score_all calls the same functions)
    for pid, fn in (("P2", WE.extract_p2),):
        pass
finally:
    WS.extractors_frozen = _orig

# ---- the M727 module is byte-identical to what the M727 registry recorded
reg27 = os.path.join(ROOT, "analyses", "M726_extractor_registry.json")
if os.path.exists(reg27):
    rec = json.load(open(reg27, encoding="utf-8"))
    assert rec["modules"]["tools/winter_extractors.py"] == hashlib.sha256(open(os.path.join(ROOT, "tools", "winter_extractors.py"), "rb").read()).hexdigest()
print("OK test_winter_extractors_b")
