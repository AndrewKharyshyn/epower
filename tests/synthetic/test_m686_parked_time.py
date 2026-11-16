"""Known-answer tests for tools/parked_time_budget.py (M686 spec Rev 1.1, section 6)."""
import math, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)
import parked_time_budget as P

TAU = 8.0


def test_single_gap_analytic_crossings():
    # T0 = 30, A = 10, tau = 8: crosses 25 at t = -8 ln(15/20), 20 at t = -8 ln(10/20), 15 at t = -8 ln(5/20)
    h = P.band_hours(30.0, 10.0, 100.0, TAU)
    t25, t20, t15 = -TAU * math.log(15 / 20), -TAU * math.log(10 / 20), -TAU * math.log(5 / 20)
    assert abs(h[P.band_of(27)] - t25) < 1e-9          # 25-30
    assert abs(h[P.band_of(22)] - (t20 - t25)) < 1e-9  # 20-25
    assert abs(h[P.band_of(17)] - (t15 - t20)) < 1e-9  # 15-20
    assert abs(h.sum() - 100.0) < 1e-9                 # V5
    # asymptote A = 10 sits on an edge-free region only above 10: A = 10 is the upper band edge value 10-15, never reached from above except at infinity
    assert h[P.band_of(12)] > 100.0 - t15 - 1e-9 or h[P.band_of(12)] + h[P.band_of(7)] > 0


def test_cooling_and_warming_and_short_gap():
    cool = P.band_hours(12.0, 2.0, 50.0, TAU)
    warm = P.band_hours(2.0, 12.0, 50.0, TAU)
    assert cool[:3].sum() > 0 and warm[2:4].sum() > 0
    short = P.band_hours(30.0, 10.0, 0.1, TAU)     # shorter than the first crossing (25 at 2.3 h)
    assert abs(short[P.band_of(29)] - 0.1) < 1e-12


def test_edge_value_goes_to_upper_band_and_constant():
    assert P.band_of(10.0) == P.LABELS.index("10-15") and P.band_of(-0.0001) == 0 and P.band_of(40.0) == P.NB - 1
    h = P.band_hours(20.0, 20.0, 5.0, TAU)
    assert h[P.band_of(20.0)] == 5.0


def test_long_gap_lands_in_band_of_A():
    h = P.band_hours(25.0, 3.0, 400.0, TAU)
    assert h[P.band_of(3.0)] > 400.0 - 8 * TAU      # after about 5 tau the pack is at A
    assert abs(h.sum() - 400.0) < 1e-9


def test_exact_vs_numeric_within_tolerance():
    for T0, A, g in ((30, 10, 60), (-3, 12, 40), (18, 18.5, 12), (41, 5, 90)):
        ex = P.band_hours(T0, A, g, TAU)
        nu = P.band_hours_numeric(T0, (lambda t, A=A: A), g, TAU)
        assert np.abs(ex - nu).max() < 1e-3


def test_threshold_slices_match_band_labels():
    res = {"bands": np.arange(1.0, 11.0), "noLong": np.arange(1.0, 11.0), "byCls": np.ones((5, P.NB))}
    m = P.metrics(res)
    assert m["cold10"] == sum(m["band:" + l] for l in ("<0", "0-5", "5-10")) and m["cold15"] == m["cold10"] + m["band:10-15"]
    assert m["hot35"] == m["band:35-40"] + m["band:>=40"] and m["hot40"] == m["band:>=40"]
    assert m["hot35NoLong"] == m["hot35"] and m["cold10NoLong"] == m["cold10"]


def _frame(rows):
    """rows: (start_utc, dur_h, tFirst, tLast, amb_start, amb_end, unlogged, clean)"""
    d = pd.DataFrame(rows, columns=["t0u", "durH", "tFirst", "tLast", "amb_start", "amb_end", "unlogged", "clean"])
    d["t0u"] = pd.to_datetime(d["t0u"])
    d["date"] = d["t0u"].dt.strftime("%Y-%m-%d")
    d["hour_end"] = 12.0
    return d


def test_gap_building_and_unassigned_and_accounting():
    d = _frame([("2026-06-01 08:00", 1.0, 20, 25, 18, 20, 0.0, True),
                ("2026-06-01 12:00", 1.0, 22, 23, 21, 22, 0.0, True),
                ("2026-06-02 08:00", 1.0, np.nan, 24, 15, 16, 0.0, True),
                ("2026-06-02 09:30", 1.0, 20, np.nan, np.nan, 15, 2.0, True),     # gap before it: missing T? previous tLast=24 ok; ambient start nan -> missing ambient
                ("2026-06-02 11:00", 1.0, 20, 21, 15, 16, 0.0, True)])             # previous tLast is NaN -> missing pack end temperature
    gaps = P.build_gaps(d)
    assert len(gaps) == 4 and [x["status"] for x in gaps] == ["assigned", "assigned", "unassigned", "unassigned"]
    assert gaps[2]["reason"] == "missing ambient reading" and gaps[3]["reason"] == "missing pack end temperature"
    acc = P.accounting(d, gaps, TAU)
    assert acc["v1Passed"] and abs(acc["sumHours"] - acc["windowHours"]) < 1e-9


def test_overlap_gap_is_unassigned_and_signed():
    d = _frame([("2026-06-01 08:00", 3.0, 20, 25, 18, 20, 0.0, True), ("2026-06-01 10:00", 1.0, 22, 23, 21, 22, 0.0, True)])
    g = P.build_gaps(d)
    assert g[0]["status"] == "unassigned" and g[0]["reason"] == "overlap" and g[0]["g"] < 0
    assert P.accounting(d, g, TAU)["v1Passed"]


