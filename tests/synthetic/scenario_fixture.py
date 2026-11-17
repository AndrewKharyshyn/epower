"""Shared synthetic model for the scenario tests (M713d): six consecutive calendar days (2 summer-month days, 4 autumn-month days), two drives per day, constant slices; every frame column the engine and the validation read."""
import os, sys
import numpy as np, pandas as pd
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import scenario_engine as SE
import scenario_frame as SF

K, NCB = 16, len(SF.CB) - 1


def build_model(days=("2026-08-30", "2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"), odo_km=2000.0):
    rows, keys = [], []
    for di, day in enumerate(days):
        for j in range(2):
            key = day.replace("-", "") + "%02d0000" % (8 + 6 * j)
            ah = 3.0 + 0.5 * di + j
            r = {"key": key, "day": day, "start": pd.Timestamp(day) + pd.Timedelta(hours=8 + 6 * j), "dur_h": 0.4, "km": 4.0 + 3.0 * di + 2.0 * j, "ah": ah, "kwh": 1.1 * ah, "soc_end": 58.0,
                 "eng_starts": 2 + j, "T_start": 14.0 + 3 * di, "T_end": 25.0, "afah_50": ah * 1.1, "ah_noT": 0.0}
            for l in SF.SOCLAB:
                r["ah_S_%s" % l] = 0.0
            r["ah_S_55-60"] = ah
            for l in SF.TLAB:
                r["ahc_T_%s" % l] = 0.0
                r["ahd_T_%s" % l] = 0.0
            r["ahc_T_20-25"] = ah / 2
            r["ahd_T_20-25"] = ah / 2
            rows.append(r)
            keys.append(key)
    D = pd.DataFrame(rows)
    n = len(D)
    ahc = np.tile((D["ah"].values * 0.5 / K)[:, None], (1, K))
    cb = np.zeros((n, K, NCB))
    cb[:, :, 1] = ahc
    Z = {"keys": np.array(keys), "K": K, "icov": np.ones(n), "i2": np.full((n, K), 400.0), "ahc": ahc, "ahd": ahc.copy(), "soc": np.full((n, K), 58.0), "Tobs": np.full((n, K), 22.0),
         "ep10c": np.zeros((n, K)), "ep20c": np.zeros((n, K)), "ep10d": np.zeros((n, K)), "ep20d": np.zeros((n, K)), "ahc_cb": cb, "ahcC_cb": cb * 3.0 / SF.CAP_AH_RATED}
    AR = pd.DataFrame({"key": keys, "Abar_s": 10.0, "Abar_e": 10.0, "amp": 0.0, "hpk": 15.0, "h0": D["start"].dt.hour.values.astype(float), "h1": D["start"].dt.hour.values + 0.4})
    amb = pd.DataFrame({"key": keys, "A0": 10.0, "A1": 10.0})
    odo = {"unloggedDays": [], "noOdometerCoverDays": [], "factors": {"f_s_summerWindow": 1.1, "f_a_laterIntervalsWithoutUnlogged": 1.2}}
    state = {"params_for_scenarios": {"EaR": 17.58, "park": {"tau": 9.0, "off": 0.5}, "drive": {"alpha": 0.013, "tau_d": 1.0, "c0": 24.0, "c1": 0.22}, "diurnal": {"summer": [0.0, 15.0], "autumn": [0.0, 15.0]},
                                      "pin": {"b0": 34.0, "bT": 1.5, "bS": -1.0}}}
    params = SE.default_params(state, odo)
    M = SE.Model(D, Z, AR, amb, np.full(12, 10.0), odo, params, pool_rule="data", odo_km=odo_km)
    return M, D
