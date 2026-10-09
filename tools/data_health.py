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


UNCOVERED_SOC_READERS = [   # M390 blind audit: raw-bytes readers of the SoC PID outside the frame loader / _series / the two patched rainflow functions
    "compute_summary_arrays._hf_perdrive (soc-balanced fuel dSoC, last minus first: interior spike has no effect)",
    "compute_summary_arrays._fcs_snapshot (full-cell case-study SoC)", "compute_summary_arrays._of_grid (warm-up / thermal fuel penalty SoC statistics)",
    "frame_loader-is-None fallbacks (no effect when the frame loader is supplied)",
    "energy_mc_precompute (start/end SoC and a coulomb cross-check; _series path to be confirmed)",
    "recon_engine (first-to-last dSoC, unaffected)", "m119v2_model (frozen, hash-gated; sees the glitch at 1 Hz)"]


def soc_spike_block(dm):
    """M390 (analyses/M390_spec.md): single-sample SoC logger-glitch rejection, counted from the raw files with the shared rule (soc_spike.py)."""
    import re, glob
    sys.path.insert(0, ROOT)
    import soc_spike as S
    raw_dir = os.environ.get("XT_RAW_DIR") or P("raw")
    if not os.path.isdir(raw_dir):
        return {"status": "not computed: raw directory not available"}
    dg = lambda n: re.sub(r"\D", "", os.path.basename(n))
    idx = {dg(f): f for f in glob.glob(os.path.join(raw_dir, "*.csv"))}
    n_files = n_int = 0; flagged = []; near = []
    for f in dm["file"].astype(str):
        path = idx.get(dg(f))
        if not path:
            continue
        try:
            d = pd.read_csv(path, usecols=["time", S.SOC_RAW_COL], low_memory=False)
        except Exception:
            continue
        t = pd.to_datetime(d["time"], format="mixed", errors="coerce")
        m = d[S.SOC_RAW_COL].notna() & t.notna()
        if m.sum() < 3:
            continue
        v = d.loc[m, S.SOC_RAW_COL].to_numpy(float)
        ts = ((t[m] - pd.Timestamp("1900-01-01")).dt.total_seconds()).to_numpy()
        n_files += 1; n_int += int(len(v) - 1)
        with_t, no_t = S.soc_spike_mask(v, ts), S.soc_spike_mask(v)
        for i in np.where(with_t)[0]:
            flagged.append({"file": f, "values": [float(v[i - 1]), float(v[i]), float(v[i + 1])],
                            "interval_before_s": round(float(ts[i] - ts[i - 1]), 3), "interval_after_s": round(float(ts[i + 1] - ts[i]), 3)})
        for i in np.where(no_t & ~with_t)[0]:
            near.append({"file": f, "values": [float(v[i - 1]), float(v[i]), float(v[i + 1])]})
    return {"rule": {"jump_pp": S.SOC_SPIKE_JUMP_PP, "neighbour_tol_pp": S.SOC_SPIKE_NEIGHBOUR_TOL_PP, "short_side_s": S.SOC_SPIKE_MAX_GAP_S, "verified": False,
                     "basis": "fixed, not tuned; a >=20 pp move within 5 s would imply roughly 300 kW if CAP_KWH=2.1 (verified:false), above the 150 kW motor rating (unverified); order-of-magnitude plausibility bound"},
            "files_with_soc": n_files, "intervals": n_int, "n_flagged": len(flagged), "flagged": flagged, "n_failing_only_time_guard": len(near), "failing_only_time_guard": near,
            "treatment": "logger glitch flagged as missing in the frame loader, per-drive code and the two rainflow functions; study figures are not corrected",
            "uncovered_readers": UNCOVERED_SOC_READERS, "no_time_guard_in_uncovered_readers": True, "ref": "CHANGELOG M388c, M390"}


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
    out["soc_spike"] = soc_spike_block(dm)
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
