"""M667 (N-02, spec analyses/M666_spec.md Rev 1.1): known-answer test of tools/n02_seasonal_fits on a constructed drive set with planted quantities.
Planted: Q1 gamma = -0.012 per C below 15 C (consumption rises when cold, i.e. ln(Ah/km) falls with ambient), Q2 beta = 0.6, Q3 tau = 8 h on the temperature scale.
Checks: estimates recovered, intervals cover the planted values, a thin cold band is 'not shown' and its slope 'not observed at this support', the L1 temperature-scale estimator recovers tau while the
outcome-filtered project variant is biased on the same set (the reason for D-05), the held-out gate passes for the planted model and fails for a planted no-decay set, determinism.
Run: python tests/synthetic/test_m667_seasonal_fits.py"""
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT); sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, ROOT)
import numpy as np
import pandas as pd
import n02_seasonal_fits as N

TAU, GAMMA, BETA = 8.0, 0.012, 0.6


def make(seed=7, decay=True, n_days=70, per_day=6):
    rng = np.random.default_rng(seed)
    rows = []
    t = pd.Timestamp("2026-06-01 08:00:00")
    for k in range(n_days):
        amb_day = 8.0 + 14.0 * rng.random()                       # 8 .. 22 C: no day below 5 C
        if k < 2:
            amb_day = 2.0                                          # a thin cold band: 2 days
        t = pd.Timestamp("2026-06-01") + pd.Timedelta(days=k) + pd.Timedelta(hours=8)
        prev_end = None
        for j in range(per_day):
            dist = float(rng.uniform(2, 20)); dur = dist / 30.0 * 3600.0
            cls = ["urban", "mixed", "highway"][j % 3]
            amb = amb_day                                         # the pair reference is exact in the planted set
            cold = max(0.0, 15.0 - amb)
            lahkm = -1.0 + 0.1 * (cls == "mixed") + 0.2 * (cls == "highway") + GAMMA * cold + rng.normal(0, 0.03)
            ah = dist * np.exp(lahkm)
            ldur = np.log(dur / 60.0)
            pack = 15.0 + BETA * (amb - 15.0) + 0.5 * ldur + 0.5 * (cls == "highway") + rng.normal(0, 0.4)
            t_end = amb + 12.0 + rng.normal(0, 0.8)                # pack temperature at the end of the drive
            gap = float(rng.choice([0.1, 0.5, 1.0, 2.0, 4.0, 8.0, 14.0, 24.0])) if j > 0 else 40.0      # day-start pairs lie outside the 0.02 to 36 h window (the ambient reference changes between days)
            if prev_end is not None:
                e0 = prev_end[0] - prev_end[1]
                t_first = prev_end[1] + (e0 * np.exp(-gap / TAU) if decay else e0) + rng.normal(0, 1.0)
            else:
                t_first = amb + 3.0 + rng.normal(0, 1.0)
            t = t + pd.Timedelta(hours=gap if j > 0 else 0.0)
            rows.append(dict(file="f%05d.csv" % len(rows), date=str(t.date()), t0=t, t1=t + pd.Timedelta(seconds=dur), distance_km=dist, duration_s=dur, dclass=cls, drive_type=cls,
                             ah_throughput=ah, ambient_time_mean_c=amb, pack_temp_time_mean_c=pack, ambient_start_c=amb, ambient_end_c=amb, pack_temp_start_c=t_first, pack_temp_max_c=t_end + 1.0,
                             tFirst=t_first, tLast=t_end, unlogged_distance_est_km=0.0, clean=True, gap_h=gap))
            t = t + pd.Timedelta(seconds=dur)
            prev_end = (t_end, amb)
    d = pd.DataFrame(rows)
    return d


