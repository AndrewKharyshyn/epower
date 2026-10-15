"""M444 known-answer tests of the SOC-standardized apparent KE recovery (spec analyses/M444_spec.md Rev 2, section 9): tools/regen_std.py.
(1) Simpson fixture: identical within-SOC recovery, different SOC mixes -> different observed bars, equal standardized bars; (2) one weight vector for every bar, summing to 1; (3) a missing joint cell removes the SOC band for ALL bars, the declared drop order,
'unavailable' with a reason; (4) a bar whose SOC mix is proportional to the reference over S* equals its observed-on-S* value (1e-9); (5) failed draws are counted, more than 2.5 % make the interval unavailable, a contrast draw fails if either bar fails;
(6) week blocks resample the days of one ISO week together; week support; (7) episode deceleration, KE-weighted tercile cut points stored and applied, the ladder reports 'not checked for braking demand' when no level has support;
(8) the holdout uses the full fixed weights and the full-sample reference signs on S*_k; (9) reconciliation of the KE over S* plus the excluded KE."""
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
import regen_std as S

SP, RPM, I_, V_ = "[VCM] Vehicle Speed (km/h)", "Оберти двигуна (rpm)", "[BMS] HV Battery Current (A)", "[BMS] HV Battery voltage (V)"
SOC = "[BMS] HV State of charge (%)"
TC = ["[BMS] HV Battery Temperature Sensor %d (℃)" % k for k in (1, 2, 3, 4)]
T0 = pd.Timestamp("2026-03-01 10:00:00")


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


CUR = {57.0: 10.0, 67.0: 20.0}                                           # within-SOC recovery depends on the SOC band only
SPEC_MIX = {25.0: {57.0: 90, 67.0: 30}, 35.0: {57.0: 30, 67.0: 90}, 45.0: {57.0: 60, 67.0: 60}}                 # every joint cell has >= 30 drives (240 strict intervals) on 8 days


def build(mix, ndays=8):
    frames, dates = [], []
    i = 0
    for temp, socs in mix.items():
        for soc, n in socs.items():
            for _ in range(n):
                frames.append(brake(soc, temp, CUR[soc]))
                dates.append((pd.Timestamp("2026-03-01") + pd.Timedelta(days=i % ndays)).strftime("%Y-%m-%d"))
                i += 1
    dm = pd.DataFrame({"file": ["d%d.csv" % k for k in range(len(frames))], "date": dates, "drive_type": ["urban"] * len(frames), "ev_rpm_dt_med_s": [1.0] * len(frames)})
    return table(frames), dm


def prep(T, dm, days=None):
    co = G.Cohort(T, dm, np.ones(len(dm), bool), "t", days=days)
    labels, J = S.joint(co, "temperature", S.soc_strata(co))
    cb = co.cell_block("temperature", co.sel["allSoc"])
    cand = [g for g, l in enumerate(labels) if cb.get(l, {}).get("status") == "supported"]
    w, _ = S.reference_weights(J, list(range(len(labels))))
    return co, labels, J, cb, cand, w


