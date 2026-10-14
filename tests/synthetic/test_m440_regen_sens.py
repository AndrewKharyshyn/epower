"""M440 known-answer tests (spec analyses/M440_spec.md Rev 2, section 4; criteria declared there before any variant result): tools/m440_regen_sens.py + tools/m440_analyse.py.
(i) hand-calculated KE and charge energy of a synthetic drive; (ii) a missing-RPM second is engine-off in the legacy and flagged for V1; (iii) the native-sample age (7 s old: excluded by V2(5), kept by V2(10));
(iv) a 3 s gap between kept rows is a step in the legacy and flagged for V3; (v) a step 52 -> 48 km/h is in the 45 bin by its end speed and the 55 bin by its start speed (V4); (vi) a missing probe flags V5 and the
legacy mean skips it; (vii) the offset sign (+10 A -> 9.6112 A, +0.2 A -> no charge); (viii) pooled recovery is a ratio of sums and the identity Delta = w (eff_retained - eff_removed) holds."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import compute_summary_arrays as C
import m440_regen_sens as X
import m440_analyse as AN

SP, RPM, I_, V_ = "[VCM] Vehicle Speed (km/h)", "Оберти двигуна (rpm)", "[BMS] HV Battery Current (A)", "[BMS] HV Battery voltage (V)"
TC = ["[BMS] HV Battery Temperature Sensor %d (℃)" % k for k in (1, 2, 3, 4)]
T0 = pd.Timestamp("2026-03-01 10:00:00")


def frame(sec, speed, rpm, cur, volt=360.0, temps=(30.0, 30.0, 30.0, 30.0)):
    n = len(sec)
    d = {"time": T0 + pd.to_timedelta(np.asarray(sec, float), unit="s"), SP: np.asarray(speed, float), RPM: np.asarray(rpm, float), I_: np.asarray(cur, float), V_: np.full(n, volt)}
    for c, t in zip(TC, temps):
        d[c] = np.full(n, np.nan if t is None else t)
    return pd.DataFrame(d)


MASS = C.MASS_URBAN_MIXED_KG
ke_of = lambda v0, v1: 0.5 * MASS * ((v0 / 3.6) ** 2 - (v1 / 3.6) ** 2) / 3.6e6

# ---- (i) hand-calculated drive: 1 Hz, engine off, speed 40 -> 30 -> 20 -> 10 -> 0 km/h, charge current 20 A / 0 / 10 A / 5 A at 360 V
sec = np.arange(0, 12)
speed = [50, 50, 40, 30, 20, 10, 0, 0, 0, 0, 0, 0]
cur = [0, 0, 20, 0, 10, 5, 0, 0, 0, 0, 0, 0]
st = X.extract_drive(frame(sec, speed, [0] * 12, cur), "urban", "t1.csv", "2026-03-01", C=C, i_off=-0.3888)
assert len(st) == 4 and list(st["spEnd"]) == [40, 30, 20, 10] and list(st["spStart"]) == [50, 40, 30, 20]
want_ke = [ke_of(50, 40), ke_of(40, 30), ke_of(30, 20), ke_of(20, 10)]
want_cap = [20 * 360 / 1000 / 3600, 0.0, 10 * 360 / 1000 / 3600, 5 * 360 / 1000 / 3600]
# the last decel step 10 -> 0 (speed 0 is not > 0) is excluded; the first row has no predecessor
assert np.allclose(st["ke"], want_ke, rtol=1e-12) and np.allclose(st["cap"], want_cap, rtol=1e-12, atol=1e-15)
tt, sm = X.bins_table(st)
assert abs(sm["cap"].sum() / sm["ke"].sum() * 100 - 100 * sum(want_cap) / sum(want_ke)) < 1e-9          # pooled recovery is a ratio of sums, not a mean of ratios
assert all(st["gap"] == 1) and (st["nprobe"] == 4).all() and (~st["rpmNan"]).all()

# ---- (ii) missing RPM: engine-off in the legacy (fillna(0)) and flagged
rpm = [0, 0, 0, np.nan, 0, 0, 0, 0, 0, 0, 0, 0]
df = frame(sec, speed, rpm, cur)
df.loc[3:5, RPM] = np.nan                       # native RPM stops at second 3; the 15-row forward fill still carries 0.0 over seconds 3-5 -> the grid value is the filled one
st = X.extract_drive(df, "urban", "t2.csv", "2026-03-01", C=C)
assert len(st) == 4 and (st["ageMax"].values[1:] > 0).any()
df2 = frame(sec, speed, [np.nan] * 12, cur)
st2 = X.extract_drive(df2, "urban", "t2b.csv", "2026-03-01", C=C)
assert len(st2) == 4 and st2["rpmNan"].all()                                  # no RPM at all: legacy counts it as engine-off, the flag marks every step (V1 removes them)

# ---- (iii) age of the native sample: current logged every 8 s, speed and RPM every second
cur8 = [np.nan] * 12; cur8[0] = 20.0; cur8[8] = 20.0
st = X.extract_drive(frame(sec, speed, [0] * 12, cur8), "urban", "t3.csv", "2026-03-01", C=C)
ages = dict(zip(st["spEnd"], st["ageMax"]))
# step at grid second 4 (speed 20): the latest native current sample is at second 0, reference point 5 -> age 5 ; at second 5 (speed 10): 6
assert ages[20] == 5.0 and ages[10] == 6.0, ages
assert (st["ageMax"] <= 5).sum() == 3 and (st["ageMax"] <= 4).sum() == 2        # V2(5) keeps the steps of age <= 5, a stricter limit fewer
# a 7 s old current sample: excluded by V2(5), kept by V2(10)
cur12 = [np.nan] * 12; cur12[0] = 20.0
st = X.extract_drive(frame(sec, speed, [0] * 12, cur12), "urban", "t3b.csv", "2026-03-01", C=C)
a7 = st.loc[st["spEnd"] == 10, "ageMax"].iloc[0]
assert a7 == 6.0 and not (a7 <= 5) and (a7 <= 10)
# a channel with no native sample at all is unbounded
st = X.extract_drive(frame(sec, speed, [0] * 12, [np.nan] * 12), "urban", "t3c.csv", "2026-03-01", C=C)
assert len(st) == 0                                                          # no current at all: no kept rows (legacy drops them)

# ---- (iv) a 3 s gap between kept rows (more than the 15 s forward fill allows) is a step in the legacy and flagged
sec4 = np.r_[np.arange(0, 6), np.arange(30, 36)]
speed4 = [60, 60, 60, 60, 60, 60, 50, 50, 50, 50, 40, 30]
st = X.extract_drive(frame(sec4, speed4, [0] * 12, [10] * 12), "urban", "t4.csv", "2026-03-01", C=C)
big = st[st["gap"] > 1]
assert len(big) >= 1 and (st["gap"] >= 1).all()

# ---- (v) start / end bin
sec5 = np.arange(0, 6)
st = X.extract_drive(frame(sec5, [60, 60, 52, 48, 48, 48], [0] * 6, [10] * 6), "urban", "t5.csv", "2026-03-01", C=C)
assert len(st) == 2                                                          # 60 -> 52 and 52 -> 48
r = st[st["spEnd"] == 48].iloc[0]
assert X.mid_bin(np.array([r["spEnd"]]))[0] == 45 and X.mid_bin(np.array([r["spStart"]]))[0] == 55

# ---- (vi) one missing probe: nprobe = 3, the legacy mean skips it
st = X.extract_drive(frame(sec, speed, [0] * 12, cur, temps=(30.0, 30.0, 30.0, None)), "urban", "t6.csv", "2026-03-01", C=C)
assert (st["nprobe"] == 3).all() and (st["tbin"] == [k for k, b in enumerate(C.REGEN_TEMP_BINS) if b[0] <= 30.0 < b[1]][0]).all()

# ---- (vii) offset sign: +10 A -> 9.6112 A; +0.2 A -> discharge (no charge energy)
st = X.extract_drive(frame(np.arange(0, 4), [40, 40, 30, 20], [0] * 4, [10, 10, 10, 0.2]), "urban", "t7.csv", "2026-03-01", C=C, i_off=-0.3888)
assert abs(st["capOff"].iloc[0] - (10 - 0.3888) * 360 / 1000 / 3600) < 1e-12 and abs(st["cap"].iloc[0] - 10 * 360 / 1000 / 3600) < 1e-12
assert st["cap"].iloc[1] > 0 and st["capOff"].iloc[1] == 0.0

# ---- (viii) bootstrap layer: identity Delta = w (eff_retained - eff_removed) and the ratio of sums on unequal-KE steps
rng = np.random.default_rng(3)
n = 600
steps = pd.DataFrame({"file": rng.choice(["a", "b", "c", "d", "e", "f"], n), "day": rng.choice(["2026-03-0%d" % k for k in range(1, 9)], n), "cap": rng.random(n) * 0.01, "capOff": rng.random(n) * 0.01,
                      "ke": rng.random(n) * 0.05 + 0.001, "keUm": 0.0, "spEnd": rng.uniform(1, 120, n), "spStart": rng.uniform(1, 120, n), "tbin": rng.integers(2, 6, n),
                      "nprobe": np.where(rng.random(n) < 0.9, 4, 3).astype(np.int8), "rpmNan": rng.random(n) < 0.1, "ageMax": rng.choice([1.0, 3.0, 8.0, 20.0, np.inf], n), "gap": rng.choice([1, 1, 1, 2, 5], n).astype(np.int32),
                      "cadence": rng.choice(["fast", "slow"], n)})
A_ = {"regenCaptureMeasured": [[m, 1.0, 100] for m in (5, 15, 25, 35, 45, 55, 65, 75, 85, 95, 105, 115)],
      "regenCaptureMeasuredMassUncertainty": [[m, 0.9, 1.1] for m in (5, 15, 25, 35, 45, 55, 65, 75, 85, 95, 105, 115)],
      "regenByTempMeasured": [{"label": l, "effRangeMassUncertainty": [0.9, 1.1]} for l in ("b0", "b1", "b2", "b3", "b4", "b5", "b6", "b7")]}
res = AN.analyse(steps, A_, "synthetic", ["b0", "b1", "b2", "b3", "b4", "b5", "b6", "b7"])
for vname in ("V1_rpmKnown", "V2_age5", "V3_contiguous", "V5_fullProbe"):
    for kind, tab in res["variants"][vname].items():
        if kind in ("temp", "speed"):
            for b, row in tab.items():
                if "identityResidual" in row:
                    assert row["identityResidual"] < 1e-6, (vname, kind, b, row["identityResidual"])
# pooled ratio of sums on this fixture differs from the mean of the step ratios
m = steps["spEnd"].values < 50
assert abs(steps["cap"][m].sum() / steps["ke"][m].sum() - (steps["cap"][m] / steps["ke"][m]).mean()) > 1e-4
# V4 changes only the speed view; V5 only the temperature view; V6 changes no retained count
assert "temp" not in res["variants"]["V4_startSpeedBin"] and "speed" not in res["variants"]["V5_fullProbe"]
assert all(row["n"] == row["n0"] for row in res["variants"]["V6_offset"]["temp"].values())
# fixed seed reproduces
res2 = AN.analyse(steps, A_, "synthetic", ["b0", "b1", "b2", "b3", "b4", "b5", "b6", "b7"])
assert res == res2
# decision labels (R1-R5): a bin with fewer than 5 contributing days is notEvaluable; V4 and V6 are never notComparable; every label is one of the four
labels = {row["decision"] for vname, v in res["variants"].items() for kind in ("temp", "speed") for row in (v.get(kind) or {}).values()}
assert labels <= {"material", "notMaterial", "notComparable", "notEvaluable"}
assert all(row["decision"] != "notComparable" for vn in ("V4_startSpeedBin", "V6_offset") for kind in ("temp", "speed") for row in (res["variants"][vn].get(kind) or {}).values())
few = steps[steps["day"].isin(["2026-03-01", "2026-03-02", "2026-03-03"])].reset_index(drop=True)
rf = AN.analyse(few, A_, "few", ["b0", "b1", "b2", "b3", "b4", "b5", "b6", "b7"])
assert all(row["decision"] == "notEvaluable" for kind in ("temp", "speed") for row in rf["variants"]["V1_rpmKnown"][kind].values())          # 3 days < 5
assert "materialDefect" in res["variants"]["V1_rpmKnown"] and isinstance(res["variants"]["V1_rpmKnown"]["materialBins"], list)
print("OK test_m440_regen_sens")
