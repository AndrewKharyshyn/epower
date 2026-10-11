"""M404 (analyses/M403_spec.md v4 Rev 1b): known-answer tests for the capacity-basis tests (b) offset vs I2R, (c) level dependence, (h) key-on reset, the zero-current check, the shadow eligibility
and the exposure table. Each can FAIL: a model without the effect must not be accepted, a collinear design must be flagged, a level-dependent scale must be detected."""
import os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import capacity_basis as CB
import capacity_tests as CT

CB.N_BOOT = 300
rng = np.random.default_rng(7)


def drive_table(n=400, days=100, K=1.8, c=0.0, R=0.12, noise=0.02, collinear=False, seed=3):
    r = np.random.default_rng(seed)
    z = r.uniform(-0.3, 0.3, n)
    h = r.uniform(0.15, 1.0, n)
    Vp = r.uniform(340, 365, n)
    i2h = (h * r.uniform(150, 2500, n)) if not collinear else h * 1000.0           # A^2 h; collinear: proportional to the offset regressor
    temp = r.uniform(5, 35, n)
    off = Vp * h / 1000.0
    loss = i2h / 1000.0
    y = K * z + c * off - R * loss + r.normal(0, noise, n)
    dates = [str((pd.Timestamp("2026-06-01") + pd.Timedelta(days=int(i % days))).date()) for i in range(n)]
    s0 = 70.0
    dm = pd.DataFrame({"file": ["f%03d.csv" % i for i in range(n)], "date": dates, "ens_outlier_v2": "False", "net_draw_kwh": y, "soc_start": s0, "soc_end": s0 - 100 * z,
                       "V_pack_median": Vp, "integr_time_h": h})
    extras = {f: {"i2h": float(v), "temp": float(t)} for f, v, t in zip(dm["file"], i2h, temp)}
    return dm, extras


# ---- (b) offset vs I2R
dm, ex = drive_table()
b = CT.offset_test(dm, ex, nb=300)
assert b["evaluable"] and b["nFolds"] >= 5
assert abs(b["full"]["R_ohm"]["est"] - 0.12) < 0.02 and b["full"]["R_ohm"]["ci95"][0] <= 0.12 <= b["full"]["R_ohm"]["ci95"][1], b["full"]["R_ohm"]
assert abs(b["full"]["scaleKwhPer100"]["est"] - 1.8) < 0.05
assert b["heldOutRmsKwh"]["i2r_est"] < b["heldOutRmsKwh"]["offset_est"] and b["heldOutRmsKwh"]["offset_est"] < b["heldOutRmsKwh"]["offset_fix"]      # the true scale (1.8) beats the fixed 2.1
assert b["pairedAtEstimatedScale"]["lowerBoundAbovezero"] and b["acceptance"]["acceptI2R"] and "accepted" in b["decision"], b["acceptance"]
assert b["chronological"]["earlyToLate"]["rmsKwh"]["i2r_est"] < b["chronological"]["earlyToLate"]["rmsKwh"]["offset_est"]
# folds never share a day
fd = CT._folds(sorted(set(dm["date"])), CT.NFOLD, 42)
assert set(fd.values()) == set(range(CT.NFOLD)) and len(fd) == dm["date"].nunique()
# no I2R in the truth (R = 0): the I2R model is NOT accepted (the test can fail), dual report only
d0, e0 = drive_table(R=0.0)
b0 = CT.offset_test(d0, e0, nb=300)
assert not b0["acceptance"]["i_lowerHeldOutErrorAtSameScale"] and not b0["acceptance"]["acceptI2R"] and "dual report only" in b0["decision"], b0["acceptance"]
# an offset that the I2R model cannot absorb (true offset 0.4 A on a pure-offset truth, R = 0): offset term not equivalent to zero
dc, ec = drive_table(R=0.0, c=0.4)
bc = CT.offset_test(dc, ec, nb=300)
assert not bc["acceptance"]["ii_offsetEquivalentToZero_pm0.10A_ci90"] and not bc["acceptance"]["acceptI2R"]
# collinear design (I2 term proportional to the offset regressor): flagged as not separately identifiable
dl, el = drive_table(collinear=True)
bl = CT.offset_test(dl, el, nb=300)
assert bl["full"]["vif"]["i2Term"] > CT.VIF_I2R_MAX and not bl["acceptance"]["iv_identifiable_vif_le_10"] and not bl["acceptance"]["acceptI2R"]

