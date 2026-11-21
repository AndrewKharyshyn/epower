"""M727 known-answer tests (analyses/M727_spec.md Rev 2, A1): the extractors of P2, P3, P5, P7 on synthetic frames with planted truth, the cell rules, and the v2 behaviour of winter_score (registry per prediction id).
No observation after the freeze is read by this test."""
import math, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_extractors as WE

rng = np.random.default_rng(7)
NB_ = 200


def frame(n, days, a_lo, a_hi, month=11, seed=0):
    r = np.random.default_rng(seed)
    km = np.exp(r.uniform(math.log(1.0), math.log(30.0), n))
    dur = km / r.uniform(25, 90, n)
    A = r.uniform(a_lo, a_hi, n)
    d = pd.DataFrame({"key": ["k%05d" % (seed * 1000 + i) for i in range(n)], "day": ["2026-11-%02d" % (1 + (i % days)) for i in range(n)], "month": month,
                      "km": km, "dur_h": dur, "ah": km * 0.3, "spd_s": 600.0, "rpm_s": 1000.0, "eng_on_s": 300.0, "ambient_start_c": A, "ambient_end_c": A,
                      "R_pulse_mohm": 100.0, "T_pulse": 0.0})
    return d


# ---- P2: ratio of sums over the temperature bins
d = frame(20, 5, 0, 10)
for c in ("ahc_T_<0", "ahc_T_0-5", "ahc_T_5-10", "ahc_T_10-15", "ahd_T_<0", "ahd_T_0-5", "ahd_T_5-10", "ahd_T_10-15"):
    d[c] = 0.0
d["ahc_T_5-10"] = 1.0
d["ahd_T_0-5"] = 2.0
d["ahc_T_10-15"] = 7.0                                            # 3 of 10 Ah below 10 C in every drive
o = WE.extract_p2(d, NB_)
assert abs(o["estimate"] - 0.3) < 1e-12 and o["nDrives"] == 20 and o["nDays"] == 5 and o["ci95"][0] <= 0.3 <= o["ci95"][1]
d.loc[d.index[:10], "ahc_T_10-15"] = 0.0                          # pooled: (10 x 3 + 10 x 3) / (10 x 3 + 10 x 10) = 60 / 130
o = WE.extract_p2(d, NB_)
assert abs(o["estimate"] - 60.0 / 130.0) < 1e-12
assert WE.extract_p2(d.iloc[0:0], NB_)["estimate"] is None

# ---- P3: planted ratio at 0 C recovered exactly at any window temperature (correction with the frozen EaR)
EA, R25 = 25.0, 100.0                                              # kJ/mol, mOhm
d = frame(30, 6, 0, 10, seed=1)
T = np.linspace(-1.5, 1.8, 30)
ratio0 = 1.9
d["T_pulse"] = T
d["R_pulse_mohm"] = R25 * ratio0 * np.exp(EA * 1000.0 / WE.RGAS * (1.0 / (T + 273.15) - 1.0 / 273.15))
o = WE.extract_p3(d, EA, R25, nb=NB_)
assert abs(o["estimate"] - ratio0) < 1e-9 and o["nDrives"] == 30 and o["label"] == "interpolation check" and o["nPulsesBelow1C"] > 0 or o["label"] == "extrapolation test"
assert o["uncorrected"]["estimate"] != o["estimate"]
d2 = d.copy()
d2["T_pulse"] = 10.0                                                # outside the window -> no pulses
assert WE.extract_p3(d2, EA, R25, nb=NB_)["nDrives"] == 0
o = WE.extract_p3(d, EA, R25, window=WE.P3_WINDOW_SENS, nb=NB_)
assert o["nDrives"] == 30 and abs(o["estimate"] - ratio0) < 1e-9
d3 = d.copy()
d3.loc[d3.index[0], "R_pulse_mohm"] = 700.0                        # the prototype pulse filter 20 < R < 600
assert WE.extract_p3(d3, EA, R25, nb=NB_)["nDrives"] == 29

