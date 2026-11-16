#!/usr/bin/env python3
"""M702 (spec analyses/M702_spec.md Rev 1): current-step events and the apparent short-horizon step resistance R_sh = dV/dI between co-timed pre/post sample pairs.
Channels: [BMS] HV Battery Current (A) (charge-positive; discharge-positive Id = -v as in compute_drive_summary_v6, M11) and pack voltage on native timestamps (nearest within the pipeline tolerance), no resampling.
Usage:  python tools/step_events.py --feasibility OUT.json      (eligibility counts and the per-event table; no estimate)"""
import os, sys, json, hashlib
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(ROOT); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import numpy as np, pandas as pd
import compute_drive_summary_v6 as D

STEP_A = 20.0            # frozen at implementation (spec Rev 1): at least 20 current grid steps of 0.05 A would be 1 A; 20 A is the primary load-step size; 15 and 30 A are sensitivities
PRE_BAND_A = 5.0         # both pre-step samples within this band
POST_STAB = 0.20         # next post-step sample within 20 % of the first post-step value (when it exists)
SKEW_MAX_S = 0.25        # V-I timestamp skew cap (spec Rev 1 item 1)
NEIGH_S = 10.0           # non-overlap neighbourhood
EDGE_S = 20.0            # exclusion near a gap or drive boundary
GAP_FACTOR = 2.0         # a gap is a native interval above this multiple of the drive median
R_LO, R_HI = 0.0, 0.5    # plausibility window, Ohm (flag only)
REASONS = ["notStep", "preNotSteady", "postUnstable", "gap", "nearEdge", "overlap", "skewTooLarge", "noVoltage", "chargeDirection"]


def drive_events(csv_bytes, step_a=STEP_A, direction="discharge"):
    """Return (events DataFrame, exclusion counts, median interval s). direction: 'discharge' (primary) or 'charge' (sensitivity)."""
    df, t = D._prep_bytes(csv_bytes)
    I = D._series(df, t, "I")
    if I is not None:
        I = I[I["v"].abs() < 900].reset_index(drop=True)          # sentinel channel values never enter
    V = D._series(df, t, "V", lo=200, hi=450)
    exc = {k: 0 for k in REASONS}
    if I is None or V is None or len(I) < 10:
        return pd.DataFrame(), exc, None
    V = V.rename(columns={"v": "V"}); V["tV"] = V["t"]
    e = pd.merge_asof(I, V, on="t", direction="nearest", tolerance=pd.Timedelta(D.V_ALIGN_TOL))
    tt = (e["t"] - e["t"].iloc[0]).dt.total_seconds().values
    Id = -e["v"].values                                                # discharge-positive
    Vv = e["V"].values
    skew = np.abs((e["t"] - e["tV"]).dt.total_seconds().values)
    dt = np.diff(tt); med = float(np.median(dt))
    sign = 1.0 if direction == "discharge" else -1.0
    last_ev = -1e9; rows = []
    dur = tt[-1]
    gap_t = tt[1:][dt > GAP_FACTOR * med]
    for k in range(2, len(tt)):
        d = sign * (Id[k] - Id[k - 1])
        if d < step_a:
            if direction == "discharge" and (Id[k] - Id[k - 1]) <= -step_a:
                exc["chargeDirection"] += 1                              # a falling-discharge (charge-direction) step: counted, not primary
            else:
                exc["notStep"] += 1
            continue
        if abs(Id[k - 1] - Id[k - 2]) > PRE_BAND_A:
            exc["preNotSteady"] += 1; continue
        if k + 1 < len(tt) and abs(Id[k + 1] - Id[k]) > POST_STAB * max(abs(Id[k]), 1e-9):
            exc["postUnstable"] += 1; continue
        if tt[k] - tt[k - 1] > GAP_FACTOR * med or tt[k - 1] - tt[k - 2] > GAP_FACTOR * med:
            exc["gap"] += 1; continue
        if tt[k] < EDGE_S or tt[k] > dur - EDGE_S or (gap_t.size and np.min(np.abs(gap_t - tt[k])) < EDGE_S):
            exc["nearEdge"] += 1; continue
        if tt[k] - last_ev < NEIGH_S:
            exc["overlap"] += 1; continue
        if not (np.isfinite(Vv[k]) and np.isfinite(Vv[k - 1])):
            exc["noVoltage"] += 1; continue
        if skew[k] > SKEW_MAX_S or skew[k - 1] > SKEW_MAX_S:
            exc["skewTooLarge"] += 1; continue
        last_ev = tt[k]
        dI = Id[k] - Id[k - 1]; dV = Vv[k - 1] - Vv[k]
        R = dV / dI if dI else np.nan
        rows.append({"tRel": float(tt[k]), "gapS": float(tt[k] - tt[k - 1]), "skewPostS": float(skew[k]), "skewPreS": float(skew[k - 1]), "dI": float(dI), "Ipre": float(Id[k - 1]),
                     "Ipost": float(Id[k]), "dV": float(dV), "R_sh_ohm": float(R), "plausible": bool(R_LO < R < R_HI)})
    return pd.DataFrame(rows), exc, med


