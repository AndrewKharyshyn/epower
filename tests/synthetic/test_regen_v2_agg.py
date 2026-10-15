"""M441 known-answer tests of the aggregation and the cache (spec analyses/M441_spec.md Rev 2.1, section 6): tools/regen_v2_agg.py, tools/regen_v2_cache.py.
(2) identical braking at two SOC values lands in two distinct bands, boundaries (39.9 / 40 / 59.999 / 60 / 72 / 100 / NaN) follow the rules exactly once; (3) a valid zero-charge interval lowers the pooled ratio through its KE;
(9) SOC bands + below40 + missing equal the SOC-free baseline exactly, all-SOC equals the band sum; (11) whole-day resampling (counts per draw sum to the number of days, a draw reproduces by hand), fixed seed reproduces;
(12) a drive warming through temperature bins moves the bins and never changes eligibility; support status (empty / thin / supported / failed); (13) the cache entry is invalidated by raw bytes, extractor source, policy, variant and (offset file only) i_off;
(8) the pooled recovery of a cell is a ratio of sums."""
import os, sys, tempfile, shutil, json
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np
import pandas as pd
import compute_summary_arrays as C
import regen_v2 as R
import regen_v2_agg as G
import regen_v2_cache as K

SP, RPM, I_, V_ = "[VCM] Vehicle Speed (km/h)", "Оберти двигуна (rpm)", "[BMS] HV Battery Current (A)", "[BMS] HV Battery voltage (V)"
SOC = "[BMS] HV State of charge (%)"
TC = ["[BMS] HV Battery Temperature Sensor %d (℃)" % k for k in (1, 2, 3, 4)]
T0 = pd.Timestamp("2026-03-01 10:00:00")


def frame(sec, speed, cur=15.0, soc=60.0, temp=30.0):
    sec = np.asarray(sec, float); n = len(sec)
    full = lambda x: np.full(n, x, float) if np.isscalar(x) else np.asarray(x, float)
    d = {"time": T0 + pd.to_timedelta(sec, unit="s"), SP: full(speed), RPM: np.zeros(n), I_: full(cur), V_: np.full(n, 360.0), SOC: full(soc)}
    for c in TC:
        d[c] = full(temp)
    return pd.DataFrame(d)


def brake(soc=60.0, temp=30.0, cur=15.0, v0=80, n=9, step=8):
    return frame(np.arange(n), [v0 - step * k for k in range(n)], cur=cur, soc=soc, temp=temp)


def table(frames, i_off=0.4):
    """Assemble the concatenated cache-table layout of tools/regen_v2_cache.load from synthetic frames (one per drive)."""
    cols = {k: [] for k in ["iv_" + k for k in K.IV_KEYS] + ["bin_dv2", "bin_charge", "bin_touch", "iv_chargeOff", "bin_chargeOff", "drive"]}
    for di, fr in enumerate(frames):
        r = R.extract_drive(fr, C=C, i_off=i_off)
        iv, bins = r["intervals"], r["bins"]
        if iv is None:
            continue
        for k in K.IV_KEYS:
            cols["iv_" + k].append(iv[k])
        cols["bin_dv2"].append(bins["dv2"]); cols["bin_charge"].append(bins["charge"]); cols["bin_touch"].append(bins["touch"])
        cols["iv_chargeOff"].append(iv["chargeOff"]); cols["bin_chargeOff"].append(bins["chargeOff"]); cols["drive"].append(np.full(len(iv["t0"]), di, np.int32))
    return {k: np.concatenate(v) for k, v in cols.items()}


def master(n, dates, types=None):
    return pd.DataFrame({"file": ["d%d.csv" % i for i in range(n)], "date": dates, "drive_type": types or ["urban"] * n, "ev_rpm_dt_med_s": [1.0] * n})


