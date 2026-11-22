"""M732 known-answer tests of the P1 extractor (analyses/M732_spec.md Rev 2): planted chain with a closed form (tiny park and drive time constants, zero diurnal amplitude: the simulated start of drive k+1 is A0(k+1) + offset exactly,
the error is propagated and never reset), flag handling (propagate through a flagged join; the segmented sensitivity re-anchors), support rule, reading rule. No observation after the freeze is read."""
import os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_p1 as W1

PAR = {"driveHeating": {"c0_C": 20.0, "c1": 0.5, "tau_d_h": 1e-7, "alpha_C_per_A2h": 0.0}, "R_T": {"EaR_kJmol": 17.582}, "diurnalAmbient": {"autumn": {"amp": 0.0, "hpk": 15.5}}, "park": {"tau_h": 1e-7, "offset_C": 0.5}}


def sidecar(n=12, per_day=2, a0=None, y0=None, odo_step=0.0, soc_jump=0.0):
    a0 = np.linspace(-2.0, 3.0, n) if a0 is None else a0
    rows, t = [], pd.Timestamp("2026-12-01 08:00")
    for k in range(n):
        d = t + pd.Timedelta(days=k // per_day, hours=(k % per_day) * 6)
        u0 = d.value / 1e9
        y = (a0[k] + 5.0) if y0 is None else y0[k]
        r = {"key": "20261201%06d" % k, "day": d.strftime("%Y-%m-%d"), "utc0": u0, "utc1": u0 + 1800.0, "dur_s": 1800.0, "local0": d.isoformat(), "odo_start": 100.0 + 20 * k + odo_step * k, "odo_end": 100.0 + 20 * k + 10,
             "soc_first": 60.0 + soc_jump * (k % 2), "soc_last": 60.0, "A0": a0[k], "A1": a0[k] + 0.0, "icov": 1.0, "Tcool_s": 20.0, "Tcool_e": 20.0}
        for i in (1, 2, 3, 4):
            r["T%d_s" % i] = y
            r["T%d_e" % i] = 10.0
        for j in range(W1.K_SLICES):
            r["i2_%d" % j] = 0.0
        rows.append(r)
    return pd.DataFrame(rows)


sc = sidecar()
out = W1.extract_p1(sc, PAR, nb=200)
# closed form: simulated start of k+1 = A0(k+1) + 0.5 (park time constant ~ 0, no diurnal term); logged = A0 + 5.0 -> error = -4.5 for every scored drive; anchor not scored
ch, ra = W1.free_run(sc.sort_values("utc0").reset_index(drop=True), W1.build_pair_table(sc, PAR), PAR)
assert ch["anchored"].sum() == 1 and ra["first"] == 1 and ch["scored"].sum() == 11
assert np.allclose(ch.loc[ch["scored"], "err"], -4.5, atol=1e-6), ch["err"].values
a = out["cells"]["A_freeRun"]
assert a["status"] == "outside" and abs(a["bias"] + 4.5) < 1e-6 and abs(a["mae"] - 4.5) < 1e-6 and a["n"] == 11
# propagation is never reset: a planted heating-free chain whose simulated start error is carried (state = park of the SIMULATED end): with a real drive time constant the end temperature depends on the carried start
PAR2 = {**PAR, "driveHeating": {"c0_C": 20.0, "c1": 0.5, "tau_d_h": 1e6, "alpha_C_per_A2h": 0.0}, "park": {"tau_h": 1e6, "offset_C": 0.0}}   # nothing relaxes: the state is the anchor value for ever
ch2, _ = W1.free_run(sc.sort_values("utc0").reset_index(drop=True), W1.build_pair_table(sc, PAR2), PAR2)
assert np.allclose(ch2["sim"], ch2["sim"].iloc[0], atol=1e-3), ch2["sim"].values
# a perfect model: logged start = A0 + 0.5 -> zero error -> within
sc3 = sidecar(y0=np.linspace(-2.0, 3.0, 12) + 0.5)
o3 = W1.extract_p1(sc3, PAR, nb=200)
assert abs(o3["cells"]["A_freeRun"]["bias"]) < 1e-6 and o3["cells"]["A_freeRun"]["status"] == "within"
# flagged join: soc jump >= 3 points flags every pair; the chain still propagates (primary), the segmented sensitivity re-anchors at every join (errors 0 by construction of the logged start)
sc4 = sidecar(soc_jump=5.0)
ch4, ra4 = W1.free_run(sc4.sort_values("utc0").reset_index(drop=True), W1.build_pair_table(sc4, PAR), PAR)
assert ra4["segmented"] == 0 and ch4["scored"].sum() == 11
ch4s, ra4s = W1.free_run(sc4.sort_values("utc0").reset_index(drop=True), W1.build_pair_table(sc4, PAR), PAR, segmented=True)
assert ra4s["segmented"] == 11 and ch4s["scored"].sum() == 0
# support rule: 8 drives on 4 days -> not evaluable, P1 not evaluable
o5 = W1.extract_p1(sidecar(n=8), PAR, nb=100)
assert o5["cells"]["A_freeRun"]["status"] == "not evaluable" and o5["status"] == "not evaluable"
# reading rule
assert W1.reading(0.1, [-0.2, 0.3], 1.0) == "within" and W1.reading(0.9, [0.2, 1.4], 1.0) == "inconclusive" and W1.reading(1.2, [0.9, 1.5], 1.0) == "outside"
# vendored modules are not live modules and do not shadow them
V = W1.vendored()
assert os.path.dirname(os.path.abspath(V["park_model"].__file__)) == os.path.abspath(W1.VT)
assert "park_model" not in sys.modules or os.path.dirname(os.path.abspath(sys.modules["park_model"].__file__)) != os.path.abspath(W1.VT)

# M732 Director rulings (required tests)
base = sidecar()
# D4: a drive below 80 % current coverage is propagated but not scored
sc6 = sidecar(); sc6.loc[4, "icov"] = 0.5
ch6, _ = W1.free_run(sc6.sort_values("utc0").reset_index(drop=True), W1.build_pair_table(sc6, PAR), PAR)
assert (not ch6.loc[4, "scored"]) and ch6.loc[5, "scored"] and ch6["scored"].sum() == 10
o6 = W1.extract_p1(sc6, PAR, nb=100)
assert o6["notScored"]["lowCurrentCoverage"] == 1 and o6["notScored"]["scoredWithLowCoveragePredecessor"] == 1
# re-anchor reasons: missing ambient, overlap, error row (missingDrive), odometer step is propagated through (flag_odo counted, no re-anchor)
sc7 = sidecar(); sc7.loc[3, ["A0", "A1"]] = np.nan
ch7, ra7 = W1.free_run(sc7.sort_values("utc0").reset_index(drop=True), W1.build_pair_table(sc7, PAR), PAR)
assert ra7["missingAmbient"] >= 1 and ch7.loc[3, "anchored"] and not ch7.loc[3, "scored"]
sc8 = sidecar(); sc8.loc[5, "utc0"] = sc8.loc[4, "utc1"] - 600.0                              # overlap: starts before the previous drive ended
ch8, ra8 = W1.free_run(sc8.sort_values("utc0").reset_index(drop=True), W1.build_pair_table(sc8, PAR), PAR)
assert ra8["overlapOrDup"] == 1 and ch8.loc[5, "anchored"]
sc9 = sidecar(); sc9 = pd.concat([sc9, pd.DataFrame([{"key": "20261201000004z", "error": "boom"}])], ignore_index=True)
o9 = W1.extract_p1(sc9, PAR, nb=100)
assert o9["droppedSidecarRows"] == 1 and o9["reanchors"]["missingDrive"] == 1
sc10 = sidecar(odo_step=5.0)
ch10, ra10 = W1.free_run(sc10.sort_values("utc0").reset_index(drop=True), W1.build_pair_table(sc10, PAR), PAR)
assert ra10["propagatedThroughOdoStepJoins"] == 11 and ch10["scored"].sum() == 11 and ra10["first"] == 1
# amplitude sensitivity changes December values (no winter reduction): planted non-zero autumn amplitude
PAR3 = {**PAR, "diurnalAmbient": {"autumn": {"amp": 4.0, "hpk": 15.5}}, "park": {"tau_h": 5.0, "offset_C": 0.5}}
cA, _ = W1.free_run(sc.sort_values("utc0").reset_index(drop=True), W1.build_pair_table(sc, PAR3, winter_reduction=True), PAR3)
cB, _ = W1.free_run(sc.sort_values("utc0").reset_index(drop=True), W1.build_pair_table(sc, PAR3, winter_reduction=False), PAR3)
assert np.nanmax(np.abs(cA["sim"].values - cB["sim"].values)) > 0.01
# alignment guard
try:
    D_ = W1.build_pair_table(sc, PAR)
    W1.free_run(sc.iloc[::-1].reset_index(drop=True), D_, PAR)
    raise SystemExit("alignment guard did not fire")
except AssertionError:
    pass
# selection on the predicted value and the ambient snapshot hash are present; disclosures carry the cold wording
assert "B2_10C_selectedOnPredicted" in out["sensitivities"] and len(out["ambientSnapshotSha256"]) == 64 and any("NOT SUPPORTED" in d for d in out["disclosure"])
print("OK test_winter_p1 (rulings)")

# Director second check: NaN coverage counted, dropped-row pairs excluded from Part B, block floor
sc11 = sidecar(); sc11.loc[6, "icov"] = np.nan
o11 = W1.extract_p1(sc11, PAR, nb=100)
assert o11["notScored"]["noCurrentCoverageValue"] == 1
sc12 = pd.concat([sidecar(), pd.DataFrame([{"key": "20261201000004z", "error": "boom"}])], ignore_index=True)
D12 = W1.build_pair_table(W1._prepare(sc12)[0], PAR)
assert D12["after_missing"].sum() == 1 and not D12.loc[D12["after_missing"], "use"].any()
assert o11["cells"]["A_freeRun"]["blockReading"]["status"].startswith("not evaluable")          # 6 days -> 1 block of 7 days
print("OK test_winter_p1 (second check)")
print("OK test_winter_p1")