# ---- P7: planted cooling slope recovered exactly by the OLS with controls
d = frame(60, 12, -1, 19, seed=2)
d["day"] = ["2026-12-%02d" % (1 + (i % 12)) for i in range(60)]
coef_A = 0.8e-2                                                      # engine-on share (fraction) changes by -0.008 per C of ambient: cooling slope +0.8 points per C
d["eng_on_s"] = 1000.0 * (0.30 - coef_A * d["ambient_start_c"] + 0.001 * np.log(d["km"]) + 0.0001 * (d["km"] / d["dur_h"]))
o = WE.extract_p7(d, NB_)
assert abs(o["estimate"] - 0.8) < 1e-9, o["estimate"]
assert o["ci95"][0] <= 0.8 + 1e-9 and o["ci95"][1] >= 0.8 - 1e-9 and o["unit"] == "points per C of cooling"
dn = d.copy()
dn["ambient_start_c"] = dn["ambient_end_c"] = 5.0 + 0.01 * np.arange(len(dn))                     # IQR of A below 3 C
assert WE.extract_p7(dn, NB_)["status"] == "not evaluable"
dw = d.copy()
dw["spd_s"] = 30.0                                                    # prototype filter spd_s > 60 removes every drive
assert WE.extract_p7(dw, NB_)["estimate"] is None
dw = d.copy()
dw["ambient_start_c"] = dw["ambient_end_c"] = 25.0 + np.arange(len(dw)) * 0.2                    # all above 20 C
assert WE.extract_p7(dw, NB_)["estimate"] is None

# ---- P5: planted winter-minus-autumn ln(Ah/km) difference, matched cells, rule statistic
def sets_p5(dln, dT, n=60, seed=3):
    w = frame(n, 10, 2, 6, seed=seed)
    a = frame(n, 10, 2, 6, month=10, seed=seed + 1)
    a["km"] = w["km"].values                                          # the same trip lengths and speeds in both sets: matched cells coincide
    a["dur_h"] = w["dur_h"].values
    base = np.log(0.3)
    a["ah"] = a["km"] * np.exp(base)
    w["ah"] = w["km"] * np.exp(base + dln)
    a["ambient_start_c"] = a["ambient_end_c"] = 4.0 + dT
    w["ambient_start_c"] = w["ambient_end_c"] = 4.0
    return w, a

w, a = sets_p5(0.10, 10.0)
o = WE.extract_p5(w, a, NB_)
assert abs(o["dln"] - 0.10) < 1e-9 and abs(o["dTc"] - 10.0) < 1e-9 and abs(o["statistic"] - (0.10 - WE.P5_BOUND_PER_C * 10.0)) < 1e-9
assert o["status"] == "rejected" and abs(o["droppedShareOfWinterDrives"] - (1.0 - o["nWinter"] / 60.0)) < 1e-9 and abs(WE.P5_BOUND_PER_C - 0.005827) < 1e-6          # ln(1.06) / 10; the share of winter drives in cells without a partner is reported
w, a = sets_p5(0.04, 10.0)                                            # increase 4 % over a 10 C cooling is below the +6 % per 10 C bound
assert WE.extract_p5(w, a, NB_)["status"] == "not rejected"
w, a = sets_p5(0.10, 2.0)                                              # winter-autumn ambient difference below 3 C
assert WE.extract_p5(w, a, NB_)["status"] == "not evaluable"
w, a = sets_p5(0.10, 10.0)
a = a[a["km"] >= 3.0]                                                  # no autumn drive in the short cells: winter cells without a partner are dropped and the share reported
o = WE.extract_p5(w, a, NB_)
assert o["droppedShareOfWinterDrives"] > 0.0 and o["status"] in ("rejected", "not rejected")
assert WE.extract_p5(w.iloc[0:0], a, NB_)["status"] == "not evaluable"

# ---- Rev 3 (spec 8): P5 per-draw scheme reports the fixed-cell variant beside; P3 own-level sensitivity; P7 units
w, a = sets_p5(0.10, 10.0)
o = WE.extract_p5(w, a, NB_)
assert o["scheme"].startswith("per-draw") and "fixedCellVariant" in o and o["fixedCellVariant"]["status"] in ("rejected", "not rejected") and o["nUndefinedDraws"] == 0
assert abs(o["statistic"] - (0.10 - WE.P5_BOUND_PER_C * o["dTc"])) < 1e-9
# a sample where almost every draw has no eligible cell (3 drives per set on 3 days, a cell needs >= 3 in a draw) -> more than 1 % undefined -> not evaluable
w3, a3 = sets_p5(0.10, 10.0, n=60)
w3 = w3.iloc[:4].copy(); a3 = a3.iloc[:4].copy()
w3["km"] = a3["km"] = 5.0; w3["dur_h"] = a3["dur_h"] = 0.1; w3["day"] = ["2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04"]; a3["day"] = ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"]
w3["ah"] = a3["ah"] = 1.5
w3["km"] = a3["km"] = 5.0
o3 = WE.extract_p5(w3, a3, NB_)
assert o3["status"] in ("not evaluable", "rejected", "not rejected")
# P3 sensitivity against the frame's own 25 C level (labelled, separate from the primary estimate)
d = frame(30, 6, 0, 10, seed=1)
T = np.linspace(-1.5, 1.8, 30)
d["T_pulse"] = T
d["R_pulse_mohm"] = R25 * 1.9 * np.exp(EA * 1000.0 / WE.RGAS * (1.0 / (T + 273.15) - 1.0 / 273.15))
o = WE.extract_p3(d, EA, R25, nb=NB_, own25_mohm=R25 * 0.955)
assert abs(o["estimate"] - 1.9) < 1e-9 and abs(o["ownLevelSensitivity"]["estimate"] - 1.9 * R25 / (R25 * 0.955)) < 1e-9 and "never changes the status" in o["ownLevelSensitivity"]["label"]
assert WE.extract_p3(d, EA, R25, nb=NB_)["ownLevelSensitivity"] is None
# P7 units: the prototype coefficient of A is a fraction per C; the scoring output is -100 x coefficient (points per C of cooling)
d = frame(60, 12, -1, 19, seed=5)
d["day"] = ["2026-12-%02d" % (1 + (i % 12)) for i in range(60)]
coef_fraction = -0.00812
d["eng_on_s"] = 1000.0 * (0.30 + coef_fraction * d["ambient_start_c"] + 0.001 * np.log(d["km"]))
o = WE.extract_p7(d, NB_)
assert abs(o["estimate"] - (-100.0 * coef_fraction)) < 1e-9 and abs(o["coefficientOfA"] / 100.0 - coef_fraction) < 1e-12