d = make()
B = N.aggregate(d, nb=300)
q1, q2, q3 = B["Q1"], B["Q2"], B["Q3"]
# Q1 and Q2 planted values (the cold variable is max(0, 15 - ambient); consumption rises when cold: ln(Ah/km) = ... + GAMMA * cold with GAMMA > 0 planted in the log of Ah per km)
assert abs(q1["primary"]["estimate"] - GAMMA) < 0.004 and q1["primary"]["ci95"][0] <= GAMMA <= q1["primary"]["ci95"][1], q1["primary"]
assert q1["reading"] == "positive association by thermal class", q1["reading"]
assert abs(q2["primary"]["estimate"] - BETA) < 0.08 and q2["primary"]["ci95"][0] <= BETA <= q2["primary"]["ci95"][1], q2["primary"]
assert q2["flags"]["outsidePhysicalRange0to1p5"] is False and "none" in q2["priorM28"]
# thin cold band: 2 days -> not shown; slope below 5 C not observed at this support
assert B["data"]["bandSupport"]["below 5 C"]["status"] == "not shown" and q1["belowFiveC"] == "not observed at this support", (B["data"]["bandSupport"], q1["belowFiveC"])
assert B["data"]["bandSupport"]["15 C or warmer"]["status"] in ("exploratory", "supported")
# prior comparison prints a difference and an overlap flag (priors are bands)
pc = q1["priorM28CompareConsumptionSlope"]
assert set(pc["prior"]) == {"lo", "mid", "hi"} and pc["intervalOverlapsPriorBand"] in (True, False)
# Q3: the L1 temperature-scale estimator recovers the planted tau; the outcome-filtered variant is biased high on the same set
t3 = q3["primary"]["tauH"]
assert abs(t3 - TAU) / TAU < 0.08 and (q3["primary"]["ci95"][1] - q3["primary"]["ci95"][0]) < 0.3 * TAU and q3["primary"]["ci95"][0] < TAU * 1.02 and q3["primary"]["ci95"][1] > TAU * 0.9, q3["primary"]
# the outcome filter (residual excess > 0.5 C) biases the log-scale project variant on a long-gap set while the L1 temperature-scale fit stays close (the reason for D-05)
rng_b = np.random.default_rng(3)
gap_b = rng_b.choice([16.0, 24.0, 30.0], 400)
pb = pd.DataFrame({"prevEnd": 12.0 + 0 * gap_b, "amb": 0.0, "gap_h": gap_b})
pb["nextStart"] = 12.0 * np.exp(-gap_b / TAU) + rng_b.normal(0, 1.0, 400)
pj, l1b = N.project_tau(pb)["tauH"], N.fit_variant(pb, "prevEnd", "nextStart")["tauH"]
assert pj > TAU * 1.15 and abs(l1b - TAU) / TAU < 0.08, (pj, l1b)
assert q3["sensitivities"]["projectDefinitionOutcomeFiltered"]["tauH"] is not None
assert q3["heldOut"]["gatePassed"] is True and q3["d05"]["support"] == "supported"
assert q3["heldOut"]["skillVsPersistence"]["ci95"][0] > 0 and q3["heldOut"]["skillVsFullRelaxation"]["ci95"][0] > 0
assert q3["heldOut"]["skillVsBetterReference"]["estimate"] <= min(q3["heldOut"]["skillVsPersistence"]["estimate"], q3["heldOut"]["skillVsFullRelaxation"]["estimate"]) + 1e-9
assert q3["support"]["status"] == "supported" and q3["unloggedDrivingFlag"]["nFlagged"] == 0
# ambient-reference shifts are listed and move tau in the expected direction (a higher ambient_ref shrinks e0 and tau)
assert q3["sensitivities"]["ambientRefShift-2C"]["tauH"] > q3["sensitivities"]["ambientRefShift+2C"]["tauH"]
# Q4: index grid present, primary labelled, bounded, tau dependence visible, shares sum to 1
g = B["Q4"]["grid"]
assert any(r["tauLabel"] == "primary L1 temperature scale" for r in g) and B["Q4"]["primaryTau"] == "primary"
assert all(0 < r["index"] < 1.5 and abs(sum(r["shareOfIndex"].values()) - 1.0) < 1e-3 for r in g)
assert "not a life" in B["Q4"]["label"]
# no-decay set: persistence is the truth, so the held-out gate must fail and the block must not name a primary tau
dn = make(seed=11, decay=False)
Bn = N.aggregate(dn, nb=300)
assert Bn["Q3"]["heldOut"]["gatePassed"] is False and Bn["Q3"]["d05"]["support"] == "not supported", Bn["Q3"]["heldOut"]["skillVsBetterReference"]
assert Bn["Q4"]["primaryTau"].startswith("none") and not any(r["tauLabel"] == "primary L1 temperature scale" for r in Bn["Q4"]["grid"])
assert "no silent switch" in Bn["Q3"]["d05"]["ifNotSupported"]
# determinism
assert json.dumps(N.aggregate(d, nb=300), sort_keys=True, default=str) == json.dumps(B, sort_keys=True, default=str)
# language rule and stage wiring
import language_gate as G
rule = {r.rid: r for r in G.RULES}["M666-seasonal-fits-wording"]
for bad in ("equivalent years of use", "the ageing rate rises", "years of life remaining", "the slope is caused by the cold"):
    assert rule.hits(bad), bad
for good in ("Arrhenius-weighted temperature exposure index relative to constant 25 C", "association by thermal class", "not resolved at this support"):
    assert not rule.hits(good), good
ids = [s["id"] for s in json.load(open("tools/ingest_stages.json", encoding="utf-8"))["stages"]]
assert ids.index("cohort_contrast") < ids.index("seasonal_fits") < ids.index("stamp_basis")
assert "seasonal_fits_cache/" in open(".gitignore", encoding="utf-8").read()
print("PASS test_m667_seasonal_fits")
