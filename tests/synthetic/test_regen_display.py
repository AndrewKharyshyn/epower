"""M446 known-answer tests of the cadence-stratified native display layer (spec analyses/M446_spec.md Rev 1.1, sections 3-9 and 16): tools/regen_display.py.
(1) stratum assignment (< 1.0 s fast, >= 1.0 s slow, undefined = neither, held out); (2) weighted quantiles (lower convention); (3) b_nat = max |native - decimated| per stratum and cell, signed shift and factor, never borrowed, absent when
not computable; (4) drift flag; (5) narrative extrema use supported cells only and carry no 'peak'; extent includes interval, mass range and bracket; (6) zone rows are sums of the drawn 10 km/h bins; (7) the two strata plus the rest
reconcile to the pooled totals; (8) Simpson fixture per stratum: identical within-SOC recovery, different SOC mixes -> different observed rows, EQUAL standardized bars, with ONE fixed reference mix; (9) b_nat on a scaled decimated
table is the known fraction of the cell value (fast: factor 3 wins; slow: common-support mean of two phases)."""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import compute_summary_arrays as C
import regen_v2 as R
import regen_v2_cache as K
import regen_v2_agg as G
import regen_std as RS
import regen_display as D

SP, RPM, I_, V_ = "[VCM] Vehicle Speed (km/h)", "Оберти двигуна (rpm)", "[BMS] HV Battery Current (A)", "[BMS] HV Battery voltage (V)"
SOC = "[BMS] HV State of charge (%)"
TC = ["[BMS] HV Battery Temperature Sensor %d (℃)" % k for k in (1, 2, 3, 4)]
T0 = pd.Timestamp("2026-03-01 10:00:00")
CUR = {57.0: 10.0, 67.0: 20.0}


def brake(soc, temp, cur, v0=80, n=9, step=8):
    sec = np.arange(n, dtype=float)
    d = {"time": T0 + pd.to_timedelta(sec, unit="s"), SP: np.array([v0 - step * k for k in range(n)], float), RPM: np.zeros(n), I_: np.full(n, cur, float), V_: np.full(n, 360.0), SOC: np.full(n, soc, float)}
    for c in TC:
        d[c] = np.full(n, float(temp))
    return pd.DataFrame(d)


def table(frames):
    cols = {k: [] for k in ["iv_" + k for k in K.IV_KEYS] + ["bin_dv2", "bin_charge", "bin_touch", "iv_chargeOff", "bin_chargeOff", "drive"]}
    for di, fr in enumerate(frames):
        r = R.extract_drive(fr, C=C, i_off=0.4)
        iv, bins = r["intervals"], r["bins"]
        for k in K.IV_KEYS:
            cols["iv_" + k].append(iv[k])
        cols["bin_dv2"].append(bins["dv2"]); cols["bin_charge"].append(bins["charge"]); cols["bin_touch"].append(bins["touch"])
        cols["iv_chargeOff"].append(iv["chargeOff"]); cols["bin_chargeOff"].append(bins["chargeOff"]); cols["drive"].append(np.full(len(iv["t0"]), di, np.int32))
    return {k: np.concatenate(v) for k, v in cols.items()}


def build2(mixes, ndays=8):
    """mixes = {'fast': {temp: {soc: ndrives}}, 'slow': {...}}; fast drives first. Returns (T, dm)."""
    frames, dates, ev = [], [], []
    i = 0
    for stratum, mix in mixes.items():
        for temp, socs in mix.items():
            for soc, n in socs.items():
                for _ in range(n):
                    frames.append(brake(soc, temp, CUR[soc]))
                    dates.append((pd.Timestamp("2026-03-01") + pd.Timedelta(days=i % ndays)).strftime("%Y-%m-%d"))
                    ev.append(0.5 if stratum == "fast" else 2.0)
                    i += 1
    dm = pd.DataFrame({"file": ["d%d.csv" % k for k in range(len(frames))], "date": dates, "drive_type": ["urban"] * len(frames), "ev_rpm_dt_med_s": ev})
    return table(frames), dm