# ---- score_all end to end on a synthetic frame (the registry check is simulated; the real registry is never read here)
import json
import winter_score as WS
F_ = json.load(open(os.path.join(ROOT, "analyses", "M717_winter_predictions.json"), encoding="utf-8"))
r25_, ea_ = F_["params"]["R_T"]["R25_mohm"], F_["params"]["R_T"]["EaR_kJmol"]


def full_frame(n_w, n_a, seed):
    w = frame(n_w, 8, 0, 8, month=11, seed=seed)
    w["start"] = pd.to_datetime("2026-11-20 09:00:00") + pd.to_timedelta(np.arange(n_w) * 7, unit="h") * 0 + pd.to_timedelta((np.arange(n_w) % 8) * 24, unit="h")
    a = frame(n_a, 12, 8, 16, month=10, seed=seed + 1)
    a["start"] = pd.to_datetime("2026-10-05 09:00:00") + pd.to_timedelta((np.arange(n_a) % 12) * 24, unit="h")
    fr = pd.concat([a, w], ignore_index=True)
    fr["clean"] = True
    for c in ("ahc_T_<0", "ahc_T_0-5", "ahc_T_5-10", "ahc_T_10-15", "ahd_T_<0", "ahd_T_0-5", "ahd_T_5-10", "ahd_T_10-15"):
        fr[c] = 0.0
    fr["ahc_T_5-10"] = 1.0
    fr["ahc_T_10-15"] = 9.0
    fr["T_pulse"] = 0.5
    fr["R_pulse_mohm"] = r25_ * 1.9
    return fr


frm = full_frame(30, 40, 11)
_orig = WS.extractors_frozen
WS.extractors_frozen = lambda pid=None, changelog_text=None: (True, "frozen") if pid in ("P2", "P3", "P5", "P7") else (False, "not covered")
try:
    cells = {c["prediction"]: c for c in WS.score_all(frm, F_, nb=100)}
    assert cells["P1"]["status"] == "not evaluable" and cells["P4"]["status"] == "not evaluable" and cells["P6"]["status"] == "not evaluable"          # not covered: no number
    assert cells["P2"]["status"] == "within the band" and abs(cells["P2"]["estimate"] - 0.1) < 1e-9 and "not the realised-ambient band" in cells["P2"]["scoredAgainst"]
    assert cells["P3"]["status"] in ("within the band", "outside the band") and cells["P3"]["rule"].startswith("point") and "ciInside" in cells["P3"]
    assert cells["P7"]["status"] in ("within the band", "outside the band", "not evaluable")
    assert cells["P5"]["status"] in ("rejected", "not rejected", "not evaluable")
    few = full_frame(6, 40, 12)                                              # a scoring set below the support rule (6 drives on 6 days): no number for any cell
    for c in WS.score_all(few, F_, nb=50):
        assert c["status"] == "not evaluable" and "estimate" not in c and "p025" not in c, c
    nowin = frm[frm["month"] != 11].copy()                                   # an empty scoring set
    for c in WS.score_all(nowin, F_, nb=50):
        assert c["status"] == "not evaluable", c
    unclean = frm.copy()
    unclean["clean"] = False                                                 # the clean flag removes every drive
    for c in WS.score_all(unclean, F_, nb=50):
        assert c["status"] == "not evaluable", c
finally:
    WS.extractors_frozen = _orig
print("OK test_winter_extractors")