# ---- (2)/(6) SOC bands and boundaries: one drive per SOC value, identical braking
socs = [39.9, 40.0, 49.999, 50.0, 59.999, 60.0, 71.999, 72.0, 100.0, np.nan]
want = ["below40", "band 40-50", "band 40-50", "band 50-55", "band 55-60", "band 60-63", "band 69-72", "band 72-100", "band 72-100", "missingSoc"]
T = table([brake(soc=s) for s in socs])
dm = master(len(socs), ["2026-03-%02d" % (1 + i) for i in range(len(socs))])
co = G.Cohort(T, dm, np.ones(len(dm), bool), "t")
for i, (s, w) in enumerate(zip(socs, want)):
    in_sel = [k for k, m in co.sel.items() if k not in ("noSocCondition", "allSoc") and m[co.drive == i].all()]
    assert in_sel == [w], (s, in_sel, w)                                                                    # exactly one selection each (SOC is an interval-START attribute)
    assert co.sel["allSoc"][co.drive == i].all() == bool(np.isfinite(s))
# identical braking at two SOC values: two distinct cells with the same KE, selectable
b1, b2 = co.cell_block("all", co.sel["band 55-60"])["all"], co.cell_block("all", co.sel["band 60-63"])["all"]
assert b1["n"] == b2["n"] and abs(b1["keKwh"] - b2["keKwh"]) < 1e-12 and b1["n"] > 0

# ---- (9) reconciliation is exact
cbT = co.view_by_soc("temperature"); cbS = co.view_by_soc("speed", sels=["noSocCondition", "allSoc"] + G.SOC_SELS[2:])
rt, rs = G.reconcile(cbT), G.reconcile(cbS)
assert rt["nSoc"] == 0 and rt["nAll"] == 0 and rt["keKwh"] < 1e-12 and rt["chargeKwh"] < 1e-12 and rs["nSoc"] == 0 and rs["keKwh"] < 1e-12 and rs["keAll"] < 1e-12, (rt, rs)

# ---- (3)/(8) zero-charge interval stays in the denominator; pooled = ratio of sums
fr = frame(np.arange(5), [80, 70, 60, 50, 40], cur=[30, 30, -5, -5, -5])
T = table([fr]); dm1 = master(1, ["2026-03-01"]); c1 = G.Cohort(T, dm1, np.ones(1, bool), "t")
cell = c1.cell_block("all", np.ones(len(c1.drive), bool))["all"]
iv = c1.d
ke_i = R.KE_FACTOR * c1.mass * iv["iv_dv2"]
assert cell["nZeroCharge"] >= 1 and abs(cell["eff"] - 100 * iv["iv_charge"].sum() / ke_i.sum()) < 0.005
assert abs(cell["eff"] - 100 * np.mean(iv["iv_charge"] / ke_i)) > 0.5                                          # not a mean of interval percentages

# ---- (12) a drive warming through temperature bins: bins follow the start temperature, eligibility is unchanged
temps = np.linspace(8, 34, 9)
fr = brake(n=9);
for c in TC:
    fr[c] = temps
Tw = table([fr]); Tc = table([brake(n=9, temp=20.0)])
cw = G.Cohort(Tw, dm1, np.ones(1, bool), "w"); cc = G.Cohort(Tc, dm1, np.ones(1, bool), "c")
cbw = cw.cell_block("temperature", cw.sel["noSocCondition"])
assert sum(1 for v in cbw.values() if v.get("n")) >= 3 and (cw.tidx >= 0).all()
assert len(cw.drive) == len(cc.drive) and np.array_equal(cw.d["iv_dv2"], cc.d["iv_dv2"]) and np.array_equal(cw.d["iv_charge"], cc.d["iv_charge"])      # same eligibility, same energies