def test_dst_aware_elapsed_time():
    # same local wall times, UTC differs by the offset change: the gap is computed from UTC
    d = _frame([("2026-10-24 20:00", 1.0, 20, 15, 10, 10, 0.0, True), ("2026-10-25 20:00", 1.0, 14, 13, 10, 10, 0.0, True)])
    g = P.build_gaps(d)
    assert abs(g[0]["g"] - 23.0) < 1e-9


def _gaps(n=12):
    rows, t = [], pd.Timestamp("2026-06-01 00:00")
    for k in range(n):
        rows.append((t, 1.0, 20, 24, 10 + k % 3, 12, 0.0, True))
        t = t + pd.Timedelta(hours=1 + 6 + 3 * k)
    return P.build_gaps(_frame(rows))


def test_ambient_shift_moves_hours_as_expected():
    g = _gaps()
    base = P.metrics(P.evaluate(g, TAU))
    warm = P.metrics(P.evaluate(g, TAU, shift=2.0))
    cold = P.metrics(P.evaluate(g, TAU, shift=-2.0))
    assert cold["cold10"] >= base["cold10"] >= warm["cold10"] and cold["cold15"] > warm["cold15"]
    assert abs(base["parkedHours"] - sum(x["g"] for x in g if x["status"] == "assigned")) < 1e-9


def test_indoor_rules_and_realised_fraction():
    g = _gaps(30)
    for rule in ("everyKth", "coldestFirst", "hottestFirst"):
        s, r = P.indoor_set(g, 0.10, rule)
        assert s and 0 < r < 0.5 and all(g[j]["g"] >= 4.0 for j in s)
    assert P.indoor_set(g, 0.0, "everyKth") == (set(), 0.0)
    cold = {P.indoor_set(g, 0.10, "coldestFirst")[0] == P.indoor_set(g, 0.10, "hottestFirst")[0]}
    assert cold == {False}


def test_grid_min_max_and_axis():
    g = _gaps(20)
    q3 = {"primary": {"tauH": 8.0}, "heldOut": {"gatePassed": True}, "sensitivities": {"gap4hOrLonger": {"tauH": 7.0}, "L2Loss": {"tauH": 8.1}, "previousDriveMaxProxy": {"tauH": 7.5},
                                                                                    "ambientRefShift-2C": {"tauH": 9.0}, "ambientRefShift+2C": {"tauH": 6.5}, "projectDefinitionOutcomeFiltered": {"tauH": 11.0}}}
    ent, gate, _ = P.tau_axis(q3)
    names = [e[0] for e in ent]
    assert gate and names[0] == "primary" and len(ent) == 6 and not any("project" in n for n in names)
    assert [e[2] for e in ent if "Shift-2" in e[0] or "Shift+2" in e[0]] == [-2.0, 2.0]
    cells = P.run_grid(g, ent)
    s = P.grid_summary(cells)
    assert len(cells) == 6 * 3 * 7
    prim = P.metrics(P.evaluate(g, 8.0))
    assert s["cold10"]["min"] <= prim["cold10"] <= s["cold10"]["max"] and s["parkedHours"]["min"] <= s["parkedHours"]["max"]
    q3["heldOut"]["gatePassed"] = False
    ent2, gate2, _ = P.tau_axis(q3)
    assert not gate2 and "primary" not in [e[0] for e in ent2]


def test_support_ladder_and_unlogged_sensitivity():
    g = _gaps(20)
    sup = P.band_support(g, TAU)
    assert all(s["status"] in ("not shown", "exploratory", "supported") for s in sup)
    base = P.metrics(P.evaluate(g, TAU))["parkedHours"]
    gg = [dict(x) for x in g]
    gg[3]["unlogged"] = True
    less = P.metrics(P.evaluate(gg, TAU, treat_unlogged_unassigned=True))["parkedHours"]
    assert less < base and abs(base - less - gg[3]["g"]) < 1e-9


def test_planted_tau_placebo_drop_and_determinism():
    rng = np.random.default_rng(1)
    rows, t = [], pd.Timestamp("2026-05-01 06:00")
    for k in range(120):
        amb = rng.uniform(0, 25)
        T0 = amb + rng.uniform(5, 15)
        g = rng.uniform(1.5, 12.0)
        nxt = amb + (T0 - amb) * math.exp(-g / TAU) + rng.normal(0, 0.1)
        rows.append((t, 0.5, nxt, T0, amb, amb, 0.0, True))
        t = t + pd.Timedelta(hours=0.5 + g)
    d = _frame(rows)
    gaps = P.build_gaps(d)
    # overwrite the observed next-start with the planted law
    d2 = d.copy()
    for k, x in enumerate(gaps):
        d2.loc[x["i"], "tFirst"] = x["A"] + (x["T0"] - x["A"]) * math.exp(-x["g"] / TAU)
    gaps = P.build_gaps(d2)
    tm = [x["status"] == "assigned" for x in gaps]
    v = P.endpoint_validation(gaps, tm, nperm=200)
    assert v["nPairs"] > 100
    cl = [c for c in v["byClass"].values() if "maeModelC" in c]
    assert cl and all(c["maeModelC"] < 0.5 and c["skillDropsUnderPlacebo"] for c in cl)
    assert P.endpoint_validation(gaps, tm, nperm=200) == v


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    import language_gate as G
    rule = {x.rid: x for x in G.RULES}["M686-parked-time-wording"]
    for bad in ("the measured parked temperature", "calendar ageing of the pack", "damage while parked", "parked hours per year", "parked lifetime exposure", "validated parked temperature"):
        assert rule.hits(bad), bad
    for ok in ("modelled parked pack temperature", "assumed outdoor parking (owner statement 2026-11-16)"):
        assert not rule.hits(ok), ok
    print("PASS test_m686_parked_time")