def feasibility(out):
    import ah_throughput as AH
    m = pd.read_csv("drive_master.csv", usecols=["file", "date", "ens_outlier_v2"], low_memory=False)
    m = m[m["ens_outlier_v2"].astype(str) == "False"].reset_index(drop=True)
    cad = pd.read_csv("cadence_regime.csv").set_index("file")["regime"]
    sm = pd.read_csv("seasonal_drive_master.csv", usecols=["file", "thermal_regime"]).set_index("file")["thermal_regime"]
    loader = AH.raw_loader(os.environ.get("XT_RAW_DIR") or os.path.join(ROOT, "raw"))
    ev_all, drives = [], []
    tot_exc = {k: 0 for k in REASONS}
    for _, r in m.iterrows():
        b = loader(r["file"])
        if b is None:
            continue
        ev, exc, med = drive_events(b)
        for k, v in exc.items():
            tot_exc[k] += v
        c = cad.get(r["file"]); c = c if isinstance(c, str) else "unknown"
        drives.append({"file": r["file"], "date": str(r["date"])[:10], "cadence": c, "thermal": sm.get(r["file"], "warm"), "medianIntervalS": med, "nEvents": int(len(ev)), "nPlausible": int(ev["plausible"].sum()) if len(ev) else 0})
        if len(ev):
            ev = ev.assign(file=r["file"], date=str(r["date"])[:10], cadence=c, thermal=sm.get(r["file"], "warm")); ev_all.append(ev)
    dr = pd.DataFrame(drives); ev = pd.concat(ev_all, ignore_index=True) if ev_all else pd.DataFrame()
    base = out.rsplit(".", 1)[0]
    dr.to_csv(base + "_perdrive.csv", index=False); ev.to_csv(base + "_events.csv", index=False)
    res = {"spec": "analyses/M702_spec.md Rev 1 item 11", "constants": {"STEP_A": STEP_A, "PRE_BAND_A": PRE_BAND_A, "POST_STAB": POST_STAB, "SKEW_MAX_S": SKEW_MAX_S, "NEIGH_S": NEIGH_S, "EDGE_S": EDGE_S, "GAP_FACTOR": GAP_FACTOR},
           "nCleanDrives": int(len(dr)), "exclusionCounts": tot_exc, "nEvents": int(len(ev)), "supportLadder": "10 drives with >= 3 events on 5 days", "strata": {}}
    for c in ("fast", "slow", "unknown"):
        d = dr[dr["cadence"] == c]; e = ev[ev["cadence"] == c] if len(ev) else ev
        ok = d[d["nEvents"] >= 3]
        res["strata"][c] = {"drives": int(len(d)), "drivesWithEvents": int((d["nEvents"] > 0).sum()), "drivesWithAtLeast3Events": int(len(ok)), "daysWithAtLeast3Events": int(ok["date"].nunique()), "events": int(len(e)),
                            "gapMedianS": float(e["gapS"].median()) if len(e) else None, "gapP90S": float(e["gapS"].quantile(0.9)) if len(e) else None,
                            "plausibleShare": float(e["plausible"].mean()) if len(e) else None,
                            "byMonth": {k: {"drives": int((g["nEvents"] >= 3).sum()), "events": int(g["nEvents"].sum())} for k, g in d.assign(month=d["date"].str[:7]).groupby("month")},
                            "byThermal": {k: {"drives": int((g["nEvents"] >= 3).sum()), "events": int(g["nEvents"].sum())} for k, g in d.groupby("thermal")}}
    res["scriptSha256"] = hashlib.sha256(open(__file__, "rb").read()).hexdigest()
    json.dump(res, open(out, "w", encoding="utf-8"), indent=1, default=str)
    print(json.dumps({"nEvents": res["nEvents"], "strata": {k: {kk: v[kk] for kk in ("drives", "drivesWithAtLeast3Events", "daysWithAtLeast3Events", "events", "gapMedianS")} for k, v in res["strata"].items()}}, default=str))


if __name__ == "__main__":
    if "--feasibility" in sys.argv:
        feasibility(sys.argv[sys.argv.index("--feasibility") + 1])