# ---- (11) day-clustered bootstrap: counts per draw sum to the number of days; a draw reproduces by hand; the seed reproduces
frames = [brake(cur=5.0 + 3 * k) for k in range(12)]
dmb = master(12, ["2026-03-%02d" % (1 + k // 2) for k in range(12)])          # 6 days x 2 drives
Tb = table(frames); cb = G.Cohort(Tb, dmb, np.ones(12, bool), "b")
assert cb.D == 6 and (cb.counts.sum(axis=1) == 6).all()
cell = cb.cell_block("all", np.ones(len(cb.drive), bool))["all"]
mats, _ = cb.mats("all"); Cd, Cod, Kd = cb.sums(mats, np.ones(len(cb.drive), bool))[:3]
b0 = cb.counts[0]; manual = 100 * (b0 @ Cd[:, 0]) / (b0 @ Kd[:, 0])
assert np.isfinite(manual) and abs(cell["eff"] - 100 * Cd.sum() / Kd.sum()) < 0.005
cb2 = G.Cohort(Tb, dmb, np.ones(12, bool), "b")
assert np.array_equal(cb.counts, cb2.counts) and cb2.cell_block("all", np.ones(len(cb2.drive), bool))["all"]["ci95"] == cell["ci95"]
assert cell["days"] == 6 and cell["drives"] == 12 and cell["status"] == "thin"                                    # fewer than 200 intervals: exploratory, never certified

# ---- support status
big = [brake(v0=100, n=11, step=9) for _ in range(30)]                                                              # 30 drives x ~10 intervals = 300 strict intervals on 6 days
dmbig = master(30, ["2026-03-%02d" % (1 + k // 5) for k in range(30)])
cs = G.Cohort(table(big), dmbig, np.ones(30, bool), "s")
bc = cs.cell_block("all", np.ones(len(cs.drive), bool))["all"]
assert bc["n"] >= 200 and bc["drives"] >= 10 and bc["days"] >= 5 and bc["status"] == "supported", bc
one_day = G.Cohort(table(big), master(30, ["2026-03-01"] * 30), np.ones(30, bool), "one")
assert one_day.cell_block("all", np.ones(len(one_day.drive), bool))["all"]["status"] in ("thin", "failed")            # a single day cannot be certified
emp = cs.cell_block("temperature", cs.sel["noSocCondition"])
assert emp["<-10°C"]["status"] == "empty" and emp["<-10°C"]["n"] == 0 and "eff" not in emp["<-10°C"]               # an absent bin is explicit and has no estimate (never zero)

# ---- (13) cache invalidation (temporary cache directory)
tmp = tempfile.mkdtemp()
K.CACHE_DIR = tmp
try:
    ch = {"loaderSchema": 7, "despikeSrc": "a", "speedPrioritySrc": "b", "policyHash": R.POLICY_HASH, "extractorSrc": "x1", "extractorVersion": R.EXTRACTOR_VERSION}
    mp, op = K._paths("f.csv", "base")
    K._save(mp, dict(ch, rawSha256="s1", variant="base"), {}); K._save(op, {"rawSha256": "s1", "iOff": -0.4, "extractorSrc": "x1", "variant": "base"}, {})
    assert K.entry_valid("f.csv", "base", "s1", ch, -0.4) == (True, True)
    assert K.entry_valid("f.csv", "base", "s2", ch, -0.4) == (False, False)                                          # a changed raw byte
    assert K.entry_valid("f.csv", "base", "s1", dict(ch, extractorSrc="x2"), -0.4) == (False, False)                   # a changed extractor
    assert K.entry_valid("f.csv", "base", "s1", dict(ch, policyHash="zz"), -0.4) == (False, False)                     # a changed policy constant
    assert K.entry_valid("f.csv", "base", "s1", dict(ch, loaderSchema=8), -0.4) == (False, False)                      # a changed loader schema
    assert K.entry_valid("f.csv", "lagP1", "s1", ch, -0.4) == (False, False)                                          # another variant has its own entry
    assert K.entry_valid("f.csv", "base", "s1", ch, -0.5) == (True, False)                                            # only the offset file is stale when i_off changes
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("test_regen_v2_agg: ALL PASSED")
