#!/usr/bin/env python3
"""Automated data-health section for every brief -> data_health.json (so reviewers see anomalies nobody asked about).
Reads drive_master.csv (+ seasonal_drive_master.csv if present). Usage: python tools/data_health.py [--last N]
Contents: n drives/days, per-column missingness (columns >5% missing), shift of the last N drives vs the rest
(standardised mean difference + KS statistic) for key numeric columns, current-sensor offset values in use, exclusion
counts (ens_invalid / ens_outlier_v2), per-cohort n and days, duplicate file keys, date coverage."""
import argparse, json, os, sys
import numpy as np, pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
P = lambda *a: os.path.join(ROOT, *a)
KEY = ["gross_throughput_kwh", "distance_km", "engine_on_pct", "ev_dist_pct", "soc_range", "soc_band", "regen_share_of_charge",
       "standstill_draw_kw", "vsag_R_pack_mohm", "vreg_R_pack_mohm", "cell_spread_loaded_p95_adj_mv", "T_pack_mean_avg",
       "speed_mean_moving", "rf_n_cycles", "peak_discharge_kw", "peak_I_charge", "n_I_samples", "I_sample_period_s"]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--last", type=int, default=30); a = ap.parse_args()
    dm = pd.read_csv(P("drive_master.csv"), low_memory=False)
    out = {"n_drives": int(len(dm)), "n_days": int(dm["date"].nunique()) if "date" in dm else None,
           "date_range": [str(dm["date"].min()), str(dm["date"].max())] if "date" in dm else None,
           "duplicate_file_keys": int(dm["file"].duplicated().sum()) if "file" in dm else None}
    miss = dm.isna().mean().sort_values(ascending=False)
    out["missingness_gt5pct"] = {k: round(float(v), 3) for k, v in miss[miss > 0.05].items()}
    for c in ("ens_invalid", "ens_outlier_v2", "ens_extreme"):
        if c in dm:
            out[f"n_{c}"] = int(dm[c].astype(str).str.lower().eq("true").sum())
    for c in ("I_offset_2p_A_applied", "I_offset_A_applied"):
        if c in dm:
            u = dm[c].dropna().unique()
            out[c] = [float(x) for x in u[:3]]
    # shift of last N drives vs earlier
    ordered = dm.sort_values(["date", "time_start"]) if {"date", "time_start"} <= set(dm.columns) else dm
    new, old = ordered.tail(a.last), ordered.head(max(len(ordered) - a.last, 0))
    shift = {}
    try:
        from scipy.stats import ks_2samp
    except Exception:
        ks_2samp = None
    for c in KEY:
        if c in dm and pd.api.types.is_numeric_dtype(dm[c]):
            x, y = new[c].dropna().values, old[c].dropna().values
            if len(x) >= 5 and len(y) >= 20 and np.std(y) > 0:
                d = {"smd": round(float((x.mean() - y.mean()) / np.std(y)), 3), "n_new": int(len(x)), "n_old": int(len(y))}
                if ks_2samp:
                    d["ks"] = round(float(ks_2samp(x, y).statistic), 3)
                shift[c] = d
    # channel-availability events: counts are computed from the master; cause/reactivation are owner-reported context
    if {"T_intake", "date", "time_start"} <= set(dm.columns):
        ch = dm.sort_values(["date", "time_start"]).reset_index(drop=True)
        valid = ch.index[ch["T_intake"].notna()]
        if len(valid) and valid[-1] < len(ch) - 1:
            lv = int(valid[-1]); after = ch.iloc[lv + 1:]
            out["channel_status"] = {"T_intake": {
                "status": "unavailable", "sentinel_c": -100.0,
                "last_valid_drive": str(ch.at[lv, "file"]), "last_valid_date": str(ch.at[lv, "date"]),
                "n_drives_after_last_valid": int(len(after)), "n_nan_after_last_valid": int(after["T_intake"].isna().sum()),
                "n_days_after_last_valid": int(after["date"].nunique()),
                "context": "owner report: onset right after the battery-controller software update following the first drive of "
                           "2026-08-24; cause not established from the CSVs; reactivation attempt pending. Raw channel is a constant "
                           "-100 degC from 2026-08-24 10:46:12; the master NaNs it via the lo=-40 bound. Pack sensors 1-4 checked: no "
                           "evidence of change. Cold-start flag (warmupPoints) maps NaN to False = no data, not warm.",
                "ref": "CHANGELOG M319"}}
    out["last_n"] = a.last
    out["shift_last_n_vs_rest"] = shift
    out["shift_flags"] = [c for c, d in shift.items() if abs(d["smd"]) > 0.5 or d.get("ks", 0) > 0.4]
    if os.path.exists(P("seasonal_drive_master.csv")):
        sm = pd.read_csv(P("seasonal_drive_master.csv"), low_memory=False)
        out["cohorts"] = {k: {"n_drives": int(len(g)), "n_days": int(g["date"].nunique())} for k, g in sm.groupby("thermal_regime")}
    json.dump(out, open(P("data_health.json"), "w"), indent=1)
    print(json.dumps({k: out[k] for k in ("n_drives", "n_days", "shift_flags", "missingness_gt5pct")}, indent=1))


if __name__ == "__main__":
    main()