# ---- shadow eligibility (real master): at the legacy scale it reproduces the master exactly; a much smaller scale flips drives (the test can fail)
dmr = pd.read_csv("drive_master.csv", low_memory=False)
sh = CT.shadow_eligibility(dmr, 2.1)
assert sh["reproducesMasterAtLegacyScale"] and sh["variants"]["thresholdUnchanged_0.35"]["flips"] == 0 and sh["nExcludedMaster"] == sh["variants"]["thresholdUnchanged_0.35"]["nExcluded"]
sh1 = CT.shadow_eligibility(dmr, 1.0)
assert sh1["flipsAny"] and sh1["variants"]["thresholdUnchanged_0.35"]["flips"] > 0, sh1["variants"]
assert set(sh["variants"]) == {"thresholdUnchanged_0.35", "thresholdScaleOver6"} and abs(sh["variants"]["thresholdScaleOver6"]["threshold"] - 0.35) < 1e-3

# ---- exposure (real files): identities
side = pd.read_csv("ah_throughput.csv", keep_default_na=False, na_values=[""])
ex_ = CT.exposure(dmr, side, 4.8856, 1.795)
pr = ex_["primaryRaw"]
assert abs(pr["throughputKwh"] - (pr["dischargeKwh"] + pr["chargeKwh"])) < 1e-9 and abs(pr["throughputAh"] - (pr["dischargeAh"] + pr["chargeAh"])) < 1e-9
e21, e18 = ex_["energyReferences"]["legacy_2.1kWh"], ex_["energyReferences"]["apparentSoCScale"]
assert abs(e21["grossTurnoverGTC"] - 2 * e21["bidirectionalFCE"]) < 1e-9 and abs(e18["bidirectionalFCE"] / e21["bidirectionalFCE"] - 2.1 / 1.795) < 1e-9      # inverse in the reference
assert abs(ex_["windowFractionBand"]["fMin"] - 1.795 / 2.1) < 1e-9                                                                                                    # f_min = E_est / 2.1
assert ex_["chargeReferences"]["rated_5.0Ah"]["chargeThroughputEFC"] > ex_["chargeReferences"]["windowFractionBand_fMinEnd"]["chargeThroughputEFC"] and abs(ex_["windowFractionBand"]["fMinEndReferenceAh"] - 4.8856 / (1.795 / 2.1)) < 1e-9
okm = dmr[dmr["ens_outlier_v2"].map(lambda v: str(v).strip().lower()) == "false"]
assert abs(pr["throughputKwh"] - okm["gross_throughput_kwh"].sum()) < 0.05 and ex_["population"]["nDrives"] == okm["gross_throughput_kwh"].notna().sum()      # independent sum over the same population

# ---- (h) key-on reset
def keyon_tables(slope, n=160, seed=5):
    r = np.random.default_rng(seed)
    start = pd.Timestamp("2026-06-01 08:00:00")
    rows, side_rows, extras = [], [], {}
    t = start
    soc = 60.0
    for i in range(n):
        q = r.uniform(-1.0, 1.0)                                           # charge-positive net Ah of drive i
        dur = r.uniform(600, 1500)
        soc_end = soc + 100 * q / 5.0
        f = "k%03d.csv" % i
        rows.append({"file": f, "date": str(t.date()), "time_start": t.strftime("%H:%M:%S.000"), "duration_s": dur, "ens_outlier_v2": "False", "soc_start": soc, "soc_end": soc_end})
        side_rows.append({"file": f, "ah_net": -q})
        extras[f] = {"last_i60": float(np.sign(q) * 5.0)}
        rest = r.choice([300.0, 1800.0, 7200.0, 30000.0])
        t = t + pd.Timedelta(seconds=dur + rest)
        soc = soc_end + slope * q + r.normal(0, 0.1)                        # the key-on jump is slope x the previous drive's net charge
    return pd.DataFrame(rows), pd.DataFrame(side_rows), extras


mk, sk, ek = keyon_tables(-0.4)
h = CT.keyon_test(mk, sk, ek, n_boot=300)
a_ = h["all"]["slopeSoCPointsPerAh"]
assert h["evaluable"] and abs(a_["est"] + 0.4) < 0.05 and a_["ci95"][0] <= -0.4 <= a_["ci95"][1], a_
assert set(h["byRestTime"]) == {"<10min", "10-60min", "1-6h", ">6h"} and h["byLastCurrentDirection"]["lastCurrentCharging"] and h["byLastCurrentDirection"]["lastCurrentDischarging"]
mk0, sk0, ek0 = keyon_tables(0.0)
h0 = CT.keyon_test(mk0, sk0, ek0, n_boot=300)
assert abs(h0["all"]["slopeSoCPointsPerAh"]["est"]) < 0.05 and h0["all"]["slopeSoCPointsPerAh"]["ci95"][0] <= 0 <= h0["all"]["slopeSoCPointsPerAh"]["ci95"][1]
assert CT.keyon_test(mk.iloc[:10], sk, ek)["evaluable"] is False