# (1) strata
assert D.stratum_of(0.99) == "fast" and D.stratum_of(1.0) == "slow" and D.stratum_of(2.4) == "slow"
assert D.stratum_of(float("nan")) is None and D.stratum_of(None) is None
sm = D.stratum_masks([0.5, 1.0, np.nan, 0.9], held=np.array([False, False, False, True]))
assert sm["fast"].tolist() == [True, False, False, False] and sm["slow"].tolist() == [False, True, False, False]          # undefined = neither; held out of both

# (2) weighted quantiles (lower convention)
assert D.wquantiles([1, 2, 3], [1, 1, 2]) == [1.0, 2.0, 3.0]                                      # cumulative 1, 2, 4: q 0.25 -> 1, 0.5 -> 2, 0.75 -> 3
assert D.wquantiles([3, 1, 2], [2, 1, 1], qs=(0.5,)) == [2.0]                                  # cumulative 1, 2, 4 -> 0.5 * 4 = 2 -> the value 2
assert D.wquantiles([5.0], [0.0]) == [None, None, None] and D.wquantiles([], []) == [None, None, None]

# (3) b_nat
assert D.b_nat({2: 0.4, 3: -1.1}) == (1.1, -1.1, 3)
assert D.b_nat({2: 0.4}) == (0.4, 0.4, 2)
assert D.b_nat({2: None, 3: float("nan")}) == (None, None, None)
assert D.b_nat({2: -0.5, 3: 0.5})[2] == 2                                                         # tie: the lower factor

# (4) drift flag
assert D.drift_flag(1.5, 1.2) is True and D.drift_flag(1.3, 1.2) is False and D.drift_flag(None, 1.2) is None

# (5) narrative / extent
rows = {"a": {"eff": 50.0, "status": "thin"}, "b": {"eff": 60.0, "status": "supported", "ci95": [58.0, 63.0], "massRange": [59.0, 61.0], "bNat": 2.0}, "c": {"eff": 70.0, "status": "supported"}, "d": {"eff": 90.0, "status": "failed"},
        "e": {"eff": None, "status": "empty"}}
nv = D.narrative(rows, ["a", "b", "c", "d", "e"])
assert nv["effMin"] == 60.0 and nv["effMinLabel"] == "b" and nv["effMax"] == 70.0 and nv["effMaxLabel"] == "c" and nv["thin"] == ["a"] and nv["nSupported"] == 2
assert not any("peak" in k.lower() for k in nv)
assert D.extent(rows, ["a", "b", "c", "d", "e"]) == [50.0, 70.0]                              # b: 58..63 / 59..61 / 58..62; a: 50; c: 70; the failed cell (90) is not drawn
assert D.extent({"x": {"eff": 60.0, "status": "supported", "bNat": 5.0}}, ["x"]) == [55.0, 65.0]
assert D.extent({}, []) is None

# (6) zones are sums of the drawn 10 km/h bins
T, dm = build2({"fast": {25.0: {57.0: 4}}})
co = G.Cohort(T, dm, np.ones(len(dm), bool), "t")
mz, lz = D.mats_of(co, "zones10")
ms, ls = co.mats("speed")
assert lz == ["10-30", "30-60", "60-90", "90-120", "120-130"]
assert abs(mz["dv2"].sum() - ms["dv2"][:, 1:].sum()) < 1e-9 and abs(mz["charge"].sum() - ms["charge"][:, 1:].sum()) < 1e-9          # the 0-10 km/h bin is not in any zone
assert abs(mz["dv2"][:, 0].sum() - ms["dv2"][:, 1:3].sum()) < 1e-9

