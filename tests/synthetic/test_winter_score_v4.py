"""M731 known-answer tests of winter_score v4 (analyses/M731_spec.md Rev 2.2): P6 dispatch (count rule, tolerance, not evaluable below support), P2 with a stubbed realised band (the window-matched band decides, the frozen band is kept beside),
P1 still not evaluable, P3 / P4 / P5 / P7 unchanged. The registry check is simulated; no observation after the freeze is read."""
import json, os, sys
import numpy as np
import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import winter_score as WS

F_ = json.load(open(os.path.join(ROOT, "analyses", "M717_winter_predictions.json"), encoding="utf-8"))
assert WS.REGISTRY == "analyses/M736_extractor_registry.json"


def frame(nd=24, nday=8, margin=-4.0, tmin=-3.0, ah_cold_share=0.1):
    r = np.random.default_rng(3)
    d = pd.DataFrame({"key": ["20261201%06d" % i for i in range(nd)], "day": ["2026-12-%02d" % (1 + i % nday) for i in range(nd)]})
    d["day_"] = d["day"]
    d["start"] = pd.to_datetime("2026-12-01 09:00:00") + pd.to_timedelta((np.arange(nd) % nday) * 24, unit="h")
    d["month"] = 12
    d["clean"] = True
    d["Tlo_min"] = tmin + (np.arange(nd) % 3) * 0.5
    d["pin_n"] = 0
    for c in ["pin_xty_%d" % i for i in range(3)] + ["pin_xtx_%d%d" % (i, j) for i in range(3) for j in range(3)]:
        d[c] = 0.0
    for c in ("ahc_T_<0", "ahd_T_<0", "ahd_T_0-5", "ahc_T_5-10", "ahd_T_5-10"):
        d[c] = 0.0
    d["ahc_T_0-5"] = 10.0 * ah_cold_share
    d["ahd_T_0-5"] = 0.0
    d["ahc_T_10-15"] = 10.0 * (1 - ah_cold_share)
    d["ahd_T_10-15"] = 0.0
    d["ahd_T_10-15"] = 0.0
    d["R_pulse_mohm"] = np.nan
    d["T_pulse"] = np.nan
    for c in ("km", "ah", "spd_s", "dur_h", "eng_on_s", "rpm_s", "ambient_start_c", "ambient_end_c"):
        d[c] = np.nan
    d["p6_n_s"] = 100
    d["p6_margin_c"] = margin
    d["p6_Tlo"] = -2.0
    d["p6_peak_c"] = 10.0
    d["p6_soc"] = 60.0
    d["p6_limit_c"] = 14.0
    return d


_orig, _tol = WS.extractors_frozen, WS.p6_tol
WS.extractors_frozen = lambda pid=None, changelog_text=None: (True, "frozen") if pid in ("P2", "P3", "P4", "P5", "P6", "P7") else (False, "not covered")
WS.p6_tol = lambda: 0.0
try:
    cells = {c["prediction"]: c for c in WS.score_all(frame(), F_, nb=100)}
    assert cells["P1"]["status"] == "not evaluable"
    c6 = cells["P6"]
    assert c6["status"] == "fitted" and c6["reading"] == "within the map" and c6["exceedCount"] == 0 and c6["nDrives"] == 24 and "delivered" in c6["kind"]
    # one exceedance on two days -> outside the map
    f = frame()
    f.loc[[0, 1], "p6_margin_c"] = 1.0
    assert {c["prediction"]: c for c in WS.score_all(f, F_, nb=100)}["P6"]["reading"] == "outside the map"
    # below support: 6 drives on 6 days
    assert {c["prediction"]: c for c in WS.score_all(frame(nd=6, nday=6), F_, nb=50)}["P6"]["status"] == "not evaluable"
    # no tolerance (check file missing) -> not evaluable, never a default
    WS.p6_tol = lambda: None
    assert {c["prediction"]: c for c in WS.score_all(frame(), F_, nb=50)}["P6"]["status"] == "not evaluable"
    WS.p6_tol = lambda: 0.0
    # P2 with a stubbed realised band: frozen band [0.0316, 0.1476]; observed share 0.1 inside it; a realised window-matched band [0.2, 0.4] puts it outside, and the frozen result is kept
    band = {"status": "ok", "windowMatched": [0.2, 0.4], "annual": [0.05, 0.15], "thinMonths": [], "flags": [], "table": [], "scenario": "S2"}
    p2 = {c["prediction"]: c for c in WS.score_all(frame(), F_, nb=100, realised_band_fn=lambda w: band)}["P2"]
    assert p2["status"] == "outside the band" and p2["frozenBandStatus"] == "within the band" and p2["realisedBand"]["windowMatched"] == [0.2, 0.4] and "window-matched" in p2["scoredAgainst"]
    band2 = dict(band, windowMatched=[0.05, 0.2])
    p2b = {c["prediction"]: c for c in WS.score_all(frame(), F_, nb=100, realised_band_fn=lambda w: band2)}["P2"]
    assert p2b["status"] == "within the band"
    # realised band not available: the frozen-band reading stands and the realised block says why
    na = {"status": "not available", "reason": "no month with at least 5 days"}
    p2c = {c["prediction"]: c for c in WS.score_all(frame(), F_, nb=100, realised_band_fn=lambda w: na)}["P2"]
    assert p2c["status"] == "within the band" and p2c["realisedBand"]["status"] == "not available" and "not the realised-ambient band" in p2c["scoredAgainst"]
    # below support the band is never computed
    called = []
    WS.score_all(frame(nd=6, nday=6), F_, nb=50, realised_band_fn=lambda w: called.append(1) or band)
    assert not called
    # the P6 sidecar hook is used only when the frame lacks the columns
    g = frame().drop(columns=[c for c in frame().columns if c.startswith("p6_")])
    side = frame()[["key"] + [c for c in frame().columns if c.startswith("p6_")]]
    assert {c["prediction"]: c for c in WS.score_all(g, F_, nb=50, p6_sidecar_fn=lambda w: side)}["P6"]["status"] == "fitted"
    assert {c["prediction"]: c for c in WS.score_all(g, F_, nb=50)}["P6"]["status"] == "not evaluable"
    # M736: the v4 hook replaces the status and keeps the v3 status beside
    p2d = {c["prediction"]: c for c in WS.score_all(frame(), F_, nb=100, realised_band_fn=lambda w: band2, p2_v4_fn=lambda w, ev, ep: {"status": "not established (ambient-scale sensitive)", "call": None})}["P2"]
    assert p2d["status"] == "not established (ambient-scale sensitive)" and p2d["v3Status"] == "within the band" and "registry v4" in p2d["scoredAgainst"]
finally:
    WS.extractors_frozen, WS.p6_tol = _orig, _tol
print("OK test_winter_score_v4")