T, dm = build(SPEC_MIX)
co, labels, J, cb, cand, w = prep(T, dm)
cs = S.common_support(J, w, cand)
assert cs["available"] and set(labels[g] for g in cs["groups"]) == {"20–30°C", "30–40°C", "40–50°C"} and abs(cs["coverage"] - 1.0) < 1e-12
std, wt = S.standardize(J, w, cs, co.counts)
g25, g35, g45 = [labels.index(x) for x in ("20–30°C", "30–40°C", "40–50°C")]
obs = {g: cb[labels[g]]["eff"] for g in (g25, g35, g45)}
# ---- (1) Simpson fixture
assert abs(obs[g25] - obs[g35]) > 2.0, obs                                           # the observed bars differ because the SOC mixes differ
assert abs(std[g25]["point"] - std[g35]["point"]) < 1e-9 and abs(std[g25]["point"] - std[g45]["point"]) < 1e-9
# ---- (2) one weight vector for every bar, summing to 1
assert abs(wt.sum() - 1.0) < 1e-12 and abs(sum(w.values()) - 1.0) < 1e-12
# ---- (4) proportional mix over S* -> standardized equals observed-on-S* (the 45 C group: 15 + 15 identical-KE drives against a 50/50 pooled reference)
assert abs(w["band 55-60"] - w["band 66-69"]) < 1e-9
assert abs(std[g45]["point"] - S.observed_on_s(J, cs, g45)) < 1e-9, (std[g45]["point"], S.observed_on_s(J, cs, g45))
assert abs(S.observed_on_s(J, cs, g25) - std[g25]["point"]) > 0.5                       # a group with a different mix does not
# ---- (3) a missing joint cell removes the band for ALL bars; drop order; unavailable with a reason
mix3 = {25.0: {57.0: 90, 67.0: 30}, 35.0: {57.0: 30, 67.0: 90}, 45.0: {67.0: 60}}              # the 45 C bin has only the 66-69 band
T3, dm3 = build(mix3)
co3, l3, J3, cb3, cand3, w3 = prep(T3, dm3)
cs3 = S.common_support(J3, w3, cand3)
assert w3["band 66-69"] < 0.8 and cs3["available"] and [l3[g] for g in cs3["dropped"]] == ["40–50°C"] and set(cs3["strata"]) == {"band 55-60", "band 66-69"}
mix4 = {25.0: {57.0: 30}, 35.0: {67.0: 30}}                                           # no band is supported for both groups
T4, dm4 = build(mix4)
co4, l4, J4, cb4, cand4, w4 = prep(T4, dm4)
cs4 = S.common_support(J4, w4, cand4)
assert (not cs4["available"]) and "coverage" in cs4["reason"] and cs4["coverage"] == 0.0
# tie-break: two groups with identical support and KE -> the LOWEST bin is dropped first (the group index)
mix5 = {25.0: {57.0: 30, 67.0: 30}, 35.0: {57.0: 30, 67.0: 30}, 45.0: {57.0: 30, 67.0: 30}}
T5, dm5 = build(mix5)
co5, l5, J5, cb5, cand5, w5 = prep(T5, dm5)
cs5 = S.common_support(J5, w5, cand5, thr=1.01)                                       # an unreachable threshold: groups are dropped until fewer than 2 remain
assert [l5[g] for g in cs5["dropped"]] == ["20–30°C"] and not cs5["available"]      # identical support and KE: the LOWEST bin goes first
# ---- (5) failed draws; a contrast draw fails if either bar fails
assert S.interval(np.array([1.0] * 97 + [np.nan] * 3))[0] is None
assert S.interval(np.array([1.0] * 99 + [np.nan]))[0] is not None and S.interval(np.array([1.0] * 90 + [np.nan] * 10))[0] is None
a_, b_ = np.array([1.0, np.nan, 3.0, 4.0] * 50), np.array([2.0, 5.0, np.nan, 7.0] * 50)
assert np.isnan(b_ - a_).sum() == 100 and S.interval(b_ - a_)[0] is None
# ---- (6) week blocks: the days of one ISO week are resampled together; week support counts distinct ISO weeks
days = ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-09", "2026-03-10"]            # Mon-Wed of week 10, Mon-Tue of week 11
cw, nw = S.week_counts(co, days, B=200)
assert nw == 2 and (cw[:, 0] == cw[:, 1]).all() and (cw[:, 1] == cw[:, 2]).all() and (cw[:, 3] == cw[:, 4]).all()
widx, W = S.week_index(["2026-03-01", "2026-03-02", "2026-03-08", "2026-03-09", "2026-03-16"])
assert W == 4 and widx[0] != widx[1] and widx[1] == widx[2] and widx[2] != widx[3]            # Sunday 2026-03-01 closes ISO week 9; Monday 03-02 .. Sunday 03-08 are one ISO week (10)
# ---- (7) episode deceleration, tercile cut points stored and applied, the ladder without support
a = S.episode_decel(co)
assert np.allclose(a[co.est], (80 - 16) / 3.6 / 8.0, atol=1e-9)                      # every synthetic drive: 80 -> 16 km/h in 8 s
cuts = S.demand_cuts(co)
assert len(cuts) == 2 and cuts[0] <= cuts[1] and abs(cuts[0] - (80 - 16) / 3.6 / 8.0) < 1e-9
sm, dmk = S.demand_masks(co3, cuts)                                                    # applied to another cohort, not recomputed
assert dmk["high"][co3.est].all() or dmk["mid"][co3.est].all() or dmk["low"][co3.est].all()
wref = S.demand_reference(co, cuts)
db = S.demand_block(co, cuts, wref)
assert db["result"] == "not checked for braking demand" and all(not r["available"] for r in db["ladder"]) and "overlapKeShare" in db        # 30 drives per cell cannot support 72 / 24 / 27 demand strata
# ---- (8) holdout on a larger fixture: 20 days, 110 drives per cell (4 blocks of 5 days)
mixh = {25.0: {57.0: 110, 67.0: 110}, 35.0: {57.0: 110, 67.0: 110}}
Th, dmh = build(mixh, ndays=20)
coh, lh, Jh, cbh, candh, wh = prep(Th, dmh)
csh = S.common_support(Jh, wh, candh)
assert csh["available"]
asked = []
def mk(days_):
    asked.append(tuple(sorted(days_)))
    return G.Cohort(Th, dmh, np.ones(len(dmh), bool), "h", days=days_)
alld = sorted(set(dmh["date"]))
hb = S.holdout_block(mk, (lh, Jh, csh), wh, alld)
assert len(hb["blocks"]) == 4 and all(b["nDays"] == 5 for b in hb["blocks"]) and all(b["available"] for b in hb["blocks"]), hb["blocks"]
fulls = [x for x in asked if len(x) == len(alld)]
assert len(fulls) == 1                                                                   # the full-sample cohort is built once; the weights are the FIXED full w (no refit in the primary holdout)
parts = [set(x) for x in asked if len(x) == 5]
rests = [set(x) for x in asked if len(x) == 15]
assert len(parts) == 4 and len(rests) == 4 and all(not (p & r) and len(p | r) == 20 for p, r in zip(parts, rests))
assert hb["summary"]["nAdjacentPairs"] == 4 and hb["summary"]["nSameSign"] == 4        # one adjacent pair per block (25 C vs 35 C), identical standardized bars -> the sign (0) agrees with the full sample
# ---- (9) reconciliation: the KE over S* plus the excluded KE equals the group KE
for g in cs["groups"]:
    tot = sum(float(J[k]["K"][:, g].sum()) for k in J)
    inside = sum(float(J[k]["K"][:, g].sum()) for k in cs["strata"])
    assert abs(tot - inside - sum(float(J[k]["K"][:, g].sum()) for k in J if k not in cs["strata"])) < 1e-12
# ---- (5b) S5: the sign of an adjacent difference whose day interval contains 0 is indeterminate
rng_ = np.random.default_rng(0)
fake = {0: {"point": 10.0, "draws": 10.0 + rng_.normal(0, 1.0, 4000)}, 1: {"point": 10.2, "draws": 10.2 + rng_.normal(0, 1.0, 4000)}, 2: {"point": 15.0, "draws": 15.0 + rng_.normal(0, 1.0, 4000)}}
sg = S.ci_signs(fake, ["a", "b", "c"], [0, 1, 2])
assert sg["a>b"] == "indeterminate" and sg["b>c"] == 1
print("test_regen_std: ALL PASSED")