# (7) + (8) Simpson fixture per stratum, ONE fixed reference mix, reconciliation
MIX = {"fast": {25.0: {57.0: 90, 67.0: 30}, 35.0: {57.0: 30, 67.0: 90}}, "slow": {25.0: {57.0: 30, 67.0: 90}, 35.0: {57.0: 90, 67.0: 30}}}
T, dm = build2(MIX)
ev = dm["ev_rpm_dt_med_s"].values
smk = D.stratum_masks(ev)
co_pool = G.Cohort(T, dm, np.ones(len(dm), bool), "pool")
labels_t, Jt = RS.joint(co_pool, "temperature", RS.soc_strata(co_pool))
w, _ = RS.reference_weights(Jt, list(range(len(labels_t))))
assert abs(sum(w.values()) - 1.0) < 1e-12                                                       # ONE reference mix, summing to 1
bn0 = {v: {s: {} for s in D.SELS} for v in D.VIEWS}
ivmed = np.full(len(dm), 0.5)
blocks, tot = {}, {"keKwh": 0.0, "chargeKwh": 0.0, "n": 0}
for p in D.STRATA:
    co = G.Cohort(T, dm, smk[p], p)
    blocks[p] = D.stratum_block(co, w, bn0, ivmed, np.zeros(len(dm), bool))
    t = co.cell_block("all", np.ones(len(co.drive), bool))["all"]
    for k in tot:
        tot[k] += t[k]
tp = co_pool.cell_block("all", np.ones(len(co_pool.drive), bool))["all"]
assert abs(tot["keKwh"] - tp["keKwh"]) < 1e-4 and abs(tot["chargeKwh"] - tp["chargeKwh"]) < 1e-4 and tot["n"] == tp["n"]       # strata reconcile to the pooled totals
std = {p: blocks[p]["standardized"]["temperature"] for p in D.STRATA}
for p in D.STRATA:
    assert std[p]["availability"]["available"], std[p]["availability"]
    vals = [b["standardized"] for b in std[p]["bars"].values()]
    assert len(vals) == 2 and abs(vals[0] - vals[1]) < 1e-9, (p, vals)                          # identical within-SOC recovery -> EQUAL standardized bars
    obs = [r["eff"] for r in blocks[p]["views"]["temperature"]["bySoc"]["allSoc"]["rows"].values() if r.get("eff") is not None]
    assert len(obs) == 2 and abs(obs[0] - obs[1]) > 2.0, (p, obs)                              # different SOC mixes -> different observed rows
assert abs(list(std["fast"]["bars"].values())[0]["standardized"] - list(std["slow"]["bars"].values())[0]["standardized"]) < 1e-9          # same cell values, same fixed weights -> equal across strata
row = blocks["fast"]["views"]["temperature"]["bySoc"]["allSoc"]["rows"]["20–30°C"]
assert row["bNat"] is None and row["bNatF"] is None and "conventionRange" in row                  # no decimated table -> no resolution bracket (never borrowed)
assert blocks["fast"]["views"]["speed"]["bySoc"]["allSoc"]["rows"]["0-10"]["payloadOnly"] is True and "payloadOnly" not in blocks["fast"]["views"]["speed"]["bySoc"]["allSoc"]["rows"]["10-20"]
assert blocks["fast"]["views"]["temperature"]["bySoc"]["allSoc"]["sampling"]["20–30°C"]["speedDtS"][1] == 1.0

# (9) b_nat on a scaled decimated table: a known fraction of the cell value
T, dm = build2({"fast": {25.0: {57.0: 40}}})
def scaled(Tn, f):
    Td = {k: v.copy() for k, v in Tn.items()}
    for k in ("iv_charge", "iv_chargeOff", "bin_charge", "bin_chargeOff"):
        Td[k] = Td[k] * f
    return Td