# ---- zero-current check: 'no samples' is not zero; a constant 0.2 A lead is recovered
base = [("a%d" % i, {"drive": {"lead": [0.2, 0.25, 0.15, 0.2]}}) for i in range(30)]
W = CB.boot_weights(10, 200)
z = CT.zero_current(base, [i % 10 for i in range(30)], 10, W)
assert z["evaluable"] and abs(z["meanOfDriveMediansA"]["est"] - 0.2) < 1e-9 and z["nDrivesWithSamples"] == 30
assert "NOT a sensor-zero reference" in z["interpretation"]
zz = CT.zero_current([("a%d" % i, {"drive": {"lead": [0.1, -0.1, 0.0, 0.05, -0.05]}}) for i in range(30)], [i % 10 for i in range(30)], 10, W)
assert "consistent with zero" in zz["interpretation"]
zn = CT.zero_current([("a", {"drive": {"lead": None}})], [0], 1, W)
assert zn["evaluable"] is False and zn["outcome"] == "no samples"

# ---- (c) level dependence on synthetic drives: constant scale is not flagged; a SoC-dependent scale is detected (the test can fail)
CI_, CV_, CS_ = "[BMS] HV Battery Current (A)", "[BMS] HV Battery voltage (V)", "[BMS] HV State of charge (%)"


def level_drive(seed, slope, n=1500, offset=0.0):
    """Synthetic drive whose apparent scale depends on the SoC: Ah per 100 points = 5.0 + slope * (SoC - 60) / 10; 0.5-point quantised SoC, ~1.28 s cadence."""
    r = np.random.default_rng(seed)
    t = np.cumsum(r.uniform(1.1, 1.46, n)) - 1.1
    ph, per, amp = r.uniform(0, 6.28), r.uniform(300, 500), r.uniform(25, 40)
    I = amp * np.sin(2 * np.pi * t / per + ph) + r.normal(0, 2.0, n)
    soc = np.empty(n)
    soc[0] = r.uniform(52, 68)
    for k in range(1, n):
        dq = 0.5 * (I[k] + I[k - 1]) * (t[k] - t[k - 1]) / 3600.0
        soc[k] = soc[k - 1] + 100.0 * dq / (5.0 + slope * (soc[k - 1] - 60.0) / 10.0)
    secs = 36000 + t
    tm = ["%02d:%02d:%06.3f" % (int(x // 3600), int((x // 60) % 60), x % 60) for x in secs]
    return pd.DataFrame({"time": tm, CI_: I + offset, CV_: 350.0, CS_: np.round(soc * 2) / 2}).to_csv(index=False).encode("utf-8")


class TS:
    @staticmethod
    def build_level(n_drives=40, days=20, slope=0.0):
        rows, store = [], {}
        for i in range(n_drives):
            f = "l%02d.csv" % i
            store[f] = level_drive(500 + i, slope)
            rows.append({"file": f, "date": str((pd.Timestamp("2026-06-01") + pd.Timedelta(days=i % days)).date()), "ens_outlier_v2": "False"})
        return pd.DataFrame(rows), store


for sloped, expect_present in ((0.0, False), (0.6, True)):
    mm, store = TS.build_level(n_drives=40, days=20, slope=sloped)
    recs = {f: CB.extract_drive(store[f]) for f in mm["file"]}
    base_ = [(f, recs[f]) for f in mm["file"] if recs[f] is not None]
    days = sorted({mm.set_index("file").loc[f, "date"] for f, _ in base_})
    dix = {d: i for i, d in enumerate(days)}
    rr = [(dix[mm.set_index("file").loc[f, "date"]], r) for f, r in base_]
    lv = CT.level_test(rr, len(days), CB.boot_weights(len(days), 300))
    if expect_present:
        assert lv["adjustedSlope"]["est"] > 0.3 and "level-associated variation" in lv["outcome"] and "attribution unresolved" in lv["outcome"], lv["adjustedSlope"]
    else:
        assert abs(lv["adjustedSlope"]["est"]) < 0.1 and lv["outcome"].startswith("equivalent"), (lv["adjustedSlope"], lv["outcome"])
print("OK test_capacity_tests")