co_n = G.Cohort(T, dm, np.ones(len(dm), bool), "n")
eff = co_n.cell_block("temperature", co_n.sel["allSoc"])["20–30°C"]["eff"]
m = np.ones(len(dm), bool)
days = list(co_n.days)
bnf = D.bnat_tables(dm, T, {2: scaled(T, 0.9), 3: scaled(T, 0.8)}, m, days, "fast", None)
b = bnf["temperature"]["allSoc"]["20–30°C"]
assert abs(b["bNat"] - 0.2 * eff) < 0.02 and b["shiftPp"] > 0 and "<-10°C" not in bnf["temperature"]["allSoc"]          # empty cells have no bracket
allrows = np.ones(len(T["drive"]), bool)
bns = D.bnat_tables(dm, T, None, m, days, "slow", {2: [(allrows, allrows, scaled(T, 0.95)), (allrows, allrows, scaled(T, 0.95))]})
assert abs(bns["temperature"]["allSoc"]["20–30°C"]["bNat"] - 0.05 * eff) < 0.01 and bns["temperature"]["allSoc"]["20–30°C"]["f"] == 2          # slow: f = 2 only, mean of the two phases
# (10) Rev 1.3: status reason, ci suppression below 5 days, convention flag, step labels, slow phase cancellation, extrema resolution
assert D.status_reason({"status": "supported"}) is None and D.status_reason({"status": "empty"}) == "no qualifying intervals"
assert "n 120 < 200" in D.status_reason({"status": "thin", "n": 120, "drives": 12, "days": 6}) and "drives" not in D.status_reason({"status": "thin", "n": 120, "drives": 12, "days": 6})
assert D.cell({"ci95": [1.0, 2.0], "days": 4, "precisionHalfWidth": 0.5, "n": 9})["ciSuppressed"] == "days<5" and D.cell({"ci95": [1.0, 2.0], "days": 5})["ci95"] == [1.0, 2.0]
assert D.convention_sensitive({"eff": 60.0, "ci95": [58.0, 62.0], "conventionRange": {"strictOnly": 57.0, "keptPlusTrimmed": 61.0}}) is True
assert D.convention_sensitive({"eff": 60.0, "ci95": [58.0, 62.0], "conventionRange": {"strictOnly": 59.0, "keptPlusTrimmed": 61.0}}) is False
assert D.convention_sensitive({"eff": 60.0, "ci95": None, "massRange": [59.0, 61.0], "conventionRange": {"strictOnly": 62.0, "keptPlusTrimmed": None}}) is True
assert D.step_label([0.5, 3.0], 2.0, 0.5, 0.5) == "resolved" and D.step_label([0.5, 3.0], 2.0, 1.0, 1.0) == "not resolved" and D.step_label([-0.5, 3.0], 2.0, 0.1, 0.1) == "not resolved"
assert D.step_label(None, 2.0, 0.1, 0.1) == "not evaluable" and D.step_label([0.5, 3.0], 2.0, None, 0.1) == "not evaluable"
nv2 = D.extrema_resolution({"effMax": 70.0, "effMaxLabel": "c", "effMin": 60.0, "effMinLabel": "b"}, [{"a": "b", "b": "c", "stepPp": 10.0, "label": "resolved"}])
assert nv2["effMaxStepsResolved"] is True and nv2["effMinStepsResolved"] is True                # the single resolved step rises from the minimum to the maximum
nv3 = D.extrema_resolution({"effMax": 70.0, "effMaxLabel": "c", "effMin": 60.0, "effMinLabel": "b"}, [{"a": "b", "b": "c", "stepPp": 10.0, "label": "not resolved"}])
assert nv3["effMaxStepsResolved"] is False
nv4 = D.extrema_resolution({"effMax": 70.0, "effMaxLabel": "c", "effMin": 60.0, "effMinLabel": "b"}, [{"a": "b", "b": "c", "stepPp": -10.0, "label": "resolved"}])
assert nv4["effMaxStepsResolved"] is False and nv4["effMinStepsResolved"] is False                # a resolved step in the wrong direction does not support the extremum
assert D.extrema_resolution({"effMax": 1.0, "effMaxLabel": "z", "effMin": 1.0, "effMinLabel": "z"}, [])["effMaxStepsResolved"] is None
# slow b_nat: opposite phase shifts cancel in the signed mean; the per-phase values and the maximum-absolute alternative are stored
Tp = {k: v.copy() for k, v in T.items()}
bns2 = D.bnat_tables(dm, T, None, m, days, "slow", {2: [(allrows, allrows, scaled(T, 0.9)), (allrows, allrows, scaled(T, 1.1))]})
c2 = bns2["temperature"]["allSoc"]["20–30°C"]
assert c2["phaseCancel"] is True and c2["bNat"] < 0.01 * eff and abs(c2["bNatMaxPhase"] - 0.1 * eff) < 0.02 and len(c2["phaseDiffs"]) == 2
assert bns["temperature"]["allSoc"]["20–30°C"]["phaseCancel"] is False
print("test_regen_display: all known-answer tests passed")
